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
