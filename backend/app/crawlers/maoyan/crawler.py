"""猫眼演出 crawler 策略。

策略特点：
- 入口 show.maoyan.com H5/列表页（hash 路由）
- 优先监听美团/猫眼 mapi、show 列表 XHR
- DOM 回退解析列表卡片
- 验证码：crawlers/maoyan/captcha.py（美团 Yoda / 滑块，自动过验证）
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any, Sequence
from urllib.parse import quote, urlencode

from playwright.async_api import Page, Response

from app.browser.captcha.base import CaptchaSolver
from app.crawlers.base import BaseCrawler
from app.crawlers.maoyan.captcha import MaoyanCaptchaSolver
from app.models import RawShowItem, SourcePlatform
from app.utils.text import clean_text

logger = logging.getLogger(__name__)

_MAOYAN_API_HINTS = (
    "show.maoyan.com",
    "maoyan.com/api",
    "m.maoyan.com",
    "wx.maoyan.com",
    "showapi",
    "performance",
    "project/list",
    "search/shows",
    "ajax/search",
    "myshow",
)


class MaoyanCrawler(BaseCrawler):
    source = SourcePlatform.MAOYAN

    def build_captcha_solver(self) -> CaptchaSolver:
        return MaoyanCaptchaSolver(self.config)

    async def crawl(
        self,
        *,
        cities: Sequence[str],
        keywords: Sequence[str],
        max_pages: int,
    ) -> list[RawShowItem]:
        items: list[RawShowItem] = []
        kw_list = list(keywords) if keywords else [""]

        async with self.session.page() as page:
            for city in cities:
                for keyword in kw_list:
                    pages_label = "全部" if not max_pages or max_pages <= 0 else str(max_pages)
                    self.log.info(
                        "maoyan crawl city=%s keyword=%r pages=%s", city, keyword, pages_label
                    )
                    page_items = await self._crawl_city_keyword(page, city, keyword, max_pages)
                    items.extend(page_items)
                    await self._delay()

        self.log.info("maoyan done raw=%s", len(items))
        return items

    async def _crawl_city_keyword(
        self,
        page: Page,
        city: str,
        keyword: str,
        max_pages: int,
    ) -> list[RawShowItem]:
        collected: list[RawShowItem] = []
        api_payloads: list[dict[str, Any]] = []

        async def on_response(response: Response) -> None:
            try:
                url = response.url
                if not any(h in url for h in _MAOYAN_API_HINTS):
                    return
                if response.status != 200:
                    return
                ctype = response.headers.get("content-type", "")
                if "json" not in ctype and "javascript" not in ctype and "text" not in ctype:
                    return
                text = await response.text()
                data = self._try_parse_json(text)
                if data is not None:
                    api_payloads.append({"url": url, "data": data})
            except Exception as exc:  # noqa: BLE001
                self.log.debug("maoyan intercept skip: %s", exc)

        page.on("response", on_response)

        # max_pages<=0：不设硬上限，空页/无新条目时自然停
        page_cap = max_pages if max_pages and max_pages > 0 else None
        page_no = 1
        while page_cap is None or page_no <= page_cap:
            url = self._build_list_url(city, keyword, page_no)
            api_payloads.clear()
            try:
                await self.goto(page, url, wait_until="networkidle")
            except Exception as exc:  # noqa: BLE001
                self.log.warning("maoyan networkidle fail, fallback: %s", exc)
                await self.goto(page, url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)

            # 猫眼 SPA 可能需要点「加载更多」
            if page_no > 1:
                await self._try_load_more(page)

            await self._scroll_page(page, times=3)
            await page.wait_for_timeout(1000)

            batch: list[RawShowItem] = []
            if api_payloads:
                for payload in api_payloads:
                    batch.extend(self._parse_api_payload(payload, city=city))

            if not batch:
                batch = await self._parse_dom(page, city=city)

            # 去重（SPA 滚动可能重复）
            seen = {i.source_id for i in collected if i.source_id}
            new_items = [i for i in batch if not i.source_id or i.source_id not in seen]
            if not new_items:
                self.log.info("maoyan empty/dup page city=%s kw=%r page=%s", city, keyword, page_no)
                break

            collected.extend(new_items)
            self.log.info(
                "maoyan city=%s kw=%r page=%s got=%s",
                city,
                keyword,
                page_no,
                len(new_items),
            )
            page_no += 1
            await self._delay()

        page.remove_listener("response", on_response)
        return collected

    def _build_list_url(self, city: str, keyword: str, page_no: int) -> str:
        """构造猫眼演出列表 / 搜索 URL。

        猫眼前端路由多变，这里用几套常见形态；页面加载后靠 XHR + DOM 兜底。
        """
        base = self.config.sources.maoyan.base_url or "https://show.maoyan.com"
        if keyword:
            # 搜索页
            q = urlencode({"keyword": keyword, "cityName": city}, quote_via=quote)
            return f"{base}/qqw#/search?{q}"
        # 列表页
        q = urlencode({"cityName": city, "pageNo": page_no}, quote_via=quote)
        list_url = self.config.sources.maoyan.list_url or f"{base}/qqw#/list"
        sep = "&" if "?" in list_url or "#" in list_url else "?"
        # hash 路由参数拼在 hash 后
        if "#/" in list_url:
            if "?" in list_url.split("#", 1)[-1]:
                return f"{list_url}&cityName={quote(city)}&pageNo={page_no}"
            return f"{list_url}?cityName={quote(city)}&pageNo={page_no}"
        return f"{list_url}{sep}{q}"

    async def _try_load_more(self, page: Page) -> None:
        selectors = [
            "text=加载更多",
            "text=查看更多",
            ".load-more",
            "[class*='loadMore']",
            "[class*='load-more']",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() and await el.is_visible():
                    await el.click()
                    await page.wait_for_timeout(1500)
                    return
            except Exception:  # noqa: BLE001
                continue

    @staticmethod
    def _try_parse_json(body: str) -> dict[str, Any] | list[Any] | None:
        body = body.strip()
        if not body:
            return None
        if body.startswith("callback") or "({" in body[:20]:
            m = re.search(r"\((\{.*\}|\[.*\])\)\s*;?\s*$", body, re.S)
            if m:
                body = m.group(1)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    def _parse_api_payload(self, payload: dict[str, Any], *, city: str) -> list[RawShowItem]:
        records = self._extract_records(payload.get("data"))
        items: list[RawShowItem] = []
        for rec in records:
            item = self._record_to_raw(rec, city=city, from_api=True)
            if item:
                items.append(item)
        return items

    def _extract_records(self, data: Any) -> list[dict[str, Any]]:
        if data is None:
            return []
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if not isinstance(data, dict):
            return []

        for key in (
            "projects",
            "shows",
            "list",
            "records",
            "performanceList",
            "projectList",
            "data",
            "result",
        ):
            val = data.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val  # type: ignore[return-value]
            if isinstance(val, dict):
                nested = self._extract_records(val)
                if nested:
                    return nested

        found: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, list) and node and isinstance(node[0], dict):
                sample = node[0]
                keys = {str(k).lower() for k in sample.keys()}
                if keys & {"performanceid", "projectid", "showid", "id", "itemid"} and keys & {
                    "name",
                    "title",
                    "performancename",
                    "projectname",
                    "showname",
                }:
                    found.extend(x for x in node if isinstance(x, dict))
                    return
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)
        return found

    def _record_to_raw(
        self,
        rec: dict[str, Any],
        *,
        city: str,
        from_api: bool,
    ) -> RawShowItem | None:
        source_id = str(
            rec.get("performanceId")
            or rec.get("projectId")
            or rec.get("showId")
            or rec.get("id")
            or rec.get("itemId")
            or ""
        )
        title = clean_text(
            str(
                rec.get("performanceName")
                or rec.get("projectName")
                or rec.get("showName")
                or rec.get("name")
                or rec.get("title")
                or ""
            )
        )
        if not title and not source_id:
            return None

        venue = clean_text(
            str(
                rec.get("shopName")
                or rec.get("venueName")
                or rec.get("venue")
                or rec.get("address")
                or ""
            )
        )
        city_name = clean_text(
            str(rec.get("cityName") or rec.get("city") or rec.get("city_name") or city)
        )
        price_raw = clean_text(
            str(
                rec.get("priceRange")
                or rec.get("price")
                or rec.get("minPrice")
                or rec.get("lowestPrice")
                or ""
            )
        )
        if isinstance(rec.get("minPrice"), (int, float)) and not price_raw:
            max_p = rec.get("maxPrice")
            if max_p is not None:
                price_raw = f"{rec['minPrice']}-{max_p}"
            else:
                price_raw = str(rec["minPrice"])

        status_raw = clean_text(str(rec.get("saleStatus") or rec.get("status") or rec.get("ticketStatus") or ""))
        start_raw = clean_text(
            str(
                rec.get("showTime")
                or rec.get("startTime")
                or rec.get("showTimeRange")
                or rec.get("performanceTime")
                or ""
            )
        )
        category = clean_text(str(rec.get("categoryName") or rec.get("category") or rec.get("typeName") or ""))
        poster = str(
            rec.get("posterUrl")
            or rec.get("poster")
            or rec.get("imgUrl")
            or rec.get("pic")
            or rec.get("cover")
            or ""
        )
        url = str(rec.get("detailUrl") or rec.get("url") or rec.get("link") or "")
        if source_id and not url:
            url = f"https://show.maoyan.com/qqw#/detail/{source_id}"

        return RawShowItem(
            source=SourcePlatform.MAOYAN,
            source_id=source_id or self._fallback_id(title, venue, start_raw),
            url=url,
            title=title,
            city=city_name,
            venue_name=venue,
            category=category,
            poster_url=poster,
            price_raw=price_raw,
            status_raw=status_raw,
            start_time_raw=start_raw,
            raw_payload={"from_api": from_api, "record": rec},
            crawled_at=datetime.utcnow(),
        )

    async def _parse_dom(self, page: Page, *, city: str) -> list[RawShowItem]:
        items: list[RawShowItem] = []
        selectors = [
            ".show-list .show-item",
            ".list-item",
            "[class*='show-item']",
            "[class*='project-item']",
            "a[href*='detail']",
        ]
        cards = []
        for sel in selectors:
            cards = await page.query_selector_all(sel)
            if len(cards) >= 1:
                self.log.debug("maoyan dom selector hit: %s count=%s", sel, len(cards))
                break

        for card in cards:
            try:
                href = await card.get_attribute("href") or ""
                if not href:
                    link = await card.query_selector("a[href]")
                    href = (await link.get_attribute("href")) if link else ""

                source_id = ""
                for pattern in (r"detail[/=](\d+)", r"[?&]id=(\d+)", r"/(\d{5,})"):
                    m = re.search(pattern, href or "")
                    if m:
                        source_id = m.group(1)
                        break

                title_el = await card.query_selector(
                    ".title, .name, [class*='title'], [class*='name'], h3, h2"
                )
                title = clean_text(await title_el.inner_text()) if title_el else ""
                if not title:
                    full = clean_text(await card.inner_text())
                    title = full.split("\n", 1)[0] if full else ""

                venue_el = await card.query_selector(
                    ".venue, .address, [class*='venue'], [class*='address'], [class*='shop']"
                )
                venue = clean_text(await venue_el.inner_text()) if venue_el else ""

                time_el = await card.query_selector(".time, [class*='time'], [class*='date']")
                start_raw = clean_text(await time_el.inner_text()) if time_el else ""

                price_el = await card.query_selector(".price, [class*='price']")
                price_raw = clean_text(await price_el.inner_text()) if price_el else ""

                img_el = await card.query_selector("img")
                poster = ""
                if img_el:
                    poster = (await img_el.get_attribute("src")) or (
                        await img_el.get_attribute("data-src")
                    ) or ""

                if not title:
                    continue

                if href and href.startswith("//"):
                    href = "https:" + href
                elif href and href.startswith("/"):
                    href = "https://show.maoyan.com" + href
                elif href and href.startswith("#"):
                    href = "https://show.maoyan.com/qqw" + href

                items.append(
                    RawShowItem(
                        source=SourcePlatform.MAOYAN,
                        source_id=source_id or self._fallback_id(title, venue, start_raw),
                        url=href or "",
                        title=title,
                        city=city,
                        venue_name=venue,
                        poster_url=poster,
                        price_raw=price_raw,
                        start_time_raw=start_raw,
                        raw_payload={"from_api": False},
                        crawled_at=datetime.utcnow(),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log.debug("maoyan card parse error: %s", exc)

        return items

    @staticmethod
    def _fallback_id(title: str, venue: str, start: str) -> str:
        raw = f"{title}|{venue}|{start}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
