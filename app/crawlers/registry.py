"""Crawler 注册表。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.crawlers.base import BaseCrawler
from app.crawlers.damai import DamaiCrawler
from app.crawlers.maoyan import MaoyanCrawler
from app.crawlers.showstart import ShowstartCrawler
from app.models import SourcePlatform

if TYPE_CHECKING:
    from app.browser.session import BrowserSession
    from app.core.config import AppConfig

_REGISTRY: dict[SourcePlatform, type[BaseCrawler]] = {
    SourcePlatform.DAMAI: DamaiCrawler,
    SourcePlatform.MAOYAN: MaoyanCrawler,
    SourcePlatform.SHOWSTART: ShowstartCrawler,
}


def list_crawlers() -> list[SourcePlatform]:
    return list(_REGISTRY.keys())


def get_crawler_class(source: SourcePlatform | str) -> type[BaseCrawler]:
    if isinstance(source, str):
        source = SourcePlatform(source)
    cls = _REGISTRY.get(source)
    if cls is None:
        raise KeyError(f"unknown crawler source: {source}")
    return cls


def get_crawler(
    source: SourcePlatform | str,
    session: "BrowserSession | None",
    config: "AppConfig",
) -> BaseCrawler:
    return get_crawler_class(source)(session, config)
