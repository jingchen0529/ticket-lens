"""/api/shows 与 /api/export 的采集日期区间参数回归测试。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import orjson
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.storage.sqlite_store import _SCHEMA

client = TestClient(app)


def _local_midnight() -> datetime:
    return datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _day(offset_days: int) -> str:
    return (_local_midnight() + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def _seed_db(tmp_path, monkeypatch):
    """建一个每天各一条（今天 / 昨天 / 前天 / 10 天前）的临时库，并接到路由上。"""
    db = tmp_path / "daxi.sqlite3"
    local_midnight = _local_midnight()
    offsets = [0, -1, -2, -10]

    with sqlite3.connect(db) as conn:
        conn.executescript(_SCHEMA)
        for index, offset in enumerate(offsets):
            crawled = local_midnight + timedelta(days=offset, hours=1)
            payload = orjson.dumps(
                {"id": f"damai:{index}", "title": f"演出{index}", "start_time": None}
            ).decode()
            conn.execute(
                "INSERT INTO shows "
                "(id, source, source_id, title, payload, crawled_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"damai:{index}",
                    "damai",
                    str(index),
                    f"演出{index}",
                    payload,
                    crawled.astimezone(UTC).replace(tzinfo=None).isoformat(),
                ),
            )

    from app.core.config import load_config

    cfg = load_config()
    cfg.storage.db_path = str(db)
    monkeypatch.setattr("app.routers.shows.load_config", lambda: cfg)
    return db


def test_shows_endpoint_filters_by_date_range(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)

    res = client.get("/api/shows", params={"date_from": _day(-2), "date_to": _day(0)})

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


def test_shows_endpoint_accepts_single_sided_range(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)

    res = client.get("/api/shows", params={"date_from": _day(-1)})

    assert res.status_code == 200
    assert res.json()["total"] == 2


def test_shows_endpoint_keeps_single_date_compatibility(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)

    res = client.get("/api/shows", params={"date": _day(0)})

    assert res.status_code == 200
    assert res.json()["total"] == 1


def test_shows_endpoint_rejects_malformed_date_range(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)

    assert client.get("/api/shows", params={"date_from": "2026/01/01"}).status_code == 422
    assert client.get("/api/shows", params={"date_to": "20260101"}).status_code == 422


def test_export_endpoint_honours_date_range(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)

    res = client.get(
        "/api/export",
        params={"fmt": "csv", "date_from": _day(-2), "date_to": _day(0)},
    )

    assert res.status_code == 200
    # 表头里有跨行字段，按数据行前缀计数
    data_rows = [line for line in res.text.splitlines() if line.startswith("damai:")]
    assert len(data_rows) == 3
