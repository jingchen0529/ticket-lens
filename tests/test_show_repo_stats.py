"""ShowRepository.stats() 的时区语义回归测试。

crawled_at 以 UTC 落库，而「今日」是客户所在时区的日历日。历史上 stats() 直接拿
本地日期串去比 UTC 日期串，在 UTC+8 的 00:00-08:00 会把当天数据算成前一天。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from app.repositories.show_repo import ShowRepository

_SCHEMA = """
CREATE TABLE shows (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    payload TEXT NOT NULL,
    crawled_at TEXT
);
"""


def _make_db(path, crawled_at_values: list[str]) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA)
        for i, ts in enumerate(crawled_at_values):
            conn.execute(
                "INSERT INTO shows (id, source, source_id, title, payload, crawled_at)"
                " VALUES (?,?,?,?,?,?)",
                (f"damai:{i}", "damai", str(i), f"演出{i}", "{}", ts),
            )


def _utc_stamp(local_dt: datetime) -> str:
    """把带时区的本地时间换成落库用的 naive UTC ISO 串。"""
    return local_dt.astimezone(UTC).replace(tzinfo=None).isoformat()


def test_stats_returns_zeros_when_db_missing(tmp_path):
    repo = ShowRepository(tmp_path / "nope.sqlite3")
    assert repo.stats() == {"total_shows": 0, "today_shows": 0}


def test_stats_counts_early_morning_local_records_as_today(tmp_path):
    """本地凌晨 1 点采集的数据，UTC 日期还是前一天，仍必须算进今日。"""
    local_midnight = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    db = tmp_path / "daxi.sqlite3"
    _make_db(
        db,
        [
            _utc_stamp(local_midnight + timedelta(hours=1)),   # 今日 01:00 本地
            _utc_stamp(local_midnight + timedelta(hours=13)),  # 今日 13:00 本地
            _utc_stamp(local_midnight - timedelta(hours=2)),   # 昨日 22:00 本地
            _utc_stamp(local_midnight + timedelta(days=1)),    # 明日 00:00 本地
        ],
    )

    stats = ShowRepository(db).stats()

    assert stats["total_shows"] == 4
    # 只有落在本地今天 [00:00, 次日 00:00) 区间内的两条算今日
    assert stats["today_shows"] == 2


def test_stats_excludes_records_outside_local_day(tmp_path):
    local_midnight = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    db = tmp_path / "daxi.sqlite3"
    _make_db(
        db,
        [
            _utc_stamp(local_midnight - timedelta(days=3)),
            _utc_stamp(local_midnight - timedelta(minutes=1)),
        ],
    )

    stats = ShowRepository(db).stats()

    assert stats["total_shows"] == 2
    assert stats["today_shows"] == 0
