"""只读数据访问：从固定 SQLite 库查询已清洗的 Show 数据。

采集侧用 SqliteStorage 累积写入固定库（upsert），API 侧只读。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import orjson

from app.utils.show_visibility import LEDGER_HIDDEN_CATEGORIES


@dataclass
class ShowQuery:
    """列表查询条件。"""

    source: str | None = None
    city: str | None = None
    category: str | None = None
    status: str | None = None
    perf_state: str | None = None  # 演出状态: upcoming/ongoing/done/cancelled
    keyword: str | None = None  # 标题模糊
    limit: int = 50
    offset: int = 0


# 允许排序的白名单列，避免 SQL 注入
_SORTABLE = {
    "start_time",
    "min_price",
    "max_price",
    "crawled_at",
    "normalized_at",
    "title",
}

# 演出状态 → 与今天（按日）比较的 SQL 运算符。
# 口径与 utils.showstate.performance_status 一致：
# cancelled 优先于时间判定；start_time 解析不出日期的记录不归入任何时间态。
_PERF_STATE_TIME_OP = {"upcoming": ">", "ongoing": "=", "done": "<"}

# 不对外展示的演出大类：这两类不属于台账口径，查询/导出/筛选项一律排除。
# 库里仍保留原始记录，只是查询层过滤，改动可逆。
_EXCLUDED_CATEGORIES = LEDGER_HIDDEN_CATEGORIES


class ShowRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        # 只读打开：库不存在时给出清晰错误
        if not self._db_path.exists():
            raise FileNotFoundError(
                f"数据库不存在: {self._db_path}，请先运行采集写入固定库"
            )
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def exists(self) -> bool:
        return self._db_path.exists()

    def stats(self) -> dict[str, int]:
        """统计数据：库内演出总数、今日新增采集数。

        crawled_at 落库用的是 UTC（models 里 default_factory=utcnow），而「今日」
        对客户来说是本地日历日，所以把本地当天的起止换算成 UTC 再按区间比较。
        直接拿本地日期串去比 UTC 日期串会在 CST 的 00:00-08:00 漏计当天数据。
        """
        if not self._db_path.exists():
            return {"total_shows": 0, "today_shows": 0}

        start_local = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # ISO 字符串按字典序比较即等价于时间序，去掉 tzinfo 与落库格式对齐
        start_utc = start_local.astimezone(UTC).replace(tzinfo=None).isoformat()
        end_utc = (
            (start_local + timedelta(days=1)).astimezone(UTC).replace(tzinfo=None).isoformat()
        )

        with self._connect() as conn:
            row_total = conn.execute("SELECT COUNT(*) AS n FROM shows").fetchone()
            total_shows = int(row_total["n"]) if row_total else 0

            row_today = conn.execute(
                "SELECT COUNT(*) AS n FROM shows WHERE crawled_at >= ? AND crawled_at < ?",
                (start_utc, end_utc),
            ).fetchone()
            today_shows = int(row_today["n"]) if row_today else 0

            return {
                "total_shows": total_shows,
                "today_shows": today_shows,
            }

    def _build_where(self, q: ShowQuery) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if q.source:
            clauses.append("source = ?")
            params.append(q.source)
        if q.city and q.city.lower() not in ("all", "全部", ""):
            c = q.city.strip()
            c_clean = c.replace("中国", "").replace("市", "").replace("特别行政区", "").strip()
            if c_clean and c_clean != c:
                clauses.append("(city = ? OR city = ? OR city LIKE ?)")
                params.extend([c, c_clean, f"%{c_clean}%"])
            else:
                clauses.append("(city = ? OR city LIKE ?)")
                params.extend([c, f"%{c}%"])
        if q.category:
            clauses.append("category = ?")
            params.append(q.category)
        if q.status:
            clauses.append("status = ?")
            params.append(q.status)
        if q.perf_state:
            if q.perf_state == "cancelled":
                clauses.append("status = 'cancelled'")
            elif q.perf_state in _PERF_STATE_TIME_OP:
                op = _PERF_STATE_TIME_OP[q.perf_state]
                clauses.append(
                    "(status IS NULL OR status != 'cancelled') "
                    f"AND date(start_time) {op} date(?)"
                )
                params.append(datetime.now().strftime("%Y-%m-%d"))
        if q.keyword:
            clauses.append("title LIKE ?")
            params.append(f"%{q.keyword}%")
        # 排除不对外展示的大类（展览休闲 / 体育）；NULL 分类保留
        if _EXCLUDED_CATEGORIES:
            placeholders = ",".join("?" for _ in _EXCLUDED_CATEGORIES)
            clauses.append(
                f"(category IS NULL OR category NOT IN ({placeholders}))"
            )
            params.extend(_EXCLUDED_CATEGORIES)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def count(self, q: ShowQuery) -> int:
        where, params = self._build_where(q)
        with self._connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM shows{where}", params).fetchone()
            return int(row["n"])

    def list_shows(
        self,
        q: ShowQuery,
        sort_by: str = "start_time",
        descending: bool = False,
    ) -> list[dict[str, Any]]:
        where, params = self._build_where(q)
        col = sort_by if sort_by in _SORTABLE else "start_time"
        order = "DESC" if descending else "ASC"
        sql = (
            f"SELECT payload FROM shows{where} "
            f"ORDER BY {col} {order} NULLS LAST LIMIT ? OFFSET ?"
        )
        params = [*params, q.limit, q.offset]
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [orjson.loads(r["payload"]) for r in rows]

    def iter_for_export(
        self, q: ShowQuery, ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """导出用：不分页。

        - ids 非空时：只导出这些 id（前端勾选导出），忽略筛选条件。
        - ids 为空/None 时：导出全部匹配筛选条件的记录。
        """
        if ids:
            # 用占位符批量 IN 查询，保序：按前端勾选顺序返回
            placeholders = ",".join("?" for _ in ids)
            sql = f"SELECT id, payload FROM shows WHERE id IN ({placeholders})"
            with self._connect() as conn:
                rows = conn.execute(sql, list(ids)).fetchall()
            by_id = {r["id"]: orjson.loads(r["payload"]) for r in rows}
            return [by_id[i] for i in ids if i in by_id]

        where, params = self._build_where(q)
        sql = f"SELECT payload FROM shows{where} ORDER BY start_time ASC NULLS LAST"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [orjson.loads(r["payload"]) for r in rows]

    def delete_shows(
        self, q: ShowQuery, ids: list[str] | None = None
    ) -> dict[str, int]:
        """按范围删除演出（勾选的 ids 或筛选条件），并连带删除对应的 raw_items。

        - ids 非空：只删这些 id（前端勾选清除），忽略筛选条件。
        - ids 为空：删全部匹配筛选条件的记录。
        crawl_runs 采集历史属全局记录、非单条演出产物，此处保留（整库清空走 clear_data）。
        返回 {"shows": n, "raw_items": m}。库不存在时返回全 0。
        """
        counts = {"shows": 0, "raw_items": 0}
        if not self._db_path.exists():
            return counts
        with self._get_db_conn_rw() as conn:
            # 先定位目标演出的 (source, source_id)，用于连带清对应 raw_items
            if ids:
                placeholders = ",".join("?" for _ in ids)
                rows = conn.execute(
                    f"SELECT source, source_id FROM shows WHERE id IN ({placeholders})",
                    list(ids),
                ).fetchall()
                del_sql = f"DELETE FROM shows WHERE id IN ({placeholders})"
                del_params: list[Any] = list(ids)
            else:
                where, params = self._build_where(q)
                rows = conn.execute(
                    f"SELECT source, source_id FROM shows{where}", params
                ).fetchall()
                del_sql = f"DELETE FROM shows{where}"
                del_params = params
            pairs = [(r["source"], r["source_id"]) for r in rows]
            counts["shows"] = len(pairs)
            conn.execute(del_sql, del_params)
            # 连带删除对应 raw_items（按 source + source_id 匹配）
            for source, source_id in pairs:
                cur = conn.execute(
                    "DELETE FROM raw_items WHERE source = ? AND source_id = ?",
                    (source, source_id),
                )
                if cur.rowcount and cur.rowcount > 0:
                    counts["raw_items"] += cur.rowcount
            conn.commit()
            # 释放已删除数据占用的磁盘空间
            conn.execute("VACUUM")
        return counts

    def clear_data(self) -> dict[str, int]:
        """清空采集数据：shows / raw_items / crawl_runs 三张表。

        保留 cities 主表（预设城市）与设置，只删采集产物。
        返回各表删除前的行数，供前端提示。库不存在时返回全 0。
        """
        counts = {"shows": 0, "raw_items": 0, "crawl_runs": 0}
        if not self._db_path.exists():
            return counts
        with self._get_db_conn_rw() as conn:
            for table in counts:
                try:
                    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                    counts[table] = int(row["n"])
                    conn.execute(f"DELETE FROM {table}")
                except sqlite3.OperationalError:
                    # 表不存在（老库）时跳过
                    pass
            # 回收 autoincrement 计数，避免 id 无限增长
            try:
                conn.execute(
                    "DELETE FROM sqlite_sequence WHERE name IN ('raw_items','crawl_runs')"
                )
            except sqlite3.OperationalError:
                pass
            conn.commit()
            # 释放已删除数据占用的磁盘空间
            conn.execute("VACUUM")
        return counts

    def get_show(self, show_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM shows WHERE id = ?", (show_id,)
            ).fetchone()
        return orjson.loads(row["payload"]) if row else None

    def _get_db_conn_rw(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        from app.repositories.storage.sqlite_store import _SCHEMA
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn

    def facets(self) -> dict[str, list[str]]:
        """筛选项：从数据库获取 cities 基础主数据以及可用的 source / category / status 取值。"""
        out: dict[str, list[str]] = {"source": [], "city": [], "category": [], "status": []}
        # 确保数据库文件与 cities 主表建表与数据 seed 成功
        try:
            with self._get_db_conn_rw() as rw_conn:
                from app.core.cities import seed_cities_table
                seed_cities_table(rw_conn)
        except Exception:
            pass

        if not self._db_path.exists():
            return out

        with self._connect() as conn:
            for field in ("source", "category", "status"):
                try:
                    rows = conn.execute(
                        f"SELECT DISTINCT {field} AS v FROM shows "
                        f"WHERE {field} IS NOT NULL AND {field} != '' ORDER BY {field}"
                    ).fetchall()
                    out[field] = [r["v"] for r in rows]
                except Exception:
                    out[field] = []

            # 预设平台：包含大麦网(damai)与猫眼(maoyan)
            for s in ("damai", "maoyan"):
                if s not in out["source"]:
                    out["source"].append(s)

            # 分类下拉同样排除不对外的大类，与查询/导出口径一致
            out["category"] = [
                c for c in out["category"] if c not in _EXCLUDED_CATEGORIES
            ]

            # 核心：从数据库 cities 表读取全量预设城市
            cities_list: list[str] = []
            try:
                c_rows = conn.execute(
                    "SELECT name FROM cities ORDER BY sort_order ASC, id ASC"
                ).fetchall()
                cities_list = [r["name"] for r in c_rows]
            except Exception:
                pass

            # 动态补齐 shows 数据中真实存在但不在预设表里的城市
            try:
                d_rows = conn.execute(
                    "SELECT DISTINCT city AS v FROM shows WHERE city IS NOT NULL AND city != ''"
                ).fetchall()
                existing = set(cities_list)
                for r in d_rows:
                    v = r["v"]
                    if v and v not in existing:
                        cities_list.append(v)
                        existing.add(v)
            except Exception:
                pass

            out["city"] = cities_list
        return out
