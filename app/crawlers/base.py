"""Crawler 策略基类。

大麦 / 猫眼各自独立目录实现 crawl + captcha，但输入输出契约一致：
  输入：城市、关键词、页数
  输出：list[RawShowItem]
"""

from __future__ import annotations

import abc
import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence

from playwright.async_api import Page

from app.browser.captcha.base import CaptchaSolver
from app.browser.session import BrowserSession
from app.core.config import AppConfig
from app.models import RawShowItem, SourcePlatform

logger = logging.getLogger(__name__)

ItemCallback = Callable[[RawShowItem], Awaitable[None] | None]
ItemsCallback = Callable[[list[RawShowItem]], Awaitable[None] | None]


class BaseCrawler(abc.ABC):
    source: SourcePlatform

    def __init__(self, session: BrowserSession, config: AppConfig) -> None:
        self.session = session
        self.config = config
        self.log = logging.getLogger(f"crawler.{self.source.value}")
        self.captcha: CaptchaSolver = self.build_captcha_solver()

    @abc.abstractmethod
    def build_captcha_solver(self) -> CaptchaSolver:
        """返回本平台专属验证码策略。"""

    @abc.abstractmethod
    async def crawl(
        self,
        *,
        cities: Sequence[str],
        keywords: Sequence[str],
        max_pages: int,
        category: str = "",
        on_item: ItemCallback | None = None,
        on_items_discovered: ItemsCallback | None = None,
    ) -> list[RawShowItem]:
        """执行采集，返回平台原始条目。"""

    async def _emit_item(self, item: RawShowItem, on_item: ItemCallback | None) -> None:
        """把完整条目交给编排层；回调可同步也可异步。"""
        if on_item is None:
            return
        result = on_item(item)
        if inspect.isawaitable(result):
            await result

    async def goto(self, page: Page, url: str, *, wait_until: str = "domcontentloaded") -> None:
        """导航并自动处理本平台验证码。"""
        await self.session.goto(page, url, wait_until=wait_until, captcha=self.captcha)

    async def _delay(self) -> None:
        delay = self.config.crawl.request_delay_seconds
        if delay > 0:
            await asyncio.sleep(delay)

    async def _scroll_page(self, page: Page, times: int = 3) -> None:
        pause = self.config.crawl.scroll_pause_ms
        for _ in range(times):
            await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            await page.wait_for_timeout(pause)
