"""秀动签名 HTTP API 采集策略。"""

from __future__ import annotations

import asyncio
import inspect
import random
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import httpx

from app.browser.captcha.base import CaptchaSolver
from app.crawlers.base import BaseCrawler, ItemCallback, ItemsCallback
from app.crawlers.showstart.captcha import ShowstartCaptchaSolver
from app.crawlers.showstart.client import ShowstartClient
from app.models import RawShowItem, SourcePlatform
from app.utils.timeparse import parse_chinese_datetime


class ShowstartCrawler(BaseCrawler):
    """通过秀动签名 JSON API 采集演出。"""

    source = SourcePlatform.SHOWSTART
    requires_browser = False

    def build_captcha_solver(self) -> CaptchaSolver:
        return ShowstartCaptchaSolver(self.config)

    @staticmethod
    def _ticket_price(value: Any) -> float | None:
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _status_from_show_time(cls, show_time: str) -> str:
        start = parse_chinese_datetime(show_time)
        if start is not None and start < datetime.utcnow():
            return "已结束"
        return "在售"

    @classmethod
    def _raw_item(
        cls,
        record: dict[str, Any],
        detail: dict[str, Any] | None = None,
    ) -> RawShowItem:
        source_id = str(record["id"])
        # 秀动列表 soldOut 字段恒为 1（采样 150/150），票档 status 恒为 0，
        # 均无法区分在售/售罄；唯一可靠信号是演出时间：已结束 vs 未开始。
        status = cls._status_from_show_time(str(record.get("showTime") or ""))
        detail_payload: dict[str, Any] = {}
        sessions: list[dict[str, Any]] = []
        artists: list[str] = []
        category = ""
        venue_address = ""
        if detail is not None:
            artists = [str(performer.get("name") or "") for performer in detail.get("performers", [])]
            artists = [name for name in artists if name]
            category = str(detail.get("styles") or "")
            site = detail.get("site") or {}
            venue_address = str(site.get("address") or "")
            tickets = detail.get("tickets") or []
            sessions = [
                {
                    "name": str(record.get("showTime") or ""),
                    "start_time": str(record.get("showTime") or ""),
                    "status": status,
                    "ticket_tiers": [
                        {
                            "name": str(ticket.get("ticketName") or ""),
                            "price": cls._ticket_price(ticket.get("sellPriceStr")),
                            "status": "onsale" if ticket.get("status") == 0 else "",
                            "salable": ticket.get("status") == 0,
                            "raw": (
                                f"{ticket.get('ticketName') or ''} "
                                f"{ticket.get('sellPriceStr') or ''}"
                            ),
                        }
                        for ticket in tickets
                    ],
                }
            ]
            detail_payload = {
                "detail_complete": True,
                "performers": artists,
                "styles": category,
                "site": site,
                "tickets": tickets,
            }
        return RawShowItem(
            source=SourcePlatform.SHOWSTART,
            source_id=source_id,
            url=f"https://www.showstart.com/event/{source_id}",
            title=str(record.get("title") or ""),
            city=str(record.get("cityName") or ""),
            venue_name=str(record.get("siteName") or ""),
            venue_address=venue_address,
            category=category,
            artists=artists,
            poster_url=str(record.get("poster") or ""),
            price_raw=str(record.get("price") or ""),
            status_raw=status,
            start_time_raw=str(record.get("showTime") or ""),
            sessions_raw=sessions,
            raw_payload={
                "record": record,
                "from_api": True,
                "detail": detail_payload,
            },
        )

    async def _emit_discovered(
        self,
        items: list[RawShowItem],
        callback: ItemsCallback | None,
    ) -> None:
        if callback is None:
            return
        result = callback(items)
        if inspect.isawaitable(result):
            await result

    async def _enrich_and_emit(
        self,
        client: ShowstartClient,
        item: RawShowItem,
        on_item: ItemCallback | None,
    ) -> RawShowItem:
        try:
            detail = await client.activity_info(item.source_id)
            enriched = self._raw_item(item.raw_payload["record"], detail)
        except (RuntimeError, httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            self.log.warning("showstart detail failed activity_id=%s error=%s", item.source_id, exc)
            enriched = item
        await self._emit_item(enriched, on_item)
        delay = self.config.crawl.detail_delay_seconds
        if delay > 0:
            await asyncio.sleep(delay * random.uniform(1.0, 1.25))
        return enriched

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
        client = ShowstartClient()
        try:
            params = await client.list_params()
            city_map = {str(city["cityName"]): str(city["cityCode"]) for city in params}
            style_map = {
                str(style["showName"]): str(style["key"])
                for city in params
                for style in city.get("styles", [])
            }
            show_style = style_map.get(category, "") if category else ""
            if category and not show_style:
                self.log.warning("unknown showstart category=%s; using all styles", category)
            items: list[RawShowItem] = []
            item_indexes: dict[str, int] = {}
            for city in cities:
                city_code = city_map.get(city)
                if city_code is None:
                    self.log.warning("unknown showstart city=%s; skipped", city)
                    continue
                for keyword in keywords or [""]:
                    pair_items: list[RawShowItem] = []
                    page_no = 1
                    while True:
                        page = await client.activity_list(
                            page_no=page_no,
                            city_code=city_code,
                            show_style=show_style,
                            keyword=keyword,
                        )
                        records = page.get("result") or []
                        if not records:
                            break
                        for record in records:
                            item = self._raw_item(record)
                            if item.source_id in item_indexes:
                                continue
                            item_indexes[item.source_id] = len(items)
                            items.append(item)
                            pair_items.append(item)
                        total_page = int(page.get("totalPage") or 0)
                        if (max_pages > 0 and page_no >= max_pages) or (
                            total_page > 0 and page_no >= total_page
                        ):
                            break
                        page_no += 1
                        await self._delay()
                    await self._emit_discovered(pair_items, on_items_discovered)
                    if self.config.crawl.enrich_detail:
                        for item in pair_items:
                            enriched = await self._enrich_and_emit(client, item, on_item)
                            index = item_indexes[item.source_id]
                            items[index] = enriched
                    else:
                        for item in pair_items:
                            await self._emit_item(item, on_item)
            return items
        finally:
            await client.aclose()
