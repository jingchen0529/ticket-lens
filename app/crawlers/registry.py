"""Crawler 注册表。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Type

from app.crawlers.base import BaseCrawler
from app.crawlers.damai import DamaiCrawler
from app.crawlers.maoyan import MaoyanCrawler
from app.models import SourcePlatform

if TYPE_CHECKING:
    from app.browser.session import BrowserSession
    from app.core.config import AppConfig

_REGISTRY: dict[SourcePlatform, Type[BaseCrawler]] = {
    SourcePlatform.DAMAI: DamaiCrawler,
    SourcePlatform.MAOYAN: MaoyanCrawler,
}


def list_crawlers() -> list[SourcePlatform]:
    return list(_REGISTRY.keys())


def get_crawler(
    source: SourcePlatform | str,
    session: "BrowserSession",
    config: "AppConfig",
) -> BaseCrawler:
    if isinstance(source, str):
        source = SourcePlatform(source)
    cls = _REGISTRY.get(source)
    if not cls:
        raise KeyError(f"unknown crawler source: {source}")
    return cls(session, config)
