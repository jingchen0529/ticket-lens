"""只读数据访问：从固定 SQLite 库查询已清洗的 Show 数据。

采集侧用 SqliteStorage 累积写入固定库（upsert），API 侧只读。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import orjson


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

    def _build_where(self, q: ShowQuery) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if q.source:
            clauses.append("source = ?")
            params.append(q.source)
        if q.city:
            clauses.append("city = ?")
            params.append(q.city)
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

    def iter_for_export(self, q: ShowQuery) -> list[dict[str, Any]]:
        """导出用：不分页，取全部匹配记录。"""
        where, params = self._build_where(q)
        sql = f"SELECT payload FROM shows{where} ORDER BY start_time ASC NULLS LAST"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [orjson.loads(r["payload"]) for r in rows]

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
