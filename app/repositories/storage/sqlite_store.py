"""SQLite 存储（统一 Show + 原始 JSON）。"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import orjson

from app.core.cities import seed_cities_table
from app.models import CrawlResult, RawShowItem, Show
from app.pipeline.normalize import split_show_by_sessions
from app.repositories.storage.base import Storage

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shows (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    city TEXT,
    venue_name TEXT,
    category TEXT,
    status TEXT,
    min_price REAL,
    max_price REAL,
    start_time TEXT,
    url TEXT,
    poster_url TEXT,
    payload TEXT NOT NULL,
    crawled_at TEXT,
    normalized_at TEXT
);

CREATE TABLE IF NOT EXISTS raw_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT,
    title TEXT,
    payload TEXT NOT NULL,
    crawled_at TEXT
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    sort_order INTEGER DEFAULT 0
);
"""


class SqliteStorage(Storage):
    def __init__(self, root: Path, db_path: Path | None = None) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        # db_path 显式指定时用固定库（前端/API 持久查询），否则落在 run 目录里
        self._db_path = Path(db_path) if db_path else self._root / "daxi.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        seed_cities_table(self._conn)

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def root(self) -> Path:
        return self._root

    @staticmethod
    def _raw_session_quality(payload: str | bytes | dict) -> tuple[int, bool, int]:
        try:
            data = orjson.loads(payload) if not isinstance(payload, dict) else payload
        except (orjson.JSONDecodeError, TypeError):
            return (0, False, 0)
        sessions = data.get("sessions_raw") if isinstance(data, dict) else []
        sessions = sessions if isinstance(sessions, list) else []
        tier_count = 0
        for session in sessions:
            tiers = session.get("ticket_tiers") if isinstance(session, dict) else []
            tier_count += len(tiers) if isinstance(tiers, list) else 0
        detail = (data.get("raw_payload") or {}).get("detail") if isinstance(data, dict) else {}
        detail = detail if isinstance(detail, dict) else {}
        complete = bool(detail.get("detail_complete", bool(sessions)))
        return (len(sessions), complete, tier_count)

    @staticmethod
    def _show_payload_quality(payloads: list[str]) -> tuple[int, bool, bool, int]:
        enriched = False
        complete = False
        tier_count = 0
        for payload in payloads:
            try:
                data = orjson.loads(payload)
            except (orjson.JSONDecodeError, TypeError):
                continue
            extras = data.get("extras") if isinstance(data, dict) else {}
            extras = extras if isinstance(extras, dict) else {}
            enriched = enriched or bool(extras.get("detail_enriched"))
            complete = complete or bool(extras.get("detail_complete"))
            sessions = data.get("sessions") if isinstance(data, dict) else []
            for session in sessions if isinstance(sessions, list) else []:
                tiers = session.get("ticket_tiers") if isinstance(session, dict) else []
                tier_count += len(tiers) if isinstance(tiers, list) else 0
        return (len(payloads), enriched, complete, tier_count)

    def save_raw(self, items: list[RawShowItem]) -> Path:
        # 同一批内也先去重。旧实现只先 DELETE 再批量 INSERT；若批次本身含
        # 4 个相同项目，仍会一次插入 4 行。
        seen: set[tuple[str, str]] = set()
        unique_reversed: list[RawShowItem] = []
        for item in reversed(items):
            if item.source_id:
                key = (item.source.value, item.source_id)
                if key in seen:
                    continue
                seen.add(key)
            unique_reversed.append(item)
        unique_items = list(reversed(unique_reversed))
        existing_raw: dict[tuple[str, str], str] = {}
        for item in unique_items:
            if not item.source_id:
                continue
            row = self._conn.execute(
                "SELECT payload FROM raw_items WHERE source = ? AND source_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (item.source.value, item.source_id),
            ).fetchone()
            if row:
                existing_raw[(item.source.value, item.source_id)] = str(row[0])

        protected_items: list[RawShowItem] = []
        for item in unique_items:
            key = (item.source.value, item.source_id)
            old_payload = existing_raw.get(key)
            if old_payload:
                old_count, _old_complete, old_tiers = self._raw_session_quality(old_payload)
                new_payload = item.model_dump(mode="json")
                new_count, new_complete, new_tiers = self._raw_session_quality(new_payload)
                if old_count > 0 and new_count == 0:
                    logger.warning(
                        "keep existing raw detail source=%s source_id=%s old_sessions=%s "
                        "new_sessions=0",
                        item.source.value,
                        item.source_id,
                        old_count,
                    )
                    continue
                if old_count > new_count and not new_complete:
                    logger.warning(
                        "keep existing raw detail source=%s source_id=%s old_sessions=%s "
                        "new_sessions=%s new_complete=false",
                        item.source.value,
                        item.source_id,
                        old_count,
                        new_count,
                    )
                    continue
                if old_tiers > new_tiers and not new_complete:
                    logger.warning(
                        "keep existing raw detail source=%s source_id=%s old_tiers=%s "
                        "new_tiers=%s new_complete=false",
                        item.source.value,
                        item.source_id,
                        old_tiers,
                        new_tiers,
                    )
                    continue
            protected_items.append(item)
        unique_items = protected_items
        rows = [
            (
                i.source.value,
                i.source_id,
                i.title,
                orjson.dumps(i.model_dump(mode="json")).decode(),
                i.crawled_at.isoformat() if i.crawled_at else None,
            )
            for i in unique_items
        ]
        # 去重：raw_items 原来是纯 INSERT，每次采集无脑追加，同一 (source, source_id)
        # 会重复堆积、库无限膨胀。改为「先删同键旧行再插」，与 shows 的 upsert 口径一致。
        # source_id 为空的条目无法判重，保持原样直接插入。
        keyed = [(s, sid) for s, sid, *_ in rows if sid]
        if keyed:
            self._conn.executemany(
                "DELETE FROM raw_items WHERE source = ? AND source_id = ?",
                keyed,
            )
        self._conn.executemany(
            "INSERT INTO raw_items (source, source_id, title, payload, crawled_at) VALUES (?,?,?,?,?)",
            rows,
        )
        self._conn.commit()
        # 同步一份 JSON 方便查看
        json_path = self._root / "raw_items.json"
        json_path.write_bytes(
            orjson.dumps(
                [i.model_dump(mode="json") for i in unique_items],
                option=orjson.OPT_INDENT_2,
            )
        )
        return json_path

    def save_shows(self, shows: list[Show]) -> Path:
        # 存储边界再兜底一次：调用方即使传入尚未拆分的聚合 Show，也必须按
        # sessions 展开，不能把“接口返回一次”误当成“一条展示记录”。
        split_shows: list[Show] = []
        for show in shows:
            if len(show.sessions) > 1:
                split_shows.extend(split_show_by_sessions(show))
            else:
                split_shows.append(show)
        shows = split_shows
        incoming_by_key: dict[tuple[str, str], list[Show]] = {}
        for show in shows:
            if show.source_id:
                incoming_by_key.setdefault((show.source.value, show.source_id), []).append(show)

        # 预读本批涉及演出的现有行（含旧拆分行）：同时服务「防劣化保护」
        # 与「完全重复跳过写入」。比较时剔除 crawled_at/normalized_at——
        # 重采必然带新时间戳，业务内容完全相同的行不应产生任何写入动作。
        existing_by_id: dict[str, str] = {}
        existing_by_key: dict[tuple[str, str], list[str]] = {}
        if incoming_by_key:
            conds = " OR ".join(
                "(source = ? AND source_id = ?)" for _ in incoming_by_key
            )
            params: list[str] = []
            for source, source_id in incoming_by_key:
                params.extend([source, source_id])
            for row_id, source, source_id, payload in self._conn.execute(
                f"SELECT id, source, source_id, payload FROM shows WHERE {conds}",
                params,
            ):
                existing_by_id[str(row_id)] = str(payload)
                existing_by_key.setdefault((str(source), str(source_id)), []).append(
                    str(payload)
                )

        def content_key(payload: str) -> dict[str, Any]:
            data = orjson.loads(payload)
            data.pop("crawled_at", None)
            data.pop("normalized_at", None)
            return data

        protected_keys: set[tuple[str, str]] = set()
        for key, incoming in incoming_by_key.items():
            existing_payloads = existing_by_key.get(key) or []
            if not existing_payloads:
                continue
            old_quality = self._show_payload_quality(existing_payloads)
            new_quality = self._show_payload_quality(
                [orjson.dumps(show.model_dump(mode="json")).decode() for show in incoming]
            )
            old_count, old_enriched, old_complete, old_tiers = old_quality
            new_count, new_enriched, new_complete, new_tiers = new_quality
            if old_enriched and not new_enriched:
                protected_keys.add(key)
            elif old_count > new_count and not new_complete:
                protected_keys.add(key)
            elif old_tiers > new_tiers and not new_complete:
                protected_keys.add(key)

        for source, source_id in protected_keys:
            logger.warning(
                "keep existing show detail source=%s source_id=%s because incoming detail "
                "is missing or incomplete",
                source,
                source_id,
            )

        if protected_keys:
            shows = [
                show
                for show in shows
                if (show.source.value, show.source_id) not in protected_keys
            ]
        rows = []
        skipped_unchanged = 0
        for s in shows:
            payload = orjson.dumps(s.model_dump(mode="json")).decode()
            old = existing_by_id.get(s.id)
            if old is not None and content_key(old) == content_key(payload):
                # 与库中内容完全一致（仅时间戳不同）→ 不入库，保持原行原样。
                skipped_unchanged += 1
                continue
            rows.append(
                (
                    s.id,
                    s.source.value,
                    s.source_id,
                    s.title,
                    s.venue.city,
                    s.venue.name,
                    s.category,
                    s.status.value,
                    s.price.min_price,
                    s.price.max_price,
                    s.start_time.isoformat() if s.start_time else None,
                    s.url,
                    s.poster_url,
                    payload,
                    s.crawled_at.isoformat() if s.crawled_at else None,
                    s.normalized_at.isoformat() if s.normalized_at else None,
                )
            )
        if skipped_unchanged:
            logger.info("sqlite save_shows skipped %s unchanged rows", skipped_unchanged)
        # 一条演出会按场次拆成多行（id = source:source_id:序号）。重采时若场次
        # 变少，纯 upsert 会让旧的高序号拆分行残留成孤儿：只删除本批不再出现的
        # 拆分行，仍存在的行保留（ON CONFLICT 不覆盖 crawled_at，保住首次采集
        # 时间；否则重采会把历史数据全部归到今天，按采集日期查询/导出失真）。
        ids_by_key: dict[tuple[str, str], list[str]] = {}
        for s in shows:
            if s.source_id:
                ids_by_key.setdefault((s.source.value, s.source_id), []).append(s.id)
        for (source, source_id), ids in ids_by_key.items():
            if not ids:
                continue
            placeholders = ",".join("?" for _ in ids)
            self._conn.execute(
                f"DELETE FROM shows WHERE source = ? AND source_id = ? "
                f"AND id NOT IN ({placeholders})",
                (source, source_id, *ids),
            )
        self._conn.executemany(
            """
            INSERT INTO shows (
                id, source, source_id, title, city, venue_name, category, status,
                min_price, max_price, start_time, url, poster_url, payload,
                crawled_at, normalized_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                city=excluded.city,
                venue_name=excluded.venue_name,
                category=excluded.category,
                status=excluded.status,
                min_price=excluded.min_price,
                max_price=excluded.max_price,
                start_time=excluded.start_time,
                url=excluded.url,
                poster_url=excluded.poster_url,
                payload=excluded.payload,
                normalized_at=excluded.normalized_at
            """,
            rows,
        )
        self._conn.commit()
        json_path = self._root / "shows.json"
        json_path.write_bytes(
            orjson.dumps([s.model_dump(mode="json") for s in shows], option=orjson.OPT_INDENT_2)
        )
        return json_path

    def save_result(self, result: CrawlResult) -> Path:
        payload = orjson.dumps(result.model_dump(mode="json")).decode()
        self._conn.execute("INSERT INTO crawl_runs (payload) VALUES (?)", (payload,))
        self._conn.commit()
        path = self._root / "result.json"
        path.write_bytes(orjson.dumps(result.model_dump(mode="json"), option=orjson.OPT_INDENT_2))
        return path
