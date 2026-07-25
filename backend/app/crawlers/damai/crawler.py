"""大麦 crawler 策略。

策略特点：
- 列表数据走 search.damai.cn/searchajax.html（pageData.resultData）
- 先打开一次 search.htm 建会话/cookie，再同页 fetch 翻页（避免每页整页刷新）
- 命中 FAIL_SYS_USER_VALIDATE / 水果滑块时调用 captcha solver，同页重试
- 首屏接口成功但无记录时回退 DOM 卡片解析
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Sequence
from urllib.parse import quote, urlencode

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from app.browser.captcha.base import CaptchaSolver
from app.crawlers.base import BaseCrawler
from app.crawlers.damai.captcha import DamaiCaptchaSolver
from app.crawlers.damai.detail import enrich_items_detail
from app.crawlers.damai.fruit_slider import CaptchaPayload, attach_payload_listener
from app.models import RawShowItem, SourcePlatform
from app.utils.text import clean_text

logger = logging.getLogger(__name__)

SEARCH_AJAX_URL = "https://search.damai.cn/searchajax.html"

# 大麦搜索相关接口 URL 片段
_DAMAI_API_HINTS = (
    "searchajax",
    "search.htm",
    "search.damai.cn",
    "mtop.alibaba.damai",
    "project/list",
)


class _SearchAjaxError(RuntimeError):
    """searchajax transport or response-format failure."""


class DamaiCrawler(BaseCrawler):
    source = SourcePlatform.DAMAI

    def build_captcha_solver(self) -> CaptchaSolver:
        return DamaiCaptchaSolver(self.config)

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
                        "damai crawl city=%s keyword=%r pages=%s", city, keyword, pages_label
                    )
                    page_items = await self._crawl_city_keyword(page, city, keyword, max_pages)
                    items.extend(page_items)
                    await self._delay()

            # 列表完成后：用同一浏览器上下文拉 subpage，补全场次/票档/场馆
            if items and self._should_enrich_detail():
                self.log.info("damai detail enrich start count=%s", len(items))
                delay = float(getattr(self.config.crawl, "detail_delay_seconds", 0.35) or 0.35)
                date_limit = int(getattr(self.config.crawl, "detail_date_limit", 40) or 40)
                items = await enrich_items_detail(
                    page,
                    items,
                    delay_s=delay,
                    fetch_all_dates=True,
                    date_limit=date_limit,
                )
                self.log.info(
                    "damai detail enrich done with_sessions=%s",
                    sum(1 for i in items if i.sessions_raw),
                )

        self.log.info("damai done raw=%s", len(items))
        return items

    def _should_enrich_detail(self) -> bool:
        crawl = getattr(self.config, "crawl", None)
        if crawl is None:
            return True
        return bool(getattr(crawl, "enrich_detail", True))

    async def goto(self, page: Page, url: str, *, wait_until: str = "domcontentloaded") -> None:
        """导航并过验证；优先使用外层已截获的 newslidecaptcha 双图。

        出题响应只会出现一次。必须在 page.goto 之前挂好 listener（见
        `_crawl_city_keyword` 的 early payload 池），这里把最新 payload 传给 solver。
        """
        self.log.debug("goto %s", url)
        await page.goto(url, wait_until=wait_until)
        hint = self._latest_early_payload()
        if hint is not None:
            self.log.info(
                "damai early captcha payload ready image=%sB ques=%sB token=%s",
                len(hint.image_data or b""),
                len(hint.ques or b""),
                bool(hint.encrypt_token),
            )
        result = await self.captcha.ensure_cleared(page, payload_hint=hint)
        if not result.ok:
            raise RuntimeError(
                f"[{self.captcha.platform}] captcha not cleared via {result.method}: "
                f"{result.message}"
            )
        # 通过后持久化 cookie，减少下次验证
        if (
            result.method not in ("skipped",)
            and getattr(self.session, "captcha_config", None) is not None
            and getattr(self.session.captcha_config, "persist_cookies", False)
            and hasattr(self.session, "save_platform_cookies")
        ):
            await self.session.save_platform_cookies(self.source.value)

    def _latest_early_payload(self) -> CaptchaPayload | None:
        early = getattr(self, "_early_payloads", None) or []
        return early[-1] if early else None

    async def _attach_early_payload_listener(self, page: Page) -> Any:
        """在导航前挂 newslidecaptcha 监听；测试用假 page 无 on 时跳过。"""
        self._early_payloads: list[CaptchaPayload] = []

        def _noop() -> None:
            return None

        if not hasattr(page, "on"):
            return _noop
        try:
            detach = await attach_payload_listener(page, self._early_payloads)
            self.log.info("damai early newslidecaptcha listener attached")
            return detach
        except Exception as exc:  # noqa: BLE001
            self.log.warning("damai early payload listener unavailable: %s", exc)
            return _noop

    async def _crawl_city_keyword(
        self,
        page: Page,
        city: str,
        keyword: str,
        max_pages: int,
    ) -> list[RawShowItem]:
        """search.htm 建会话 → searchajax 翻页 → 风控时过验证后从当前页重试。"""
        collected: list[RawShowItem] = []

        # 整城关键词周期内保持 listener，避免出题响应在 solver 挂载前就结束
        detach_early = await self._attach_early_payload_listener(page)
        try:
            return await self._crawl_city_keyword_body(
                page, city, keyword, max_pages, collected
            )
        finally:
            try:
                detach_early()
            except Exception:  # noqa: BLE001
                pass
            self._early_payloads = []

    async def _crawl_city_keyword_body(
        self,
        page: Page,
        city: str,
        keyword: str,
        max_pages: int,
        collected: list[RawShowItem],
    ) -> list[RawShowItem]:
        # 1) 打开搜索页一次，建立 XSRF / 站点 cookie（会顺带打一发 currPage=1）
        entry = self._build_search_url(city, keyword, 1)
        try:
            await self.goto(page, entry, wait_until="domcontentloaded")
        except RuntimeError as exc:
            raise RuntimeError(
                f"damai search.htm captcha failed city={city} keyword={keyword!r}: {exc}"
            ) from exc
        except PlaywrightError as exc:
            self.log.warning("search.htm goto failed: %s", exc)
            try:
                await self.goto(page, entry, wait_until="load")
            except Exception as retry_exc:  # noqa: BLE001
                raise RuntimeError(
                    f"damai search.htm navigation failed city={city} keyword={keyword!r}: "
                    f"{retry_exc}"
                ) from retry_exc
        await page.wait_for_timeout(1200)

        captcha_retries = 0
        max_captcha_retries = 1
        page_no = 1
        # max_pages<=0：不设硬上限，以大麦 totalPage / 空页为准
        page_cap = max_pages if max_pages and max_pages > 0 else None
        while page_cap is None or page_no <= page_cap:
            fetch_error: _SearchAjaxError | None = None
            try:
                payload = await self._fetch_search_ajax(
                    page,
                    city=city,
                    keyword=keyword,
                    page_no=page_no,
                )
            except _SearchAjaxError as exc:
                fetch_error = exc
                payload = None

            # A timeout/non-JSON response can be either a challenge or an ordinary outage.
            # Only consume captcha budget when the page currently contains a challenge.
            if fetch_error is not None:
                try:
                    challenge = await self.captcha.detect(page)
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"damai could not classify searchajax failure city={city} "
                        f"keyword={keyword!r} page={page_no}: {fetch_error}"
                    ) from exc
                if challenge is None:
                    raise RuntimeError(
                        f"damai searchajax failed city={city} keyword={keyword!r} "
                        f"page={page_no}: {fetch_error}"
                    ) from fetch_error

            if self._is_user_validate(payload) or fetch_error is not None:
                punish = self._punish_url(payload) if isinstance(payload, dict) else None
                self.log.warning(
                    "damai captcha block city=%s kw=%r page=%s fetch_error=%s punish=%s",
                    city,
                    keyword,
                    page_no,
                    fetch_error is not None,
                    (punish or "")[:120],
                )
                if captcha_retries >= max_captcha_retries:
                    raise RuntimeError(
                        f"damai captcha retries exhausted city={city} keyword={keyword!r} "
                        f"page={page_no}"
                    )
                captcha_retries += 1
                if punish:
                    try:
                        await self.goto(page, punish, wait_until="domcontentloaded")
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(
                            f"damai captcha navigation/solve failed city={city} "
                            f"keyword={keyword!r} page={page_no}: {exc}"
                        ) from exc
                else:
                    try:
                        cleared = await self._maybe_solve_captcha(page)
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(
                            f"damai captcha solver errored city={city} keyword={keyword!r} "
                            f"page={page_no}: {exc}"
                        ) from exc
                    if not cleared:
                        raise RuntimeError(
                            f"damai captcha solver failed city={city} keyword={keyword!r} "
                            f"page={page_no}"
                        )
                # 过验证后不要先浪费额度回第 1 页；直接重试当前 page_no
                # 若当前仍在 punish 页，回到 search 域（仍请求目标页）
                if "punish" in (page.url or "") or "_____tmd_____" in (page.url or ""):
                    try:
                        await page.goto(entry, wait_until="domcontentloaded")
                        await page.wait_for_timeout(800)
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(
                            f"damai failed to return to search page city={city} "
                            f"keyword={keyword!r} page={page_no}: {exc}"
                        ) from exc
                continue

            batch = self._parse_api_payload({"url": SEARCH_AJAX_URL, "data": payload}, city=city)
            if not batch and page_no == 1:
                # 首屏接口空时尝试 DOM
                batch = await self._parse_dom(page, city=city)

            if not batch:
                self.log.info("damai empty page city=%s kw=%r page=%s", city, keyword, page_no)
                break

            collected.extend(batch)
            total_page = None
            if isinstance(payload, dict):
                pd = payload.get("pageData") or {}
                if isinstance(pd, dict):
                    total_page = pd.get("totalPage") or pd.get("maxPage")
            self.log.info(
                "damai city=%s kw=%r page=%s got=%s totalPage=%s",
                city,
                keyword,
                page_no,
                len(batch),
                total_page,
            )
            captcha_retries = 0
            if total_page is not None and page_no >= int(total_page):
                break
            page_no += 1
            await self._delay()

        return collected

    async def _fetch_search_ajax(
        self,
        page: Page,
        *,
        city: str,
        keyword: str,
        page_no: int,
        timeout_ms: int = 12000,
    ) -> dict[str, Any] | list[Any]:
        """在已打开的 search 域页面内 fetch searchajax（带 cookie）。

        必须带 AbortController：风控/punish 时接口常挂起不返回，无超时会把整条
        采集链路卡死（永远进不到 captcha solver）。
        """
        url = self._build_ajax_url(city, keyword, page_no)
        # 外层 wait_for 比 JS abort 略宽一点，避免竞态
        outer_timeout = max(5.0, (timeout_ms / 1000.0) + 3.0)
        try:
            raw = await asyncio.wait_for(
                page.evaluate(
                    """async ({ ajaxUrl, timeoutMs }) => {
                      const ctrl = new AbortController();
                      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
                      try {
                        const r = await fetch(ajaxUrl, {
                          credentials: 'include',
                          signal: ctrl.signal,
                          headers: {
                            accept: 'application/json, text/plain, */*',
                            'x-requested-with': 'XMLHttpRequest',
                          },
                        });
                        const text = await r.text();
                        try { return JSON.parse(text); } catch (e) {
                          return { _parse_error: true, status: r.status, text: text.slice(0, 500) };
                        }
                      } catch (e) {
                        const name = (e && e.name) || '';
                        const msg = (e && e.message) || String(e);
                        return {
                          _fetch_error: true,
                          aborted: name === 'AbortError' || /abort/i.test(msg),
                          error: msg.slice(0, 200),
                        };
                      } finally {
                        clearTimeout(timer);
                      }
                    }""",
                    {"ajaxUrl": url, "timeoutMs": int(timeout_ms)},
                ),
                timeout=outer_timeout,
            )
        except asyncio.TimeoutError:
            raise _SearchAjaxError(f"outer timeout after {outer_timeout:.1f}s")
        except Exception as exc:  # noqa: BLE001
            raise _SearchAjaxError(f"page evaluate failed: {exc}") from exc
        if isinstance(raw, dict) and raw.get("_fetch_error"):
            raise _SearchAjaxError(
                f"fetch error aborted={bool(raw.get('aborted'))}: "
                f"{str(raw.get('error') or 'unknown error')[:200]}"
            )
        if isinstance(raw, dict) and raw.get("_parse_error"):
            raise _SearchAjaxError(f"non-json response status={raw.get('status')}")
        if isinstance(raw, (dict, list)):
            return raw  # type: ignore[return-value]
        raise _SearchAjaxError(f"unexpected response type={type(raw).__name__}")

    async def _maybe_solve_captcha(self, page: Page) -> bool:
        hint = self._latest_early_payload()
        if hint is not None:
            self.log.info(
                "damai solve with early payload image=%sB ques=%sB",
                len(hint.image_data or b""),
                len(hint.ques or b""),
            )
        result = await self.captcha.ensure_cleared(page, payload_hint=hint)
        if result and result.ok and result.method != "skipped":
            self.log.info("damai captcha solved: %s", result.method)
        await page.wait_for_timeout(500)
        # A blocked API response cannot be cleared merely because no UI was detected.
        return bool(result and result.ok and result.method != "skipped")

    @staticmethod
    def _is_user_validate(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        ret = payload.get("ret")
        if isinstance(ret, list) and any("USER_VALIDATE" in str(x) or "RGV587" in str(x) for x in ret):
            return True
        data = payload.get("data")
        if isinstance(data, dict):
            url = str(data.get("url") or "")
            if "punish" in url or "captcha" in url or "capslide" in url:
                return True
        return False

    @staticmethod
    def _punish_url(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if isinstance(data, dict):
            url = data.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
        return None

    def _build_search_url(self, city: str, keyword: str, page_no: int) -> str:
        base = self.config.sources.damai.search_url or "https://search.damai.cn/search.htm"
        params: dict[str, str] = {
            "order": "1",
            "cty": city or "",
            "currPage": str(page_no),
        }
        if keyword:
            params["keyword"] = keyword
        else:
            # 与线上 MCP 验证一致：空关键词 + order=1 可拉全部分类
            params["keyword"] = ""
        return f"{base}?{urlencode(params, quote_via=quote)}"

    def _build_ajax_url(self, city: str, keyword: str, page_no: int) -> str:
        params = {
            "keyword": keyword or "",
            "cty": city or "",
            "ctl": "",
            "sctl": "",
            "tsg": "0",
            "st": "",
            "et": "",
            "order": "1",
            "pageSize": "30",
            "currPage": str(page_no),
            "tn": "",
        }
        return f"{SEARCH_AJAX_URL}?{urlencode(params, quote_via=quote)}"

    @staticmethod
    def _try_parse_json(body: str) -> dict[str, Any] | list[Any] | None:
        body = body.strip()
        if not body:
            return None
        # 有时是 JSONP
        if body.startswith("callback") or body.startswith("jsonp"):
            m = re.search(r"\((\{.*\}|\[.*\])\)\s*;?\s*$", body, re.S)
            if m:
                body = m.group(1)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    def _parse_api_payload(self, payload: dict[str, Any], *, city: str) -> list[RawShowItem]:
        data = payload.get("data")
        records = self._extract_records(data)
        items: list[RawShowItem] = []
        for rec in records:
            item = self._record_to_raw(rec, city=city, from_api=True)
            if item:
                items.append(item)
        return items

    def _extract_records(self, data: Any) -> list[dict[str, Any]]:
        """从各种大麦响应结构里抠出项目列表。"""
        if data is None:
            return []
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]

        if not isinstance(data, dict):
            return []

        # 线上实测：searchajax → pageData.resultData: list[project]
        page_data = data.get("pageData") if isinstance(data.get("pageData"), dict) else {}
        result_data = page_data.get("resultData") if isinstance(page_data, dict) else None
        if isinstance(result_data, list) and result_data and isinstance(result_data[0], dict):
            return result_data  # type: ignore[return-value]
        if isinstance(result_data, dict):
            for key in ("projectInfo", "result", "list", "data"):
                inner = result_data.get(key)
                if isinstance(inner, list) and inner and isinstance(inner[0], dict):
                    return inner  # type: ignore[return-value]

        # 其它常见路径
        candidates = [
            data.get("pageData", {}).get("resultData", {}).get("projectInfo")
            if isinstance(data.get("pageData", {}).get("resultData"), dict)
            else None,
            data.get("data", {}).get("projectInfo") if isinstance(data.get("data"), dict) else None,
            data.get("projectInfo"),
            data.get("result"),
            data.get("data") if isinstance(data.get("data"), list) else None,
        ]
        for c in candidates:
            if isinstance(c, list) and c and isinstance(c[0], dict):
                return c  # type: ignore[return-value]

        # 深度搜索：找含 name/projectName + id 的 dict 列表
        found: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, list) and node and isinstance(node[0], dict):
                sample = node[0]
                keys = set(sample.keys())
                if keys & {"projectid", "projectId", "id", "itemId"} and keys & {
                    "name",
                    "projectName",
                    "title",
                    "nameNoHtml",
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
            rec.get("projectid")
            or rec.get("projectId")
            or rec.get("id")
            or rec.get("itemId")
            or ""
        )
        title = clean_text(
            str(
                rec.get("nameNoHtml")
                or rec.get("name")
                or rec.get("projectName")
                or rec.get("title")
                or ""
            )
        )
        if not title and not source_id:
            return None

        venue = clean_text(str(rec.get("venue") or rec.get("venueName") or rec.get("venue_name") or ""))
        price_raw = clean_text(
            str(rec.get("priceStr") or rec.get("price_str") or rec.get("price") or rec.get("priceLow") or "")
        )
        if price_raw and not price_raw.endswith("元") and re.search(r"\d", price_raw):
            price_raw = f"{price_raw}元"

        status_raw = clean_text(
            str(rec.get("showStatus") or rec.get("showstatus") or rec.get("status") or "")
        )
        start_raw = clean_text(
            str(
                rec.get("showtime")
                or rec.get("showTime")
                or rec.get("actdate")
                or rec.get("showStartTime")
                or ""
            )
        )
        category = clean_text(str(rec.get("categoryName") or rec.get("categoryname") or rec.get("category") or ""))
        poster = str(rec.get("verticalPic") or rec.get("poster") or rec.get("imgUrl") or rec.get("pic") or "")
        url = str(rec.get("projectLink") or rec.get("url") or "")
        if source_id and not url:
            url = f"https://detail.damai.cn/item.htm?id={source_id}"

        city_name = clean_text(str(rec.get("cityname") or rec.get("cityName") or rec.get("city") or city))

        # 列表 actors 常为「艺人：A、B」或「艺人：某某乐团」
        artists: list[str] = []
        actors_raw = clean_text(str(rec.get("actors") or rec.get("artistName") or ""))
        if actors_raw:
            actors_raw = re.sub(r"^艺人[：:]\s*", "", actors_raw)
            for part in re.split(r"[、,/|]", actors_raw):
                part = clean_text(part)
                if part and part not in artists:
                    artists.append(part)

        return RawShowItem(
            source=SourcePlatform.DAMAI,
            source_id=source_id or self._fallback_id(title, venue, start_raw),
            url=url,
            title=title,
            city=city_name,
            venue_name=venue,
            category=category,
            artists=artists,
            poster_url=poster,
            price_raw=price_raw,
            status_raw=status_raw,
            start_time_raw=start_raw,
            raw_payload={"from_api": from_api, "record": rec},
            crawled_at=datetime.utcnow(),
        )

    async def _parse_dom(self, page: Page, *, city: str) -> list[RawShowItem]:
        """DOM 回退解析：兼容 search 列表卡片。"""
        items: list[RawShowItem] = []

        # 多种选择器兜底
        selectors = [
            ".items .item",
            ".search__itemlist .item__box",
            "[class*='item'] a[href*='detail.damai.cn']",
            "a[href*='item.htm']",
        ]
        cards = []
        for sel in selectors:
            cards = await page.query_selector_all(sel)
            if cards:
                self.log.debug("damai dom selector hit: %s count=%s", sel, len(cards))
                break

        for card in cards:
            try:
                href = await card.get_attribute("href") or ""
                if not href:
                    link = await card.query_selector("a[href*='item.htm'], a[href*='detail.damai']")
                    href = (await link.get_attribute("href")) if link else ""

                source_id = ""
                m = re.search(r"[?&]id=(\d+)", href or "")
                if m:
                    source_id = m.group(1)

                title_el = await card.query_selector(
                    ".items__txt__title, .item__box__name, h3, .title, [class*='title']"
                )
                title = clean_text(await title_el.inner_text()) if title_el else clean_text(await card.inner_text())
                # 卡片全文过长时截第一行
                if title and "\n" in title:
                    title = title.split("\n", 1)[0].strip()

                venue_el = await card.query_selector(
                    ".items__txt__venue, .item__box__venue, [class*='venue']"
                )
                venue = clean_text(await venue_el.inner_text()) if venue_el else ""

                time_el = await card.query_selector(
                    ".items__txt__time, .item__box__time, [class*='time']"
                )
                start_raw = clean_text(await time_el.inner_text()) if time_el else ""

                price_el = await card.query_selector(
                    ".items__txt__price, .item__box__price, [class*='price']"
                )
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
                    href = "https://detail.damai.cn" + href

                items.append(
                    RawShowItem(
                        source=SourcePlatform.DAMAI,
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
                self.log.debug("damai card parse error: %s", exc)

        return items

    @staticmethod
    def _fallback_id(title: str, venue: str, start: str) -> str:
        import hashlib

        raw = f"{title}|{venue}|{start}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
