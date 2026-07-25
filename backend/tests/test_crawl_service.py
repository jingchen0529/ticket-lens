"""Crawl orchestration must surface crawler failures in its public result."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import AppConfig
from app.models import CrawlJob, SourcePlatform
from app.services import crawl as crawl_service


@pytest.mark.asyncio
async def test_run_crawl_records_crawler_error(monkeypatch, tmp_path):
    config = AppConfig()
    config.storage.backend = "json"
    config.storage.output_dir = str(tmp_path)
    config.storage.run_subdir = False
    job = CrawlJob(sources=[SourcePlatform.DAMAI], cities=["上海"], max_pages=1)

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
