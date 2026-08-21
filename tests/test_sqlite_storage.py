from __future__ import annotations

import sqlite3

import orjson

from app.models import RawShowItem, SourcePlatform
from app.pipeline.normalize import normalize_one
from app.repositories.storage.sqlite_store import SqliteStorage


def _raw(source_id: str, *, title: str = "测试演出") -> RawShowItem:
    return RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id=source_id,
        title=title,
    )


def test_save_raw_deduplicates_repeated_project_inside_one_batch(tmp_path):
    storage = SqliteStorage(tmp_path)

    storage.save_raw([_raw("1", title="旧标题"), _raw("1", title="新标题")])

    with sqlite3.connect(storage.db_path) as conn:
        rows = conn.execute(
            "SELECT title, payload FROM raw_items WHERE source = ? AND source_id = ?",
            ("damai", "1"),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "新标题"
    assert orjson.loads(rows[0][1])["title"] == "新标题"


def test_save_shows_defensively_splits_aggregate_sessions(tmp_path):
    storage = SqliteStorage(tmp_path)
    raw = _raw("multi")
    raw.sessions_raw = [
        {"id": "s1", "start_time": "2026-08-01 15:00", "date_key": "20260801"},
        {"id": "s2", "start_time": "2026-08-01 19:30", "date_key": "20260801"},
    ]
    aggregate = normalize_one(raw)
    assert aggregate is not None
    assert len(aggregate.sessions) == 2

    storage.save_shows([aggregate])

    with sqlite3.connect(storage.db_path) as conn:
        rows = conn.execute(
            "SELECT id, payload FROM shows WHERE source = ? AND source_id = ? ORDER BY start_time",
            ("damai", "multi"),
        ).fetchall()
    assert [row[0] for row in rows] == ["damai:multi:1", "damai:multi:2"]
    assert all(len(orjson.loads(row[1])["sessions"]) == 1 for row in rows)


def test_incomplete_recrawl_does_not_replace_existing_session_detail(tmp_path):
    storage = SqliteStorage(tmp_path)
    complete = _raw("protected", title="多场演出")
    complete.start_time_raw = "2026-08-01 15:00"
    complete.sessions_raw = [
        {
            "id": "s1",
            "start_time": "2026-08-01 15:00",
            "date_key": "20260801",
            "ticket_tiers": [{"sku_id": "a", "price": 180}],
        },
        {
            "id": "s2",
            "start_time": "2026-08-01 19:30",
            "date_key": "20260801",
            "ticket_tiers": [{"sku_id": "b", "price": 680}],
        },
    ]
    complete.raw_payload = {
        "detail": {"session_count": 2, "detail_complete": True}
    }
    complete_show = normalize_one(complete)
    assert complete_show is not None
    storage.save_raw([complete])
    storage.save_shows([complete_show])

    fallback = _raw("protected", title="多场演出")
    fallback.start_time_raw = "2026.08.01-08.02"
    fallback.raw_payload = {
        "from_api": True,
        "detail_fetch": {"success": False, "reason": "subpage unavailable"},
    }
    fallback_show = normalize_one(fallback)
    assert fallback_show is not None
    storage.save_raw([fallback])
    storage.save_shows([fallback_show])

    with sqlite3.connect(storage.db_path) as conn:
        show_rows = conn.execute(
            "SELECT payload FROM shows WHERE source = ? AND source_id = ? ORDER BY start_time",
            ("damai", "protected"),
        ).fetchall()
        raw_payload = conn.execute(
            "SELECT payload FROM raw_items WHERE source = ? AND source_id = ?",
            ("damai", "protected"),
        ).fetchone()[0]

    assert len(show_rows) == 2
    assert [
        orjson.loads(row[0])["sessions"][0]["session_id"] for row in show_rows
    ] == ["s1", "s2"]
    assert len(orjson.loads(raw_payload)["sessions_raw"]) == 2


def test_incomplete_recrawl_with_same_sessions_cannot_drop_ticket_tiers(tmp_path):
    storage = SqliteStorage(tmp_path)
    complete = _raw("tickets", title="票档保护")
    complete.sessions_raw = [
        {
            "id": "s1",
            "start_time": "2026-08-01 19:30",
            "ticket_tiers": [
                {"sku_id": "a", "price": 180},
                {"sku_id": "b", "price": 680},
            ],
        }
    ]
    complete.raw_payload = {"detail": {"detail_complete": True}}
    complete_show = normalize_one(complete)
    assert complete_show is not None
    storage.save_raw([complete])
    storage.save_shows([complete_show])

    partial = _raw("tickets", title="票档保护")
    partial.sessions_raw = [
        {"id": "s1", "start_time": "2026-08-01 19:30", "ticket_tiers": []}
    ]
    partial.raw_payload = {
        "detail": {
            "detail_complete": False,
            "ticket_sessions_failed": ["s1"],
        }
    }
    partial_show = normalize_one(partial)
    assert partial_show is not None
    storage.save_raw([partial])
    storage.save_shows([partial_show])

    with sqlite3.connect(storage.db_path) as conn:
        show_payload = conn.execute(
            "SELECT payload FROM shows WHERE source = ? AND source_id = ?",
            ("damai", "tickets"),
        ).fetchone()[0]
        raw_payload = conn.execute(
            "SELECT payload FROM raw_items WHERE source = ? AND source_id = ?",
            ("damai", "tickets"),
        ).fetchone()[0]

    assert len(orjson.loads(show_payload)["sessions"][0]["ticket_tiers"]) == 2
    assert len(orjson.loads(raw_payload)["sessions_raw"][0]["ticket_tiers"]) == 2


def test_recrawl_keeps_first_crawled_at_but_updates_content(tmp_path):
    """重采同一演出时保留首次采集时间 crawled_at，内容更新为新值。"""
    from datetime import datetime, timezone

    storage = SqliteStorage(tmp_path)

    first = _raw("keep-ts", title="首次标题")
    first.crawled_at = datetime(2026, 8, 17, 4, 0, 0, tzinfo=timezone.utc)
    first_show = normalize_one(first)
    assert first_show is not None
    storage.save_shows([first_show])

    second = _raw("keep-ts", title="重采标题")
    second.crawled_at = datetime(2026, 8, 21, 4, 0, 0, tzinfo=timezone.utc)
    second_show = normalize_one(second)
    assert second_show is not None
    storage.save_shows([second_show])

    with sqlite3.connect(storage.db_path) as conn:
        row = conn.execute(
            "SELECT title, crawled_at, normalized_at FROM shows WHERE source_id = ?",
            ("keep-ts",),
        ).fetchone()

    assert row is not None
    assert row[0] == "重采标题"  # 内容已更新
    assert row[1].startswith("2026-08-17")  # 首次采集时间保留
    assert row[2].startswith("2026-08-21")  # 最近规范化时间更新


def test_recrawl_removes_orphan_split_rows_when_sessions_shrink(tmp_path):
    """场次变少时清理旧的高序号拆分行，保留的行走冲突更新。"""
    storage = SqliteStorage(tmp_path)

    full = _raw("shrink", title="多场变少场")
    full.sessions_raw = [
        {"id": "s1", "start_time": "2026-08-01 15:00", "date_key": "20260801"},
        {"id": "s2", "start_time": "2026-08-02 19:30", "date_key": "20260802"},
        {"id": "s3", "start_time": "2026-08-03 19:30", "date_key": "20260803"},
    ]
    full.raw_payload = {"detail": {"detail_complete": True}}
    full_show = normalize_one(full)
    assert full_show is not None
    storage.save_shows([full_show])

    with sqlite3.connect(storage.db_path) as conn:
        before = conn.execute(
            "SELECT id FROM shows WHERE source_id = ? ORDER BY id",
            ("shrink",),
        ).fetchall()
    assert len(before) == 3

    shrink = _raw("shrink", title="多场变少场")
    shrink.sessions_raw = [
        {"id": "s1", "start_time": "2026-08-01 15:00", "date_key": "20260801"},
    ]
    shrink.raw_payload = {"detail": {"detail_complete": True}}
    shrink_show = normalize_one(shrink)
    assert shrink_show is not None
    storage.save_shows([shrink_show])

    with sqlite3.connect(storage.db_path) as conn:
        after = conn.execute(
            "SELECT id FROM shows WHERE source_id = ? ORDER BY id",
            ("shrink",),
        ).fetchall()
    assert len(after) == 1
    # 单场次聚合 show 的 id 不带序号后缀（防御拆分只拆多场次）
    assert after[0][0] in ("damai:shrink", "damai:shrink:1")


def test_identical_recrawl_skips_write_entirely(tmp_path):
    """完全重复（仅时间戳不同）的采集不产生任何写入：内容、时间戳全部保持原样。"""
    from datetime import datetime, timezone

    storage = SqliteStorage(tmp_path)

    first = _raw("noop", title="重复演出")
    first.start_time_raw = "2026-09-01 19:30"
    first.sessions_raw = [
        {"id": "s1", "start_time": "2026-09-01 19:30", "date_key": "20260901"}
    ]
    first.crawled_at = datetime(2026, 8, 17, 4, 0, 0, tzinfo=timezone.utc)
    first_show = normalize_one(first)
    assert first_show is not None
    storage.save_shows([first_show])

    with sqlite3.connect(storage.db_path) as conn:
        before = conn.execute(
            "SELECT title, crawled_at, normalized_at FROM shows WHERE source_id = ?",
            ("noop",),
        ).fetchone()

    # 21 号完全重复采集：内容不变，仅 crawled_at/normalized_at 不同
    dup = _raw("noop", title="重复演出")
    dup.start_time_raw = "2026-09-01 19:30"
    dup.sessions_raw = [
        {"id": "s1", "start_time": "2026-09-01 19:30", "date_key": "20260901"}
    ]
    dup.crawled_at = datetime(2026, 8, 21, 4, 0, 0, tzinfo=timezone.utc)
    dup_show = normalize_one(dup)
    assert dup_show is not None
    storage.save_shows([dup_show])

    with sqlite3.connect(storage.db_path) as conn:
        after = conn.execute(
            "SELECT title, crawled_at, normalized_at FROM shows WHERE source_id = ?",
            ("noop",),
        ).fetchone()

    assert after == before  # 完全重复：行一个字节都没变（含 normalized_at）


def test_changed_recrawl_updates_content_keeps_first_crawled_at(tmp_path):
    """有内容变化（如价格/状态）的重采：只更新内容，首次采集时间保留。"""
    from datetime import datetime, timezone

    storage = SqliteStorage(tmp_path)

    first = _raw("chg", title="价格变化演出")
    first.start_time_raw = "2026-09-01 19:30"
    first.sessions_raw = [
        {
            "id": "s1",
            "start_time": "2026-09-01 19:30",
            "date_key": "20260901",
            "ticket_tiers": [{"sku_id": "a", "price": 100}],
        }
    ]
    first.crawled_at = datetime(2026, 8, 17, 4, 0, 0, tzinfo=timezone.utc)
    first_show = normalize_one(first)
    assert first_show is not None
    storage.save_shows([first_show])

    changed = _raw("chg", title="价格变化演出")
    changed.start_time_raw = "2026-09-01 19:30"
    changed.sessions_raw = [
        {
            "id": "s1",
            "start_time": "2026-09-01 19:30",
            "date_key": "20260901",
            "ticket_tiers": [{"sku_id": "a", "price": 180}],
        }
    ]
    changed.crawled_at = datetime(2026, 8, 21, 4, 0, 0, tzinfo=timezone.utc)
    changed_show = normalize_one(changed)
    assert changed_show is not None
    storage.save_shows([changed_show])

    with sqlite3.connect(storage.db_path) as conn:
        row = conn.execute(
            "SELECT min_price, crawled_at FROM shows WHERE source_id = ?",
            ("chg",),
        ).fetchone()

    assert row[0] == 180.0  # 内容已更新为新价格
    assert row[1].startswith("2026-08-17")  # 首次采集时间保留
