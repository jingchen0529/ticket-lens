"""不启浏览器：只测各策略的 API 记录解析。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse

import pytest

from app.browser.captcha.base import CaptchaSolveResult
from app.core.config import AppConfig
from app.crawlers.damai import DamaiCrawler
from app.crawlers.damai.crawler import _SearchAjaxError
from app.crawlers.maoyan import MaoyanCrawler


class _DummySession:
    pass


def _api_response(
    body: str,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    url: str = "https://search.damai.cn/searchajax.html",
):
    return SimpleNamespace(
        ok=200 <= status < 300,
        status=status,
        headers=headers or {"content-type": "application/json"},
        url=url,
        text=AsyncMock(return_value=body),
        dispose=AsyncMock(),
    )


def _page_with_api(*responses):
    request_get = AsyncMock(side_effect=list(responses))
    return SimpleNamespace(
        url="https://search.damai.cn/search.htm",
        context=SimpleNamespace(request=SimpleNamespace(get=request_get)),
        evaluate=AsyncMock(
            side_effect=AssertionError("searchajax must not use the page execution context")
        ),
        wait_for_timeout=AsyncMock(),
    )


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


def test_damai_skips_merchandise_mixed_into_performance_results():
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]

    item = crawler._record_to_raw(
        {
            "projectid": "1065385649255",
            "nameNoHtml": "薛之谦-万兽之王巡回演唱会-官方荧光棒",
            "categoryid": 51,
            "categoryname": "其他",
            "venue": "演出场馆地址待定",
        },
        city="北京",
        from_api=True,
    )

    assert item is None


def test_damai_keeps_non_merchandise_other_category():
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]

    item = crawler._record_to_raw(
        {
            "projectid": "other-event",
            "nameNoHtml": "城市文化特别活动",
            "categoryid": 51,
            "categoryname": "其他",
        },
        city="北京",
        from_api=True,
    )

    assert item is not None


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


@pytest.mark.parametrize(
    ("category", "category_id"),
    [
        ("", 0),
        ("演唱会", 1),
        ("话剧音乐剧", 4),
        ("音乐节", 10),
        ("戏曲艺术", 3),
        ("沉浸剧场", 14),
        ("Livehouse", 17),
        ("其他", 8),
    ],
)
def test_maoyan_category_is_added_to_api_path(category, category_id):
    crawler = MaoyanCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]

    url = crawler._build_api_url(city_id=1, page_no=2, category=category)

    assert f"/performances/{category_id};st=0;p=2;" in url
    assert "cityId=1" in url


def test_maoyan_rejects_unknown_category():
    crawler = MaoyanCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="unknown maoyan category"):
        crawler._build_api_url(city_id=1, page_no=1, category="不存在")


def test_maoyan_reads_category_from_live_response_field():
    crawler = MaoyanCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]

    item = crawler._record_to_raw(
        {"performanceId": 1, "name": "某演出", "cornerDisplayName": "沉浸剧场"},
        city="北京",
        from_api=True,
    )

    assert item is not None
    assert item.category == "沉浸剧场"


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


def test_damai_category_is_added_to_search_urls():
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]

    search_query = parse_qs(
        urlparse(crawler._build_search_url("北京", "", 2, "话剧歌剧")).query,
        keep_blank_values=True,
    )
    ajax_query = parse_qs(
        urlparse(crawler._build_ajax_url("北京", "", 2, "话剧歌剧")).query,
        keep_blank_values=True,
    )

    assert search_query["ctl"] == ["话剧歌剧"]
    assert ajax_query["ctl"] == ["话剧歌剧"]
    assert search_query["currPage"] == ["2"]
    assert ajax_query["currPage"] == ["2"]


def test_damai_empty_category_keeps_all_categories():
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]

    query = parse_qs(
        urlparse(crawler._build_ajax_url("上海", "", 1)).query,
        keep_blank_values=True,
    )

    assert query["ctl"] == [""]


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
    ("response_or_error", "message"),
    [
        (RuntimeError("network down"), "context request failed.*network down"),
        (_api_response("bad gateway", status=502), "http status=502"),
    ],
)
async def test_damai_searchajax_failure_without_captcha_raises(response_or_error, message):
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    crawler.goto = AsyncMock(return_value=None)  # type: ignore[method-assign]
    crawler.captcha.detect = AsyncMock(return_value=None)  # type: ignore[method-assign]
    crawler.captcha.ensure_cleared = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("ordinary API failures must not enter captcha solving")
    )
    page = _page_with_api(response_or_error)

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
    page = _page_with_api(
        _api_response(json.dumps(first_page, ensure_ascii=False)),
        RuntimeError("request timed out after 12000ms"),
    )

    with pytest.raises(RuntimeError, match="searchajax failed.*page=2"):
        await crawler._crawl_city_keyword(page, "上海", "", 3)

    assert page.context.request.get.await_count == 2
    assert page.evaluate.await_count == 0


@pytest.mark.asyncio
async def test_damai_fetch_helper_raises_typed_error_for_non_json_payload():
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    response = _api_response("null", headers={"content-type": "text/plain"})
    page = _page_with_api(response)

    with pytest.raises(_SearchAjaxError, match="non-json response status=200"):
        await crawler._fetch_search_ajax(page, city="上海", keyword="", page_no=1)

    response.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_damai_searchajax_does_not_depend_on_page_execution_context():
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    crawler.goto = AsyncMock(return_value=None)  # type: ignore[method-assign]
    payload = {
        "pageData": {
            "totalPage": 1,
            "resultData": [{"projectid": "nav-1", "nameNoHtml": "导航后恢复"}],
        }
    }
    response = _api_response(json.dumps(payload, ensure_ascii=False))
    page = _page_with_api(response)

    items = await crawler._crawl_city_keyword(page, "北京", "", 1)

    assert [item.source_id for item in items] == ["nav-1"]
    assert page.evaluate.await_count == 0
    response.dispose.assert_awaited_once()
    request_kwargs = page.context.request.get.await_args.kwargs
    assert request_kwargs["max_redirects"] == 0
    assert request_kwargs["max_retries"] == 1
    assert request_kwargs["timeout"] == 12000
    assert request_kwargs["headers"]["x-requested-with"] == "XMLHttpRequest"
    assert "HeadlessChrome" not in request_kwargs["headers"]["user-agent"]


@pytest.mark.asyncio
async def test_damai_searchajax_challenge_redirect_uses_existing_solver_flow():
    crawler = DamaiCrawler(_DummySession(), AppConfig())  # type: ignore[arg-type]
    crawler.goto = AsyncMock(return_value=None)  # type: ignore[method-assign]
    challenge = _api_response(
        "",
        status=302,
        headers={"location": "https://risk.damai.cn/punish?x=1"},
    )
    success_payload = {
        "pageData": {
            "totalPage": 1,
            "resultData": [{"projectid": "after-captcha", "name": "验证后恢复"}],
        }
    }
    success = _api_response(json.dumps(success_payload, ensure_ascii=False))
    page = _page_with_api(challenge, success)

    items = await crawler._crawl_city_keyword(page, "北京", "", 1)

    assert [item.source_id for item in items] == ["after-captcha"]
    assert crawler.goto.await_count == 2
    assert crawler.goto.await_args_list[1].args[1].startswith(
        "https://risk.damai.cn/punish"
    )
    assert page.evaluate.await_count == 0
    challenge.dispose.assert_awaited_once()
    success.dispose.assert_awaited_once()


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

    items = await crawler.crawl(
        cities=["上海", "北京"], keywords=[], max_pages=1, category="音乐会"
    )

    assert [item.source_id for item in items] == ["same"]
    assert [call.args[4] for call in crawler._crawl_city_keyword.await_args_list] == [
        "音乐会",
        "音乐会",
    ]
