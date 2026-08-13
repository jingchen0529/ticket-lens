"""ShowRepository 采集日期筛选的时区语义回归测试。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from app.repositories.show_repo import ShowQuery, ShowRepository
from app.repositories.storage.sqlite_store import _SCHEMA


def _utc_stamp(local_dt: datetime) -> str:
    return local_dt.astimezone(UTC).replace(tzinfo=None).isoformat()


def test_date_filter_uses_local_calendar_day(tmp_path):
    local_midnight = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    db = tmp_path / "daxi.sqlite3"
    timestamps = [
        _utc_stamp(local_midnight + timedelta(hours=1)),
        _utc_stamp(local_midnight + timedelta(hours=13)),
        _utc_stamp(local_midnight - timedelta(minutes=1)),
        _utc_stamp(local_midnight + timedelta(days=1)),
    ]

    with sqlite3.connect(db) as conn:
        conn.executescript(_SCHEMA)
        for index, timestamp in enumerate(timestamps):
            conn.execute(
                "INSERT INTO shows "
                "(id, source, source_id, title, payload, crawled_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"damai:{index}",
                    "damai",
                    str(index),
                    f"演出{index}",
                    "{}",
                    timestamp,
                ),
            )

    query = ShowQuery(date=local_midnight.strftime("%Y-%m-%d"))

    assert ShowRepository(db).count(query) == 2
