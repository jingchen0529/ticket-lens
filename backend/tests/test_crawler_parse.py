"""不启浏览器：只测各策略的 API 记录解析。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager

import pytest

from app.browser.captcha.base import CaptchaSolveResult
from app.core.config import AppConfig
from app.crawlers.damai import DamaiCrawler
from app.crawlers.damai.crawler import _SearchAjaxError
from app.crawlers.maoyan import MaoyanCrawler


class _DummySession:
    pass


def test_damai_record_to_raw():
    c = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    rec = {
        "projectid": "999",
        "nameNoHtml": "某音乐节",
        "venue": "上海 | 世博公园",
        "priceStr": "199-999",
        "showtime": "2026.09.01",
        "cityname": "上海",
        "categoryName": "音乐节",
        "verticalPic": "https://example.com/a.jpg",
    }
    item = c._record_to_raw(rec, city="上海", from_api=True)
    assert item is not None
    assert item.source_id == "999"
    assert item.title == "某音乐节"
    assert item.city == "上海"
    assert "detail.damai.cn" in item.url


def test_maoyan_record_to_raw():
    c = MaoyanCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    rec = {
        "performanceId": 888,
        "performanceName": "话剧·雷雨",
        "shopName": "天桥艺术中心",
        "cityName": "北京",
        "minPrice": 180,
        "maxPrice": 680,
        "showTime": "2026-10-01 19:30",
        "saleStatus": "在售",
    }
    item = c._record_to_raw(rec, city="北京", from_api=True)
    assert item is not None
    assert item.source_id == "888"
    assert item.title == "话剧·雷雨"
    assert "180" in item.price_raw


def test_damai_extract_records_nested():
    c = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    data = {
        "pageData": {
            "resultData": {
                "projectInfo": [
                    {"projectid": "1", "name": "A"},
                    {"projectid": "2", "name": "B"},
                ]
            }
        }
    }
    recs = c._extract_records(data)
    assert len(recs) == 2


def test_each_platform_has_own_captcha_solver():
    c1 = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    c2 = MaoyanCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    assert c1.captcha.platform == "damai"
    assert c2.captcha.platform == "maoyan"
    assert type(c1.captcha) is not type(c2.captcha)


@pytest.mark.asyncio
async def test_damai_block_without_punish_runs_one_solver_batch():
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    crawler.goto = AsyncMock(return_value=None)  # type: ignore[method-assign]
    crawler._fetch_search_ajax = AsyncMock(  # type: ignore[method-assign]
        return_value={"ret": ["FAIL_SYS_USER_VALIDATE"], "data": {}}
    )
    crawler.captcha.ensure_cleared = AsyncMock(
        return_value=CaptchaSolveResult(ok=False, method="fruit", message="rejected")
    )
    page = SimpleNamespace(
        url="https://search.damai.cn/search.htm",
        wait_for_timeout=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="captcha solver failed.*page=1"):
        await crawler._crawl_city_keyword(page, "上海", "", 1)

    assert crawler.goto.await_count == 1
    # 无 punish 时走 _maybe_solve_captcha → ensure_cleared
    assert crawler.captcha.ensure_cleared.await_count == 1


@pytest.mark.asyncio
async def test_damai_maybe_solve_passes_early_payload_hint():
    """风控求解必须把预挂监听截到的双图传给 ensure_cleared。"""
    from app.crawlers.damai.fruit_slider import CaptchaPayload

    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    hint = CaptchaPayload(
        encrypt_token="tok",
        image_data=b"\xff\xd8\xff" + b"\x00" * 200,
        ques=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
    )
    crawler._early_payloads = [hint]
    crawler.captcha.ensure_cleared = AsyncMock(
        return_value=CaptchaSolveResult(ok=True, method="fruit_slider:provider", message="ok")
    )
    page = SimpleNamespace(wait_for_timeout=AsyncMock())

    ok = await crawler._maybe_solve_captcha(page)  # type: ignore[arg-type]
    assert ok is True
    crawler.captcha.ensure_cleared.assert_awaited_once()
    kwargs = crawler.captcha.ensure_cleared.await_args.kwargs
    assert kwargs.get("payload_hint") is hint


@pytest.mark.asyncio
async def test_damai_punish_navigation_does_not_solve_twice():
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    crawler.goto = AsyncMock(return_value=None)  # type: ignore[method-assign]
    crawler._fetch_search_ajax = AsyncMock(  # type: ignore[method-assign]
        return_value={"ret": ["FAIL_SYS_USER_VALIDATE"], "data": {"url": "https://x/punish"}}
    )
    crawler._maybe_solve_captcha = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("goto already owns captcha solving")
    )
    page = SimpleNamespace(
        url="https://search.damai.cn/search.htm",
        wait_for_timeout=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="captcha retries exhausted.*page=1"):
        await crawler._crawl_city_keyword(page, "上海", "", 1)

    assert crawler.goto.await_count == 2
    assert crawler._maybe_solve_captcha.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"_fetch_error": True, "aborted": False, "error": "network down"}, "fetch error"),
        ({"_parse_error": True, "status": 502, "text": "bad gateway"}, "non-json"),
    ],
)
async def test_damai_searchajax_failure_without_captcha_raises(raw, message):
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    crawler.goto = AsyncMock(return_value=None)  # type: ignore[method-assign]
    crawler.captcha.detect = AsyncMock(return_value=None)  # type: ignore[method-assign]
    crawler.captcha.ensure_cleared = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("ordinary API failures must not enter captcha solving")
    )
    page = SimpleNamespace(
        url="https://search.damai.cn/search.htm",
        evaluate=AsyncMock(return_value=raw),
        wait_for_timeout=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match=rf"searchajax failed.*page=1.*{message}"):
        await crawler._crawl_city_keyword(page, "上海", "", 1)

    assert crawler.captcha.detect.await_count == 1
    assert crawler.captcha.ensure_cleared.await_count == 0


@pytest.mark.asyncio
async def test_damai_later_searchajax_failure_does_not_return_partial_results():
    cfg = AppConfig()
    cfg.crawl.request_delay_seconds = 0
    crawler = DamaiCrawler(_DummySession(), cfg)  # type: ignore[arg-type]
    crawler.goto = AsyncMock(return_value=None)  # type: ignore[method-assign]
    crawler.captcha.detect = AsyncMock(return_value=None)  # type: ignore[method-assign]
    first_page = {
        "pageData": {
            "totalPage": 3,
            "resultData": [
                {
                    "projectid": "999",
                    "nameNoHtml": "第一页项目",
                    "cityname": "上海",
                }
            ],
        }
    }
    page = SimpleNamespace(
        url="https://search.damai.cn/search.htm",
        evaluate=AsyncMock(
            side_effect=[
                first_page,
                {"_fetch_error": True, "aborted": True, "error": "timeout"},
            ]
        ),
        wait_for_timeout=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="searchajax failed.*page=2"):
        await crawler._crawl_city_keyword(page, "上海", "", 3)

    assert page.evaluate.await_count == 2


@pytest.mark.asyncio
async def test_damai_fetch_helper_raises_typed_error_for_unexpected_payload():
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    page = SimpleNamespace(evaluate=AsyncMock(return_value=None))

    with pytest.raises(_SearchAjaxError, match="unexpected response type=NoneType"):
        await crawler._fetch_search_ajax(page, city="上海", keyword="", page_no=1)


@pytest.mark.asyncio
async def test_damai_deduplicates_projects_before_detail_fetch(monkeypatch):
    import app.crawlers.damai.crawler as crawler_module

    @asynccontextmanager
    async def page_context():
        yield object()

    session = SimpleNamespace(page=page_context)
    cfg = AppConfig()
    cfg.crawl.request_delay_seconds = 0
    crawler = DamaiCrawler(session, cfg)  # type: ignore[arg-type]
    first = crawler._record_to_raw(
        {"projectid": "same", "name": "重复项目"}, city="上海", from_api=True
    )
    duplicate = crawler._record_to_raw(
        {"projectid": "same", "name": "重复项目"}, city="北京", from_api=True
    )
    assert first is not None and duplicate is not None
    crawler._crawl_city_keyword = AsyncMock(  # type: ignore[method-assign]
        side_effect=[[first], [duplicate]]
    )

    async def fake_enrich(_page, items, **_kwargs):
        assert [item.source_id for item in items] == ["same"]
        return items

    monkeypatch.setattr(crawler_module, "enrich_items_detail", fake_enrich)

    items = await crawler.crawl(cities=["上海", "北京"], keywords=[], max_pages=1)

    assert [item.source_id for item in items] == ["same"]
