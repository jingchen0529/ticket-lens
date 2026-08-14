"""Crawl orchestration must surface crawler failures in its public result."""

from contextlib import asynccontextmanager
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import AppConfig
from app.models import CrawlJob, RawShowItem, SourcePlatform
from app.services import crawl as crawl_service


@pytest.mark.asyncio
async def test_run_crawl_records_crawler_error(monkeypatch, tmp_path):
    config = AppConfig()
    config.storage.backend = "json"
    config.storage.output_dir = str(tmp_path)
    config.storage.run_subdir = False
    job = CrawlJob(
        sources=[SourcePlatform.DAMAI],
        cities=["上海"],
        category="演唱会",
        max_pages=1,
    )

    session = SimpleNamespace(save_platform_cookies=AsyncMock())

    @asynccontextmanager
    async def fake_browser_session(*args, **kwargs):
        yield session

    crawler = SimpleNamespace(crawl=AsyncMock(side_effect=RuntimeError("searchajax down")))
    monkeypatch.setattr(crawl_service, "browser_session", fake_browser_session)
    monkeypatch.setattr(crawl_service, "get_crawler", lambda *args, **kwargs: crawler)

    result = await crawl_service.run_crawl(job, config)

    assert result.errors == ["damai: searchajax down"]
    assert result.raw_count == 0
    assert result.show_count == 0
    assert result.by_source == {}
    assert crawler.crawl.await_args.kwargs["category"] == "演唱会"


@pytest.mark.asyncio
async def test_run_crawl_keeps_legacy_crawler_callback_signature(monkeypatch, tmp_path):
    config = AppConfig()
    config.storage.backend = "json"
    config.storage.output_dir = str(tmp_path)
    config.storage.run_subdir = False
    job = CrawlJob(sources=[SourcePlatform.DAMAI], cities=["北京"], max_pages=1)
    session = SimpleNamespace(save_platform_cookies=AsyncMock())

    @asynccontextmanager
    async def fake_browser_session(*args, **kwargs):
        yield session

    class LegacyCrawler:
        async def crawl(
            self,
            *,
            cities,
            keywords,
            max_pages,
            category,
            on_item,
        ):
            _ = (cities, keywords, max_pages, category, on_item)
            return []

    monkeypatch.setattr(crawl_service, "browser_session", fake_browser_session)
    monkeypatch.setattr(crawl_service, "get_crawler", lambda *args: LegacyCrawler())

    result = await crawl_service.run_crawl(job, config)

    assert result.errors == []


@pytest.mark.asyncio
async def test_run_crawl_persists_split_rows_before_crawler_finishes(monkeypatch, tmp_path):
    config = AppConfig()
    config.storage.backend = "sqlite"
    config.storage.db_path = str(tmp_path / "stream.sqlite3")
    config.storage.output_dir = str(tmp_path)
    config.storage.run_subdir = False
    job = CrawlJob(sources=[SourcePlatform.DAMAI], cities=["上海"], max_pages=1)
    raw = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="stream-1",
        title="即时拆分",
        category="体育",
        sessions_raw=[
            {"id": "a", "start_time": "2026-08-01 15:00", "date_key": "20260801"},
            {"id": "b", "start_time": "2026-08-01 19:30", "date_key": "20260801"},
        ],
    )
    session = SimpleNamespace(save_platform_cookies=AsyncMock())

    @asynccontextmanager
    async def fake_browser_session(*args, **kwargs):
        yield session

    class StreamingCrawler:
        async def crawl(self, *, on_item, **_kwargs):
            await on_item(raw)
            with sqlite3.connect(config.storage.db_path) as conn:
                assert conn.execute("SELECT COUNT(*) FROM shows").fetchone()[0] == 2
            return [raw]

    monkeypatch.setattr(crawl_service, "browser_session", fake_browser_session)
    monkeypatch.setattr(crawl_service, "get_crawler", lambda *args, **kwargs: StreamingCrawler())

    result = await crawl_service.run_crawl(job, config)

    assert result.raw_count == 1
    assert result.show_count == 2
    assert result.ledger_visible_count == 0
    assert result.ledger_hidden_count == 2
    assert result.ledger_hidden_by_category == {"体育": 2}


