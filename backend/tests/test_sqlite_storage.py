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
