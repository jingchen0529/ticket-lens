"""猫眼演出 crawler 策略。

策略特点：
- 移动端直连 m.dianping.com API（最快最稳）
- 城市ID 映射 + 分页抓取
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

import httpx

from app.browser.captcha.base import CaptchaSolver
from app.crawlers.base import BaseCrawler, ItemCallback
from app.crawlers.maoyan.captcha import MaoyanCaptchaSolver
from app.models import RawShowItem, SourcePlatform
from app.utils.text import clean_text

logger = logging.getLogger(__name__)

_MAOYAN_CITY_IDS = {
    "北京": 1, "上海": 2, "广州": 3, "深圳": 4,
    "杭州": 5, "成都": 6, "武汉": 7, "南京": 8,
    "西安": 9, "重庆": 10, "天津": 11, "苏州": 12,
    "长沙": 13, "青岛": 14, "郑州": 15, "厦门": 16,
    "福州": 17, "合肥": 18, "宁波": 19, "无锡": 20,
    "沈阳": 21, "大连": 22, "济南": 23, "昆明": 24,
    "佛山": 25, "东莞": 26, "珠海": 27, "温州": 28,
    "贵阳": 29, "石家庄": 30, "太原": 31, "哈尔滨": 32,
    "南昌": 33, "南宁": 34, "兰州": 35, "乌鲁木齐": 36,
    "海口": 37, "三亚": 38, "银川": 39, "呼和浩特": 40,
    "银川": 39,
}


def _get_city_id(city: str) -> int:
    """将城市名映射为猫眼 cityId。"""
    return _MAOYAN_CITY_IDS.get(city.strip(), 1)


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
        on_item: ItemCallback | None = None,
    ) -> list[RawShowItem]:
        items: list[RawShowItem] = []
        seen_projects: set[str] = set()
        kw_list = list(keywords) if keywords else [""]

        async with self.session.page() as page:
            for city in cities:
                for keyword in kw_list:
                    pages_label = "全部" if not max_pages or max_pages <= 0 else str(max_pages)
                    self.log.info(
                        "maoyan crawl city=%s keyword=%r pages=%s", city, keyword, pages_label
                    )
                    page_items = await self._crawl_city_keyword(page, city, keyword, max_pages)
                    for item in page_items:
                        key = item.source_id or item.url
                        if key and key in seen_projects:
                            continue
                        if key:
                            seen_projects.add(key)
                        items.append(item)
                        await self._emit_item(item, on_item)
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
        city_id = _get_city_id(city)
        self.log.info("maoyan mobile API crawl: city=%s cityId=%s keyword=%r", city, city_id, keyword)

        page_cap = max_pages if max_pages and max_pages > 0 else 5
        page_no = 1
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            while page_no <= page_cap:
                api_url = (
                    f"https://m.dianping.com/myshow/ajax/performances/{city_id}"
                    f";st=0;p={page_no};s=10;tft=0?cityId={city_id}&sellChannel=7"
                )
                self.log.info("maoyan fetching page=%s", page_no)

                try:
                    resp = await client.get(api_url, headers={
                        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
                        "Referer": f"https://m.dianping.com/myshow/{city_id}",
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    })

                    if resp.status_code != 200:
                        self.log.warning("maoyan API status=%s page=%s", resp.status_code, page_no)
                        break

                    data = self._try_parse_json(resp.text)
                    if not data or not isinstance(data, dict):
                        self.log.warning("maoyan invalid JSON response page=%s", page_no)
                        break

                    records = data.get("data", [])
                    if not isinstance(records, list) or not records:
                        self.log.info("maoyan empty page=%s, stopping", page_no)
                        break

                    batch_items: list[RawShowItem] = []
                    for rec in records:
                        if not isinstance(rec, dict):
                            continue
                        item = self._record_to_raw(rec, city=city, from_api=True)
                        if item and item.source_id not in seen_ids:
                            seen_ids.add(item.source_id)
                            batch_items.append(item)

                    self.log.info(
                        "maoyan page=%s records=%s new_items=%s",
                        page_no, len(records), len(batch_items),
                    )

                    if not batch_items:
                        break

                    collected.extend(batch_items)
                    page_no += 1
                    await self._delay()

                except Exception as exc:  # noqa: BLE001
                    self.log.warning("maoyan API error page=%s: %s", page_no, exc)
                    break

        self.log.info("maoyan crawl finished: city=%s total_items=%s", city, len(collected))
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
        # 列表页 - 支持多个入口（qqw 可能已调整）
        list_url = self.config.sources.maoyan.list_url or f"{base}/qqw#/list"
        # 备选入口
        if "qqw#/list" in list_url:
            list_url = f"{base}/qqw#/list"
        elif "list" not in list_url.lower():
            list_url = f"{base}/qqw#/list"

        q = urlencode({"cityName": city, "pageNo": page_no}, quote_via=quote)
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

        # Much more comprehensive Maoyan keys (newer responses often use these)
        for key in (
            "projects",
            "shows",
            "list",
            "records",
            "performanceList",
            "projectList",
            "data",
            "result",
            "performances",
            "items",
            "content",
            "pageData",
            "resultData",
            "dataList",
            "listData",
            "resultList",
            "performanceList",
            "projectList",
            "itemList",
            "showList",
            "eventList",
            "activities",
            "recommend",
            "recommendList",
        ):
            val = data.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                self.log.debug("maoyan extracted %s records from key=%s", len(val), key)
                return val  # type: ignore[return-value]
            if isinstance(val, dict):
                nested = self._extract_records(val)
                if nested:
                    return nested

        # Enhanced walk for nested objects (very common in Maoyan JSON)
        found: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, list) and node and isinstance(node[0], dict):
                sample = node[0]
                keys = {str(k).lower() for k in sample.keys()}
                if keys & {"performanceid", "projectid", "showid", "id", "itemid", "performanceid", "projectid"} and keys & {
                    "name",
                    "title",
                    "performancename",
                    "projectname",
                    "showname",
                    "venue",
                    "shop",
                    "nameNoHtml",
                    "title",
                }:
                    found.extend(x for x in node if isinstance(x, dict))
                    self.log.debug("maoyan walk found %s items", len(found))
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
            "[class*='performance-item']",
            "[class*='item']",
            "a[href*='detail']",
            ".performance",
            ".item",
            "[data-item-id]",
            "[data-show-id]",
            "[data-project-id]",
            ".title",
            ".name",
            ".venue",
            ".price",
            ".time",
            ".date",
            "a[href*='/detail/']",
            ".show-item",
            ".performance-item",
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
                for pattern in (r"detail[/=](\d+)", r"[?&]id=(\d+)", r"/(\d{5,})", r"itemId=(\d+)", r"showId=(\d+)", r"projectId=(\d+)"):
                    m = re.search(pattern, href or "")
                    if m:
                        source_id = m.group(1)
                        break

                title_el = await card.query_selector(
                    ".title, .name, [class*='title'], [class*='name'], h3, h2, .item-title"
                )
                title = clean_text(await title_el.inner_text()) if title_el else ""
                if not title:
                    full = clean_text(await card.inner_text())
                    title = full.split("\n", 1)[0] if full else ""

                venue_el = await card.query_selector(
                    ".venue, .address, [class*='venue'], [class*='address'], [class*='shop'], .location"
                )
                venue = clean_text(await venue_el.inner_text()) if venue_el else ""

                time_el = await card.query_selector(".time, [class*='time'], [class*='date'], .schedule")
                start_raw = clean_text(await time_el.inner_text()) if time_el else ""

                price_el = await card.query_selector(".price, [class*='price'], .price-range")
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

        if items:
            self.log.info("maoyan dom parse success: %s items found", len(items))
        return items

    @staticmethod
    def _fallback_id(title: str, venue: str, start: str) -> str:
        raw = f"{title}|{venue}|{start}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