@pytest.mark.asyncio
async def test_run_crawl_keeps_discovered_list_checkpoint_when_detail_stops(
    monkeypatch,
    tmp_path,
):
    config = AppConfig()
    config.storage.backend = "sqlite"
    config.storage.db_path = str(tmp_path / "checkpoint.sqlite3")
    config.storage.output_dir = str(tmp_path)
    config.storage.run_subdir = False
    job = CrawlJob(sources=[SourcePlatform.DAMAI], cities=["北京"], max_pages=1)
    listed = [
        RawShowItem(
            source=SourcePlatform.DAMAI,
            source_id="1007108168970",
            title="待恢复项目",
            price_raw="39-360",
        ),
        RawShowItem(
            source=SourcePlatform.DAMAI,
            source_id="2",
            title="后续待处理项目",
        ),
    ]
    session = SimpleNamespace(save_platform_cookies=AsyncMock())

    @asynccontextmanager
    async def fake_browser_session(*args, **kwargs):
        yield session

    class InterruptedCrawler:
        async def crawl(self, *, on_items_discovered, on_item, **_kwargs):
            await on_items_discovered(listed)
            listed[0].sessions_raw = [
                {
                    "id": "complete-session",
                    "start_time": "2026-08-20 19:30",
                    "date_key": "20260820",
                }
            ]
            await on_item(listed[0])
            raise RuntimeError("PC detail circuit open")

    monkeypatch.setattr(crawl_service, "browser_session", fake_browser_session)
    monkeypatch.setattr(
        crawl_service,
        "get_crawler",
        lambda *args, **kwargs: InterruptedCrawler(),
    )

    result = await crawl_service.run_crawl(job, config)

    assert result.errors == ["damai: PC detail circuit open"]
    assert result.raw_count == 1
    assert result.show_count == 1
    assert result.by_source == {"damai": 1}
    with sqlite3.connect(config.storage.db_path) as conn:
        rows = conn.execute(
            "SELECT source_id, payload FROM raw_items ORDER BY source_id"
        ).fetchall()
        assert [row[0] for row in rows] == ["1007108168970", "2"]
        assert conn.execute("SELECT COUNT(*) FROM shows").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_json_snapshots_survive_cancellation_during_detail(monkeypatch, tmp_path):
    import asyncio
    import json

    config = AppConfig()
    config.storage.backend = "json"
    config.storage.output_dir = str(tmp_path)
    config.storage.run_subdir = False
    job = CrawlJob(sources=[SourcePlatform.DAMAI], cities=["北京"], max_pages=1)
    listed = [
        RawShowItem(
            source=SourcePlatform.DAMAI,
            source_id="done",
            title="已完成详情",
        ),
        RawShowItem(
            source=SourcePlatform.DAMAI,
            source_id="pending",
            title="待处理详情",
        ),
    ]
    session = SimpleNamespace(save_platform_cookies=AsyncMock())

    @asynccontextmanager
    async def fake_browser_session(*args, **kwargs):
        yield session

    class CancelledCrawler:
        async def crawl(self, *, on_items_discovered, on_item, **_kwargs):
            await on_items_discovered(listed)
            listed[0].sessions_raw = [
                {
                    "id": "done-session",
                    "start_time": "2026-08-20 19:30",
                    "date_key": "20260820",
                }
            ]
            await on_item(listed[0])
            raise asyncio.CancelledError()

    monkeypatch.setattr(crawl_service, "browser_session", fake_browser_session)
    monkeypatch.setattr(
        crawl_service,
        "get_crawler",
        lambda *args, **kwargs: CancelledCrawler(),
    )

    with pytest.raises(asyncio.CancelledError):
        await crawl_service.run_crawl(job, config)

    raw_payload = json.loads((tmp_path / "raw_items.json").read_text(encoding="utf-8"))
    show_payload = json.loads((tmp_path / "shows.json").read_text(encoding="utf-8"))
    assert {item["source_id"] for item in raw_payload} == {"done", "pending"}
    assert [show["source_id"] for show in show_payload] == ["done"]
