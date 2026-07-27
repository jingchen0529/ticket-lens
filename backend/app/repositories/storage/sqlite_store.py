"""SQLite 存储（统一 Show + 原始 JSON）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import orjson

from app.core.cities import seed_cities_table
from app.models import CrawlResult, RawShowItem, Show
from app.repositories.storage.base import Storage

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

    def save_raw(self, items: list[RawShowItem]) -> Path:
        rows = [
            (
                i.source.value,
                i.source_id,
                i.title,
                orjson.dumps(i.model_dump(mode="json")).decode(),
                i.crawled_at.isoformat() if i.crawled_at else None,
            )
            for i in items
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
            orjson.dumps([i.model_dump(mode="json") for i in items], option=orjson.OPT_INDENT_2)
        )
        return json_path

    def save_shows(self, shows: list[Show]) -> Path:
        rows = []
        for s in shows:
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
                    orjson.dumps(s.model_dump(mode="json")).decode(),
                    s.crawled_at.isoformat() if s.crawled_at else None,
                    s.normalized_at.isoformat() if s.normalized_at else None,
                )
            )
        # 一条演出会按场次拆成多行（id = source:source_id:序号）。重采时若场次
        # 变少，纯 upsert 会让旧的高序号拆分行残留成孤儿。改为先按本批出现的
        # (source, source_id) 删掉该演出的所有旧拆分行，再整体重插。
        keyed = {(s.source.value, s.source_id) for s in shows if s.source_id}
        if keyed:
            self._conn.executemany(
                "DELETE FROM shows WHERE source = ? AND source_id = ?",
                list(keyed),
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
