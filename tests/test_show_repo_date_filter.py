"""ShowRepository 采集日期筛选的时区语义与区间语义回归测试。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from app.repositories.show_repo import ShowQuery, ShowRepository
from app.repositories.storage.sqlite_store import _SCHEMA


def _utc_stamp(local_dt: datetime) -> str:
    return local_dt.astimezone(UTC).replace(tzinfo=None).isoformat()


def _local_midnight() -> datetime:
    return datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _seed(db, timestamps: list[str]) -> ShowRepository:
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
    return ShowRepository(db)


def _day(offset_days: int) -> str:
    return (_local_midnight() + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def test_date_filter_uses_local_calendar_day(tmp_path):
    local_midnight = _local_midnight()
    repo = _seed(
        tmp_path / "daxi.sqlite3",
        [
            _utc_stamp(local_midnight + timedelta(hours=1)),
            _utc_stamp(local_midnight + timedelta(hours=13)),
            _utc_stamp(local_midnight - timedelta(minutes=1)),
            _utc_stamp(local_midnight + timedelta(days=1)),
        ],
    )

    assert repo.count(ShowQuery(date=local_midnight.strftime("%Y-%m-%d"))) == 2


def _range_repo(tmp_path) -> ShowRepository:
    """每天各一条：今天 / 昨天 / 前天 / 6 天前 / 10 天前。"""
    local_midnight = _local_midnight()
    return _seed(
        tmp_path / "daxi.sqlite3",
        [
            _utc_stamp(local_midnight + timedelta(hours=1)),
            _utc_stamp(local_midnight - timedelta(days=1) + timedelta(hours=1)),
            _utc_stamp(local_midnight - timedelta(days=2) + timedelta(hours=1)),
            _utc_stamp(local_midnight - timedelta(days=6) + timedelta(hours=1)),
            _utc_stamp(local_midnight - timedelta(days=10) + timedelta(hours=1)),
        ],
    )


def test_date_range_includes_both_endpoints(tmp_path):
    """近 7 天 = [今天-6, 今天]，两端都含在内。"""
    repo = _range_repo(tmp_path)

    assert repo.count(ShowQuery(date_from=_day(-6), date_to=_day(0))) == 4


def test_date_range_single_sided_is_unbounded(tmp_path):
    repo = _range_repo(tmp_path)

    # 只给起点：今天与昨天
    assert repo.count(ShowQuery(date_from=_day(-1))) == 2
    # 只给终点：前天及更早
    assert repo.count(ShowQuery(date_to=_day(-2))) == 3


def test_date_range_swaps_reversed_endpoints(tmp_path):
    repo = _range_repo(tmp_path)

    assert repo.count(ShowQuery(date_from=_day(0), date_to=_day(-6))) == 4


def test_date_range_takes_precedence_over_single_date(tmp_path):
    repo = _range_repo(tmp_path)

    query = ShowQuery(date=_day(-10), date_from=_day(-2), date_to=_day(0))
    assert repo.count(query) == 3


def test_no_date_filter_returns_all(tmp_path):
    repo = _range_repo(tmp_path)

    assert repo.count(ShowQuery()) == 5
