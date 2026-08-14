"""大麦详情 subpage 解析与写回 RawShowItem。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.crawlers.damai.detail import (
    BixiPunishError,
    DetailCompletenessError,
    PcDetailCircuitOpenError,
    PcDetailNoPriceError,
    PcDetailRetryableError,
    PcDetailSemanticError,
    _SubpageCircuitBreaker,
    _fetch_subpage_with_retry,
    apply_detail_to_raw,
    enrich_item_detail,
    enrich_item_mobile_detail,
    extract_detail_from_subpage,
    extract_detail_from_mobile,
    fetch_item_static,
    fetch_subpage,
    is_bixi_punish,
    merge_sessions,
    parse_item_static_html,
    parse_jsonp,
)
from app.models import RawShowItem, SourcePlatform
from app.pipeline.normalize import normalize_one

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "damai_subpage_jp0.json"


def _load_fixture() -> dict:
    text = _FIXTURE.read_text(encoding="utf-8")
    data = parse_jsonp(text)
    assert data is not None
    return data


def _pc_app_only_subpage_payload() -> dict:
    return {
        "responseInfo": {"responseSuccess": "true", "responseCode": ""},
        "actionControl": {
            "calculatePriceControl": {
                "calcFailSafe": "true",
                "calculateTag": "0_0_0_1",
                "needCalc": "true",
            },
            "renderingControl": {"renderingType": "1"},
            "srcVerify": "0",
            "tradeControl": {"rtc": "true"},
        },
        "itemAdditionalInfo": {"performZoneNotice": ""},
        "skuRelatedText": {"registerToastMap": {}},
        "tradeInfo": {
            "anewUltron": "true",
            "hnewUltron": "true",
            "inewUltron": "true",
            "itemTags4Trade": [],
        },
        "holidayCalendar": [],
    }


def _pc_app_only_item_html(
    item_id: str,
    *,
    buy_status: int = 100,
    buy_origin: int = 109,
    buy_text: str = "该渠道不支持购票",
    buy_tip: str = "请到大麦App购买",
    description: str = "",
) -> str:
    static = {
        "itemBase": {
            "itemId": int(item_id),
            "projectStatus": 1,
            "itemName": "App 专购项目",
        },
        "venue": {"venueName": "北京展览馆剧场"},
        "itemExtendInfo": {"itemExtend": description},
    }
    dynamic = {
        "buyBtnStatus": buy_status,
        "buyBtnOrigin": buy_origin,
        "buyBtnText": buy_text,
        "buyBtnTip": buy_tip,
        "showQRCode": True,
        "priceRange": "¥80 - ¥580",
        "performBases": [],
    }
    return (
        f'<div id="staticDataDefault">{json.dumps(static, ensure_ascii=False)}</div>'
        f'<div id="dataDefault">{json.dumps(dynamic, ensure_ascii=False)}</div>'
    )


def test_parse_jsonp_jp0():
    data = parse_jsonp('__jp0({"a":1,"b":"x"})')
    assert data == {"a": 1, "b": "x"}


def test_normal_damai_item_html_is_not_misclassified_as_login_page():
    import app.crawlers.damai.detail as detail_module

    sample = """
    <html><head><title>项目详情</title></head><body>
      <a href="https://passport.damai.cn/">登录</a>
      <script>window.loginHost = "https://login.taobao.com";</script>
      <div class="project-name">正常大麦项目</div>
    </body></html>
    """

    assert detail_module._is_login_or_challenge_html(sample) is False


def test_real_login_form_is_classified_as_login_page():
    import app.crawlers.damai.detail as detail_module

    html = """
    <html><head><title>淘宝登录</title></head><body>
      <form id="login-form"><input type="password" name="password"></form>
    </body></html>
    """

    assert detail_module._is_login_or_challenge_html(html) is True
    assert parse_jsonp('{"a":2}') == {"a": 2}
    assert parse_jsonp("") is None


_BIXI_HTML = """
<html><body>
<a id="a-link" href="https://bixi.alicdn.com/punish/default.html?action=deny"></a>
<script>
document.cookie = "x5secdata=; maxAge=-100";
window._config_ = {action: "deny"};
</script>
<!--rgv587_flag:sm-->
</body></html>
"""


def test_bixi_detector_requires_strong_signal():
    assert is_bixi_punish(_BIXI_HTML, "text/html") is True
    assert is_bixi_punish("<html>ordinary maintenance</html>", "text/html") is False
    assert is_bixi_punish('{"action":"deny"}', "application/json") is False


def test_extract_detail_from_subpage_fixture():
    if not _FIXTURE.exists():
        # CI 无样张时跳过
        return
    detail = extract_detail_from_subpage(_load_fixture())
    assert detail["venue_name"] == "地质礼堂剧场"
    assert "北京" in detail["city"]
    assert detail["venue_address"]
    assert detail["sessions"]
    s0 = detail["sessions"][0]
    assert "2026-08-14" in (s0.get("name") or s0.get("start_time") or "")
    tiers = s0.get("ticket_tiers") or []
    assert len(tiers) >= 3
    prices = [t["price"] for t in tiers if t.get("price") is not None]
    assert min(prices) == 80.0
    assert max(prices) == 1080.0
    assert detail["date_ids"]


def _mobile_detail_payload(item_id: str = "1073716080825") -> dict:
    return {
        "detailViewComponentMap": {
            "item": {
                "staticData": {
                    "itemBase": {
                        "itemId": item_id,
                        "itemName": "【北京】音乐剧《大江东去》",
                        "cityName": "北京市",
                        "serviceNotes": [
                            {
                                "tagDesc": (
                                    "发票开具方：北京大麦文化传媒发展有限公司\n"
                                    "本项目支持电子发票"
                                )
                            }
                        ],
                    },
                    "venue": {
                        "venueId": "59432",
                        "venueName": "天桥艺术中心-大剧场",
                        "venueCityName": "北京市",
                        "venueAddr": "北京市西城区天桥南大街9号楼",
                        "lat": 39.882293,
                        "lng": 116.397967,
                    },
                    "itemExtendInfo": {
                        "itemExtend": "<p>演出团体：东方演艺集团音乐剧团</p>"
                    },
                },
                "dynamicExtData": {
                    "artists": [
                        {"artistName": "张新成"},
                        {"artistName": "高天鹤"},
                    ]
                },
                "item": {
                    "priceRange": "¥100 - ¥980",
                    # 接口原始顺序不保证按日期排列。
                    "performBases": [
                        {
                            "performs": [
                                {
                                    "performId": "281400218",
                                    "performName": "2026-10-07 周三 14:30",
                                    "performStartDate": "2026-10-07",
                                    "performBeginTime": "14:30",
                                }
                            ]
                        },
                        {
                            "performs": [
                                {
                                    "performId": "281393778",
                                    "performName": "2026-10-05 周一 19:30",
                                    "performStartDate": "2026-10-05",
                                    "performBeginTime": "19:30",
                                },
                                {
                                    "performId": "281402085",
                                    "performName": "2026-10-06 周二 19:30",
                                    "performStartDate": "2026-10-06",
                                    "performBeginTime": "19:30",
                                },
                            ]
                        },
                    ],
                },
            }
        }
    }


def test_extract_detail_from_mobile_has_real_venue_and_sorted_sessions():
    detail = extract_detail_from_mobile(
        _mobile_detail_payload(), expected_item_id="1073716080825"
    )

    assert detail["detail_complete"] is True
    assert detail["venue_name"] == "天桥艺术中心-大剧场"
    assert detail["venue_address"] == "北京市西城区天桥南大街9号楼"
    assert detail["district"] == "西城区"
    assert [session["start_time"] for session in detail["sessions"]] == [
        "2026-10-05 19:30",
        "2026-10-06 19:30",
        "2026-10-07 14:30",
    ]
    assert detail["calendar_dates_fetched"] == 3
    assert detail["ticket_tier_source"] == "mobile_price_range"
    assert detail["performers"] == ["张新成", "高天鹤"]


@pytest.mark.asyncio
async def test_enrich_mobile_replaces_unavailable_pc_url(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    fetch_mobile = AsyncMock(return_value=_mobile_detail_payload())
    monkeypatch.setattr(
        detail_module,
        "_fetch_mobile_detail_with_retry",
        fetch_mobile,
    )
    item = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="1073716080825",
        title="【北京】音乐剧《大江东去》",
        url="https://detail.damai.cn/item.htm?id=1073716080825",
    )

    enriched = await enrich_item_mobile_detail(item)

    assert enriched.url == (
        "https://m.damai.cn/shows/item.html?itemId=1073716080825"
    )
    assert len(enriched.sessions_raw) == 3
    assert enriched.price_raw == "100-980"
    assert enriched.raw_payload["detail"]["detail_source"] == "damai_mobile_mtop"
    fetch_mobile.assert_awaited_once_with(
        "1073716080825", attempts=3, retry_delay_s=2.0
    )


@pytest.mark.asyncio
async def test_mobile_detail_retry_is_three_attempts_at_fixed_two_seconds(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    fetch = AsyncMock(
        side_effect=[RuntimeError("one"), RuntimeError("two"), _mobile_detail_payload()]
    )
    sleep = AsyncMock()
    monkeypatch.setattr(detail_module, "fetch_mobile_item_detail", fetch)
    monkeypatch.setattr(detail_module.asyncio, "sleep", sleep)

    result = await detail_module._fetch_mobile_detail_with_retry(
        "1073716080825", attempts=3, retry_delay_s=2
    )

    assert result == _mobile_detail_payload()
    assert fetch.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [2, 2]


def test_apply_detail_and_normalize():
    if not _FIXTURE.exists():
        return
    detail = extract_detail_from_subpage(_load_fixture())
    raw = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="1067977288504",
        title="占位标题",
        city="北京",
        url="https://detail.damai.cn/item.htm?id=1067977288504",
        venue_name="旧场馆",
        price_raw="80-1080元",
    )
    raw = apply_detail_to_raw(raw, detail)
    assert raw.venue_name == "地质礼堂剧场"
    assert raw.venue_address
    assert len(raw.sessions_raw) >= 1
    assert raw.sessions_raw[0].get("ticket_tiers")

    show = normalize_one(raw)
    assert show is not None
    assert show.venue.name == "地质礼堂剧场"
    assert show.venue.address
    assert show.sessions
    assert show.sessions[0].ticket_tiers
    assert show.extras.get("detail_enriched") is True
    # 全部票档：80|180|280|… 而非 80-1080 区间
    assert "|" in (show.price.raw or "")
    assert "80" in show.price.raw.split("|")[0] or show.price.raw.startswith("80")
    parts = show.price.raw.split("|")
    assert len(parts) >= 3
    assert float(parts[0]) <= float(parts[-1])
    # JSON 可序列化
    payload = show.model_dump(mode="json")
    assert payload["sessions"][0]["ticket_tiers"]
    assert payload["price"]["raw"] == show.price.raw


def test_merge_sessions_prefers_tiers():
    a = [{"id": "1", "name": "A", "ticket_tiers": []}]
    b = [{"id": "1", "name": "A", "ticket_tiers": [{"name": "80元", "price": 80}]}]
    m = merge_sessions(a, b)
    assert len(m) == 1
    assert m[0]["ticket_tiers"][0]["price"] == 80


@pytest.mark.asyncio
async def test_subpage_retry_uses_fixed_backoff_and_semantic_validation(
    monkeypatch,
):
    import app.crawlers.damai.detail as detail_module

    responses = [None, {"ready": False}, {"ready": True}]
    fetch = AsyncMock(side_effect=responses)
    sleep = AsyncMock()
    monkeypatch.setattr(detail_module, "fetch_subpage", fetch)
    monkeypatch.setattr(detail_module.asyncio, "sleep", sleep)

    data = await _fetch_subpage_with_retry(
        object(),  # type: ignore[arg-type]
        "123",
        attempts=3,
        retry_delay_s=2,
        max_retry_delay_s=10,
        validator=lambda payload: payload.get("ready") is True,
        request_label="test",
    )

    assert data == {"ready": True}
    assert fetch.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [2, 2]


@pytest.mark.asyncio
async def test_single_502_uses_short_retry_before_any_circuit_cooldown(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    error = PcDetailRetryableError(item_id="123", reason="http_502", status=502)
    fetch = AsyncMock(side_effect=[error, {"ready": True}])
    sleep = AsyncMock()
    monkeypatch.setattr(detail_module, "fetch_subpage", fetch)
    monkeypatch.setattr(detail_module.asyncio, "sleep", sleep)
    breaker = _SubpageCircuitBreaker(max_cooldowns=2)

    result = await _fetch_subpage_with_retry(
        object(),  # type: ignore[arg-type]
        "123",
        attempts=3,
        retry_delay_s=2,
        validator=lambda payload: payload.get("ready") is True,
        request_label="base",
        circuit_breaker=breaker,
    )

    assert result == {"ready": True}
    assert fetch.await_count == 2
    assert [call.args[0] for call in sleep.await_args_list] == [2]


@pytest.mark.asyncio
async def test_subpage_pacer_enforces_global_interval_with_jitter(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    class FakeLoop:
        now = 100.0

        def time(self):
            return self.now

    loop = FakeLoop()
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)
        loop.now += delay

    monkeypatch.setattr(detail_module.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(detail_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(detail_module.random, "uniform", lambda _start, end: end)
    pacer = detail_module._SubpageRequestPacer(1.5)

    await pacer.wait_turn()
    await pacer.wait_turn()

    assert sleeps == [pytest.approx(1.875)]


@pytest.mark.asyncio
async def test_detail_http_uses_context_request_and_disposes_responses():
    subpage_response = SimpleNamespace(
        ok=True,
        status=200,
        headers={"content-type": "text/javascript;charset=UTF-8"},
        text=AsyncMock(
            return_value='__jp0({"responseInfo":{"responseSuccess":"true"}})'
        ),
        dispose=AsyncMock(),
    )
    static_response = SimpleNamespace(
        ok=True,
        status=200,
        headers={"content-type": "text/html;charset=UTF-8"},
        text=AsyncMock(return_value="<html></html>"),
        dispose=AsyncMock(),
    )
    request_get = AsyncMock(side_effect=[subpage_response, static_response])
    page = SimpleNamespace(
        context=SimpleNamespace(request=SimpleNamespace(get=request_get)),
        evaluate=AsyncMock(return_value="Mozilla/5.0 Chrome/126.0.0.0"),
    )

    data = await fetch_subpage(page, "123")
    static = await fetch_item_static(page, "123")

    assert data == {"responseInfo": {"responseSuccess": "true"}}
    assert static == {}
    assert request_get.await_count == 2
    assert all(call.kwargs["max_redirects"] == 0 for call in request_get.await_args_list)
    assert all(
        call.args == ("() => navigator.userAgent",)
        for call in page.evaluate.await_args_list
    )
    subpage_response.dispose.assert_awaited_once()
    static_response.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_item_static_bixi_cools_down_and_replays_same_url(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    blocked = SimpleNamespace(
        ok=True,
        status=200,
        url="https://detail.damai.cn/item.htm?id=1007108168970",
        headers={"content-type": "text/html"},
        text=AsyncMock(return_value=_BIXI_HTML),
        dispose=AsyncMock(),
    )
    recovered = SimpleNamespace(
        ok=True,
        status=200,
        url="https://detail.damai.cn/item.htm?id=1007108168970",
        headers={"content-type": "text/html"},
        text=AsyncMock(return_value="<html><body>normal item page</body></html>"),
        dispose=AsyncMock(),
    )
    request_get = AsyncMock(side_effect=[blocked, recovered])
    page = SimpleNamespace(
        context=SimpleNamespace(request=SimpleNamespace(get=request_get)),
        evaluate=AsyncMock(return_value="Mozilla/5.0 Chrome/126.0.0.0"),
    )
    sleep = AsyncMock()
    monkeypatch.setattr(detail_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(detail_module.random, "uniform", lambda low, _high: low)
    breaker = _SubpageCircuitBreaker(max_cooldowns=2)

    result = await fetch_item_static(
        page,
        "1007108168970",
        circuit_breaker=breaker,
    )

    assert result == {}
    assert request_get.await_count == 2
    assert request_get.await_args_list[0] == request_get.await_args_list[1]
    assert [call.args[0] for call in sleep.await_args_list] == [105]
    blocked.dispose.assert_awaited_once()
    recovered.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_item_static_single_502_gets_short_pc_retry_before_circuit(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    unavailable = SimpleNamespace(
        ok=False,
        status=502,
        url="https://detail.damai.cn/item.htm?id=1007108168970",
        headers={"content-type": "text/html"},
        text=AsyncMock(return_value="bad gateway"),
        dispose=AsyncMock(),
    )
    recovered = SimpleNamespace(
        ok=True,
        status=200,
        url="https://detail.damai.cn/item.htm?id=1007108168970",
        headers={"content-type": "text/html"},
        text=AsyncMock(return_value="<html><title>正常项目</title></html>"),
        dispose=AsyncMock(),
    )
    request_get = AsyncMock(side_effect=[unavailable, recovered])
    page = SimpleNamespace(
        context=SimpleNamespace(request=SimpleNamespace(get=request_get)),
        evaluate=AsyncMock(return_value="Mozilla/5.0 Chrome/126.0.0.0"),
    )
    sleep = AsyncMock()
    monkeypatch.setattr(detail_module.asyncio, "sleep", sleep)
    breaker = _SubpageCircuitBreaker(max_cooldowns=2)

    result = await fetch_item_static(
        page,
        "1007108168970",
        circuit_breaker=breaker,
        retry_delay_s=2,
    )

    assert result == {}
    assert request_get.await_count == 2
    assert [call.args[0] for call in sleep.await_args_list] == [2]


@pytest.mark.asyncio
async def test_item_static_http_200_404_shell_is_semantic_failure_not_no_price():
    response = SimpleNamespace(
        ok=True,
        status=200,
        url="https://detail.damai.cn/item.htm?id=1007108168970",
        headers={"content-type": "text/html"},
        text=AsyncMock(
            return_value="<html><head><title>缅怀黄家驹-大麦网404</title></head></html>"
        ),
        dispose=AsyncMock(),
    )
    page = SimpleNamespace(
        context=SimpleNamespace(
            request=SimpleNamespace(get=AsyncMock(return_value=response))
        ),
        evaluate=AsyncMock(return_value="Mozilla/5.0 Chrome/126.0.0.0"),
    )

    with pytest.raises(PcDetailSemanticError, match="http_200_404_shell"):
        await fetch_item_static(page, "1007108168970")

    response.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_item_static_invalid_probe_uses_long_cooldown_not_silent_success(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    blocked = SimpleNamespace(
        ok=True,
        status=200,
        url="https://detail.damai.cn/item.htm?id=1007108168970",
        headers={"content-type": "text/html"},
        text=AsyncMock(return_value=_BIXI_HTML),
        dispose=AsyncMock(),
    )
    unavailable = SimpleNamespace(
        ok=False,
        status=503,
        url="https://detail.damai.cn/item.htm?id=1007108168970",
        headers={"content-type": "text/html"},
        text=AsyncMock(return_value="maintenance"),
        dispose=AsyncMock(),
    )
    request_get = AsyncMock(side_effect=[blocked, unavailable])
    page = SimpleNamespace(
        context=SimpleNamespace(request=SimpleNamespace(get=request_get)),
        evaluate=AsyncMock(return_value="Mozilla/5.0 Chrome/126.0.0.0"),
    )
    sleep = AsyncMock()
    monkeypatch.setattr(detail_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(detail_module.random, "uniform", lambda low, _high: low)
    breaker = _SubpageCircuitBreaker(max_cooldowns=1)

    with pytest.raises(PcDetailCircuitOpenError):
        await fetch_item_static(
            page,
            "1007108168970",
            circuit_breaker=breaker,
        )

    assert request_get.await_count == 2
    assert [call.args[0] for call in sleep.await_args_list] == [105]
    blocked.dispose.assert_awaited_once()
    unavailable.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_detail_html_response_is_retryable_pc_channel_failure(caplog):
    response = SimpleNamespace(
        ok=True,
        status=200,
        headers={"content-type": "text/html;charset=UTF-8"},
        text=AsyncMock(return_value="\n<html>risk control</html>"),
        dispose=AsyncMock(),
    )
    page = SimpleNamespace(
        context=SimpleNamespace(request=SimpleNamespace(get=AsyncMock(return_value=response))),
        evaluate=AsyncMock(return_value="Mozilla/5.0 Chrome/126.0.0.0"),
    )

    with caplog.at_level("WARNING"), pytest.raises(PcDetailRetryableError) as caught:
        await fetch_subpage(page, "123")

    assert caught.value.reason == "html_response"
    assert "subpage pc unavailable" in caplog.text
    assert "status=200" in caplog.text
    assert "content_type=text/html" in caplog.text
    response.dispose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "url", "location", "expected_reason"),
    [
        (502, "https://detail.damai.cn/subpage", "", "http_502"),
        (
            302,
            "https://detail.damai.cn/subpage",
            "https://login.taobao.com/member/login.jhtml",
            "cross_domain_redirect",
        ),
        (
            200,
            "https://www.taobao.com/",
            "",
            "cross_domain_response",
        ),
    ],
)
async def test_subpage_http_and_cross_domain_failures_never_become_business_data(
    status,
    url,
    location,
    expected_reason,
):
    headers = {"content-type": "text/javascript;charset=UTF-8"}
    if location:
        headers["location"] = location
    response = SimpleNamespace(
        ok=200 <= status < 300,
        status=status,
        url=url,
        headers=headers,
        text=AsyncMock(return_value=""),
        dispose=AsyncMock(),
    )
    request_get = AsyncMock(return_value=response)
    page = SimpleNamespace(
        context=SimpleNamespace(request=SimpleNamespace(get=request_get)),
        evaluate=AsyncMock(return_value="Mozilla/5.0 Chrome/126.0.0.0"),
    )

    with pytest.raises(PcDetailRetryableError) as caught:
        await fetch_subpage(page, "123")

    assert caught.value.reason == expected_reason
    assert request_get.await_args.kwargs["max_redirects"] == 0
    response.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_subpage_detects_bixi_and_disposes_response():
    response = SimpleNamespace(
        ok=True,
        status=200,
        url="https://detail.damai.cn/subpage",
        headers={"content-type": "text/html;charset=UTF-8"},
        text=AsyncMock(return_value=_BIXI_HTML),
        dispose=AsyncMock(),
    )
    page = SimpleNamespace(
        context=SimpleNamespace(request=SimpleNamespace(get=AsyncMock(return_value=response))),
        evaluate=AsyncMock(return_value="Mozilla/5.0 Chrome/126.0.0.0"),
    )

    with pytest.raises(BixiPunishError) as caught:
        await fetch_subpage(
            page,
            "1007108168970",
            data_type="2",
            data_id="280339080",
        )

    assert caught.value.item_id == "1007108168970"
    assert caught.value.data_type == "2"
    assert caught.value.data_id == "280339080"
    assert caught.value.status == 200
    assert caught.value.body_chars == len(_BIXI_HTML)
    response.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_subpage_detects_bixi_url_even_with_http_error_and_empty_body():
    response = SimpleNamespace(
        ok=False,
        status=403,
        url="https://detail.damai.cn/subpage",
        headers={
            "content-type": "text/html",
            "location": "https://bixi.alicdn.com/punish/default.html?action=deny",
        },
        text=AsyncMock(return_value=""),
        dispose=AsyncMock(),
    )
    page = SimpleNamespace(
        context=SimpleNamespace(request=SimpleNamespace(get=AsyncMock(return_value=response))),
        evaluate=AsyncMock(return_value="Mozilla/5.0 Chrome/126.0.0.0"),
    )

    with pytest.raises(BixiPunishError) as caught:
        await fetch_subpage(page, "1007108168970")

    assert caught.value.status == 403
    assert caught.value.response_url.startswith("https://bixi.alicdn.com/punish")
    response.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_bixi_circuit_skips_fast_retry_and_replays_same_request(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    error = BixiPunishError(
        item_id="1007108168970",
        data_type="2",
        data_id="280339080",
        status=200,
        content_type="text/html",
        body_chars=1087,
    )
    fetch = AsyncMock(side_effect=[error, {"ready": True}])
    sleep = AsyncMock()
    monkeypatch.setattr(detail_module, "fetch_subpage", fetch)
    monkeypatch.setattr(detail_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(detail_module.random, "uniform", lambda low, _high: low)
    breaker = _SubpageCircuitBreaker(
        cooldown_min_s=180,
        cooldown_max_s=300,
        retry_cooldown_min_s=600,
        retry_cooldown_max_s=1200,
        max_cooldowns=2,
    )

    result = await _fetch_subpage_with_retry(
        object(),  # type: ignore[arg-type]
        "1007108168970",
        data_type="2",
        data_id="280339080",
        attempts=3,
        retry_delay_s=2,
        validator=lambda payload: payload.get("ready") is True,
        request_label="perform:280339080",
        circuit_breaker=breaker,
    )

    assert result == {"ready": True}
    assert fetch.await_count == 2
    assert fetch.await_args_list[0] == fetch.await_args_list[1]
    # 命中 bixi 后只有分钟级冷却，没有原来的 2 秒快速三连。
    assert [call.args[0] for call in sleep.await_args_list] == [180]


@pytest.mark.asyncio
async def test_repeated_bixi_suspends_batch_and_keeps_checkpoint(
    monkeypatch,
    tmp_path,
):
    import json

    import app.crawlers.damai.detail as detail_module

    error = BixiPunishError(
        item_id="1007108168970",
        data_type="2",
        data_id="280339080",
        status=200,
        content_type="text/html",
        body_chars=1087,
    )
    fetch = AsyncMock(side_effect=[error, error])
    sleep = AsyncMock()
    monkeypatch.setattr(detail_module, "fetch_subpage", fetch)
    monkeypatch.setattr(detail_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(detail_module.random, "uniform", lambda low, _high: low)
    checkpoint = tmp_path / "damai_detail_checkpoint.json"
    breaker = _SubpageCircuitBreaker(
        cooldown_min_s=180,
        cooldown_max_s=300,
        max_cooldowns=1,
        checkpoint_path=checkpoint,
    )
    items = [
        RawShowItem(
            source=SourcePlatform.DAMAI,
            source_id="1007108168970",
            title="A",
        ),
        RawShowItem(source=SourcePlatform.DAMAI, source_id="2", title="B"),
    ]
    breaker.set_batch_progress(1, items)

    with pytest.raises(PcDetailCircuitOpenError):
        await _fetch_subpage_with_retry(
            object(),  # type: ignore[arg-type]
            "1007108168970",
            data_type="2",
            data_id="280339080",
            attempts=3,
            retry_delay_s=2,
            request_label="perform:280339080",
            circuit_breaker=breaker,
        )

    assert fetch.await_count == 2
    assert [call.args[0] for call in sleep.await_args_list] == [180]
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["state"] == "suspended"
    assert payload["strategy"] == "restart_current_item_from_base"
    assert payload["request"]["data_id"] == "280339080"
    assert [item["source_id"] for item in payload["pending_items"]] == [
        "1007108168970",
        "2",
    ]


def test_checkpoint_is_only_cleared_by_the_item_that_created_it(tmp_path):
    checkpoint = tmp_path / "damai_detail_checkpoint.json"
    breaker = _SubpageCircuitBreaker(checkpoint_path=checkpoint)
    error = PcDetailRetryableError(item_id="item-a", reason="http_502")

    assert breaker._save_checkpoint(  # noqa: SLF001 - 验证断点归属边界
        state="channel_recovered_pending_persist",
        error=error,
        request_label="base",
        resume_at=None,
    )

    breaker.mark_item_persisted("item-b")
    assert checkpoint.exists()

    breaker.mark_item_persisted("item-a")
    assert not checkpoint.exists()


@pytest.mark.asyncio
async def test_default_bixi_recovery_uses_two_long_cooldowns_then_stops(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    error = BixiPunishError(
        item_id="1007108168970",
        data_type="2",
        data_id="280339080",
    )
    fetch = AsyncMock(side_effect=[error, None, error])
    sleep = AsyncMock()
    monkeypatch.setattr(detail_module, "fetch_subpage", fetch)
    monkeypatch.setattr(detail_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(detail_module.random, "uniform", lambda low, _high: low)
    breaker = _SubpageCircuitBreaker(max_cooldowns=2)

    with pytest.raises(PcDetailCircuitOpenError):
        await _fetch_subpage_with_retry(
            object(),  # type: ignore[arg-type]
            "1007108168970",
            data_type="2",
            data_id="280339080",
            attempts=3,
            retry_delay_s=2,
            request_label="perform:280339080",
            circuit_breaker=breaker,
        )

    # 第一次 bixi 后 105 秒；探测 None 后直接 240 秒长冷却；
    # 第三次仍 bixi 后停止。全程没有 2 秒快速重试。
    assert [call.args[0] for call in sleep.await_args_list] == [105, 240]
    assert fetch.await_count == 3


@pytest.mark.asyncio
async def test_cooldown_cancel_keeps_pending_checkpoint(monkeypatch, tmp_path):
    import asyncio
    import json

    import app.crawlers.damai.detail as detail_module

    error = BixiPunishError(item_id="1007108168970", data_type="2", data_id="x")
    monkeypatch.setattr(detail_module, "fetch_subpage", AsyncMock(side_effect=error))
    monkeypatch.setattr(
        detail_module.asyncio,
        "sleep",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    checkpoint = tmp_path / "cancelled_checkpoint.json"
    breaker = _SubpageCircuitBreaker(checkpoint_path=checkpoint)
    breaker.set_batch_progress(
        1,
        [RawShowItem(source=SourcePlatform.DAMAI, source_id="1007108168970", title="A")],
    )

    with pytest.raises(asyncio.CancelledError):
        await _fetch_subpage_with_retry(
            object(),  # type: ignore[arg-type]
            "1007108168970",
            data_type="2",
            data_id="x",
            circuit_breaker=breaker,
        )

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["state"] == "cancelled_during_cooldown"
    assert payload["request"]["data_id"] == "x"


@pytest.mark.asyncio
async def test_checkpoint_serialization_failure_does_not_change_bixi_control_flow(
    monkeypatch,
    tmp_path,
):
    import app.crawlers.damai.detail as detail_module

    error = BixiPunishError(item_id="1007108168970")
    monkeypatch.setattr(detail_module, "fetch_subpage", AsyncMock(side_effect=error))
    breaker = _SubpageCircuitBreaker(
        max_cooldowns=0,
        checkpoint_path=tmp_path / "bad.json",
    )
    breaker.set_batch_progress(
        1,
        [
            RawShowItem(
                source=SourcePlatform.DAMAI,
                source_id="1007108168970",
                title="A",
                raw_payload={"not_json": object()},
            )
        ],
    )

    with pytest.raises(PcDetailCircuitOpenError, match="断点保存失败"):
        await _fetch_subpage_with_retry(
            object(),  # type: ignore[arg-type]
            "1007108168970",
            circuit_breaker=breaker,
        )


def _subpage_payload(
    *,
    item_id: str,
    current_id: str,
    sessions: list[dict],
    prices: list[float],
    date_ids: list[str] | None = None,
    price_range: str = "￥280.00 - ￥1280.00",
) -> dict:
    current = next(session for session in sessions if session["performId"] == current_id)
    return {
        "responseInfo": {"responseSuccess": "true"},
        "itemBasicInfo": {
            "itemId": item_id,
            "cityName": "北京市",
            "venueName": "北京艺术中心",
            "priceRange": price_range,
        },
        "performCalendar": {
            "currentPerformId": current_id,
            "dateViews": [
                {"dateId": date_id, "clickable": "true"}
                for date_id in (date_ids or [])
            ],
            "performViews": sessions,
        },
        "perform": {
            **current,
            "skuList": [
                {
                    "skuId": f"sku-{current_id}-{price}",
                    "priceName": f"{price:.2f}元",
                    "price": str(price),
                    "skuSalable": "true",
                }
                for price in prices
            ],
        },
    }


@pytest.mark.asyncio
async def test_enrich_fetches_each_perform_tiers_and_uses_display_time(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    sessions = [
        {
            "performId": "pm",
            "performName": "2026-08-13 周四 14:30",
            # 线上真实出现过名称 14:30、结构化字段 14:00 的冲突。
            "performBeginDTStr": "202608131400",
            "dateKey": "20260813",
            "salable": "true",
        },
        {
            "performId": "night",
            "performName": "2026-08-13 周四 19:30",
            "performBeginDTStr": "202608131400",
            "dateKey": "20260813",
            "salable": "true",
        },
    ]
    base = _subpage_payload(
        item_id="1051733334817",
        current_id="pm",
        sessions=sessions,
        prices=[280, 680],
        date_ids=["20260813"],
    )
    night = _subpage_payload(
        item_id="1051733334817",
        current_id="night",
        sessions=sessions,
        prices=[580, 1280],
        date_ids=["20260813"],
    )

    async def fake_fetch(_page, _item_id, *, data_id="", data_type="", **_kwargs):
        if not data_id:
            return base
        if data_type == "2" and data_id == "night":
            return night
        raise AssertionError(f"unexpected subpage request {data_type=} {data_id=}")

    monkeypatch.setattr(detail_module, "_fetch_subpage_with_retry", fake_fetch)
    monkeypatch.setattr(detail_module, "fetch_item_static", AsyncMock(return_value={}))
    item = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="1051733334817",
        title="伦敦西区原版音乐剧《玛蒂尔达》",
        start_time_raw="2026.08.07-08.23",
    )

    enriched = await enrich_item_detail(object(), item, delay_s=0)  # type: ignore[arg-type]

    assert [session["start_time"] for session in enriched.sessions_raw] == [
        "2026-08-13 14:30",
        "2026-08-13 19:30",
    ]
    assert [
        [tier["price"] for tier in session["ticket_tiers"]]
        for session in enriched.sessions_raw
    ] == [[280.0, 680.0], [580.0, 1280.0]]
    detail = enriched.raw_payload["detail"]
    assert detail["detail_complete"] is True
    assert detail["ticket_sessions_requested"] == 1
    assert detail["ticket_sessions_fetched"] == 1


@pytest.mark.asyncio
async def test_enrich_rejects_success_json_without_expected_item(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    fetch = AsyncMock(
        return_value={"responseInfo": {"responseSuccess": "true"}}
    )
    monkeypatch.setattr(detail_module, "fetch_subpage", fetch)
    item = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="1051733334817",
        title="A",
    )

    with pytest.raises(PcDetailSemanticError, match="内容不匹配"):
        await enrich_item_detail(
            object(),  # type: ignore[arg-type]
            item,
            delay_s=0,
            request_attempts=1,
        )

    fetch.assert_awaited_once()


def test_parse_item_static_exposes_strict_app_only_purchase_state():
    import app.crawlers.damai.detail as detail_module

    item_id = "1055929918278"
    static = parse_item_static_html(_pc_app_only_item_html(item_id))

    assert static["_source_item_id"] == item_id
    assert static["_buy_btn_status"] == 100
    assert static["_buy_btn_origin"] == 109
    assert detail_module._is_pc_app_only_static(static, item_id) is True
    assert detail_module._is_pc_app_only_static(static, "1056876653291") is False


@pytest.mark.asyncio
async def test_pc_app_only_project_falls_back_to_mobile_without_three_base_retries(
    monkeypatch,
):
    import app.crawlers.damai.detail as detail_module

    item_id = "1055929918278"
    fetch = AsyncMock(return_value=_pc_app_only_subpage_payload())
    static = AsyncMock(
        return_value=parse_item_static_html(_pc_app_only_item_html(item_id))
    )
    mobile = AsyncMock(
        side_effect=lambda item, **_kwargs: item
    )
    monkeypatch.setattr(detail_module, "fetch_subpage", fetch)
    monkeypatch.setattr(detail_module, "fetch_item_static", static)
    monkeypatch.setattr(detail_module, "enrich_item_mobile_detail", mobile)
    item = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id=item_id,
        title="App 专购项目",
    )

    out = await detail_module.enrich_items_detail(
        object(),
        [item],
        delay_s=0,
        request_attempts=3,
    )

    assert out == [item]
    assert fetch.await_count == 1
    static.assert_awaited_once()
    mobile.assert_awaited_once_with(
        item,
        request_attempts=3,
        retry_delay_s=2.0,
    )


@pytest.mark.asyncio
async def test_pc_app_only_candidate_with_wrong_static_item_never_uses_mobile(
    monkeypatch,
):
    import app.crawlers.damai.detail as detail_module

    item_id = "1055929918278"
    monkeypatch.setattr(
        detail_module,
        "fetch_subpage",
        AsyncMock(return_value=_pc_app_only_subpage_payload()),
    )
    monkeypatch.setattr(
        detail_module,
        "fetch_item_static",
        AsyncMock(
            return_value=parse_item_static_html(
                _pc_app_only_item_html("1056876653291")
            )
        ),
    )
    mobile = AsyncMock()
    monkeypatch.setattr(detail_module, "enrich_item_mobile_detail", mobile)
    item = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id=item_id,
        title="A",
    )

    out = await detail_module.enrich_items_detail(
        object(),
        [item],
        delay_s=0,
        request_attempts=1,
    )

    assert out == []
    mobile.assert_not_awaited()


@pytest.mark.asyncio
async def test_pc_app_only_candidate_ignores_body_text_and_normal_buy_button(
    monkeypatch,
):
    import app.crawlers.damai.detail as detail_module

    item_id = "1055929918278"
    monkeypatch.setattr(
        detail_module,
        "fetch_subpage",
        AsyncMock(return_value=_pc_app_only_subpage_payload()),
    )
    monkeypatch.setattr(
        detail_module,
        "fetch_item_static",
        AsyncMock(
            return_value=parse_item_static_html(
                _pc_app_only_item_html(
                    item_id,
                    buy_status=204,
                    buy_origin=12,
                    buy_text="立即购票",
                    buy_tip="",
                    description="该渠道不支持购票，请到大麦App购买",
                )
            )
        ),
    )
    mobile = AsyncMock()
    monkeypatch.setattr(detail_module, "enrich_item_mobile_detail", mobile)
    item = RawShowItem(source=SourcePlatform.DAMAI, source_id=item_id, title="A")

    out = await detail_module.enrich_items_detail(
        object(),
        [item],
        delay_s=0,
        request_attempts=1,
    )

    assert out == []
    mobile.assert_not_awaited()


@pytest.mark.asyncio
async def test_pc_app_only_candidate_static_502_never_uses_mobile(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    item_id = "1055929918278"
    monkeypatch.setattr(
        detail_module,
        "fetch_subpage",
        AsyncMock(return_value=_pc_app_only_subpage_payload()),
    )
    monkeypatch.setattr(
        detail_module,
        "fetch_item_static",
        AsyncMock(
            side_effect=PcDetailRetryableError(
                item_id=item_id,
                reason="http_502",
                status=502,
            )
        ),
    )
    mobile = AsyncMock()
    on_item = AsyncMock()
    monkeypatch.setattr(detail_module, "enrich_item_mobile_detail", mobile)
    item = RawShowItem(source=SourcePlatform.DAMAI, source_id=item_id, title="A")

    with pytest.raises(PcDetailRetryableError) as caught:
        await detail_module.enrich_items_detail(
            object(),
            [item],
            delay_s=0,
            request_attempts=1,
            on_item=on_item,
        )

    assert caught.value.reason == "http_502"
    mobile.assert_not_awaited()
    on_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_pc_item_id_cannot_be_disguised_as_app_only(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    item_id = "1055929918278"
    wrong_base = _pc_app_only_subpage_payload()
    wrong_base["itemBasicInfo"] = {"itemId": "1056876653291"}
    fetch = AsyncMock(return_value=wrong_base)
    static = AsyncMock()
    mobile = AsyncMock()
    monkeypatch.setattr(detail_module, "fetch_subpage", fetch)
    monkeypatch.setattr(detail_module, "fetch_item_static", static)
    monkeypatch.setattr(detail_module, "enrich_item_mobile_detail", mobile)
    item = RawShowItem(source=SourcePlatform.DAMAI, source_id=item_id, title="A")

    out = await detail_module.enrich_items_detail(
        object(),
        [item],
        delay_s=0,
        request_attempts=1,
    )

    assert out == []
    fetch.assert_awaited_once()
    static.assert_not_awaited()
    mobile.assert_not_awaited()


@pytest.mark.parametrize(
    ("buy_status", "buy_origin", "buy_text", "buy_tip"),
    [
        (204, 12, "立即购票", ""),
        (100, 109, "立即购票", "请到大麦App购买"),
        (100, 109, "该渠道不支持购票", ""),
    ],
)
def test_pc_app_only_static_requires_all_structured_business_markers(
    buy_status,
    buy_origin,
    buy_text,
    buy_tip,
):
    import app.crawlers.damai.detail as detail_module

    item_id = "1055929918278"
    static = parse_item_static_html(
        _pc_app_only_item_html(
            item_id,
            buy_status=buy_status,
            buy_origin=buy_origin,
            buy_text=buy_text,
            buy_tip=buy_tip,
        )
    )

    assert detail_module._is_pc_app_only_static(static, item_id) is False


@pytest.mark.asyncio
async def test_empty_sku_with_visible_pc_price_range_stays_on_pc(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    item_id = "1051733334817"
    sessions = [
        {
            "performId": "pm",
            "performName": "2026-08-13 周四 14:30",
            "performBeginDTStr": "202608131430",
            "dateKey": "20260813",
            "salable": "true",
        },
        {
            "performId": "night",
            "performName": "2026-08-13 周四 19:30",
            "performBeginDTStr": "202608131930",
            "dateKey": "20260813",
            "salable": "false",
        },
    ]
    base = _subpage_payload(
        item_id=item_id,
        current_id="pm",
        sessions=sessions,
        prices=[280],
        date_ids=["20260813"],
    )
    empty_tiers = _subpage_payload(
        item_id=item_id,
        current_id="night",
        sessions=sessions,
        prices=[],
        date_ids=["20260813"],
    )

    async def fake_fetch(
        _page,
        _item_id,
        *,
        data_id="",
        data_type="",
        **_kwargs,
    ):
        if not data_id:
            return base
        if data_type == "2" and data_id == "night":
            return empty_tiers
        raise AssertionError(f"unexpected subpage request {data_type=} {data_id=}")

    fetch = AsyncMock(side_effect=fake_fetch)
    monkeypatch.setattr(detail_module, "fetch_subpage", fetch)
    monkeypatch.setattr(
        detail_module,
        "fetch_item_static",
        AsyncMock(return_value={}),
    )
    item = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id=item_id,
        title="A",
    )

    enriched = await enrich_item_detail(item=item, page=object(), delay_s=0)

    assert fetch.await_count == 2
    assert enriched.raw_payload["detail"]["detail_complete"] is True
    assert enriched.raw_payload["detail"]["ticket_sessions_fetched"] == 1
    assert enriched.sessions_raw[1]["ticket_tiers"] == []


@pytest.mark.asyncio
async def test_optional_static_failure_does_not_discard_confirmed_pc_price(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    item_id = "1051733334817"
    sessions = [
        {
            "performId": "pm",
            "performName": "2026-08-13 周四 14:30",
            "performBeginDTStr": "202608131430",
            "dateKey": "20260813",
            "salable": "true",
        }
    ]
    base = _subpage_payload(
        item_id=item_id,
        current_id="pm",
        sessions=sessions,
        prices=[280],
        date_ids=["20260813"],
    )
    monkeypatch.setattr(
        detail_module,
        "_fetch_subpage_with_retry",
        AsyncMock(return_value=base),
    )
    monkeypatch.setattr(
        detail_module,
        "fetch_item_static",
        AsyncMock(
            side_effect=PcDetailRetryableError(
                item_id=item_id,
                reason="http_502",
                status=502,
            )
        ),
    )
    item = RawShowItem(source=SourcePlatform.DAMAI, source_id=item_id, title="A")

    enriched = await enrich_item_detail(item=item, page=object(), delay_s=0)

    assert enriched.price_raw == "280"


@pytest.mark.asyncio
async def test_complete_pc_detail_without_any_price_requests_mobile_fallback_signal(
    monkeypatch,
):
    import app.crawlers.damai.detail as detail_module

    item_id = "1051733334817"
    sessions = [
        {
            "performId": "pm",
            "performName": "2026-08-13 周四 14:30",
            "performBeginDTStr": "202608131430",
            "dateKey": "20260813",
            "salable": "false",
        },
        {
            "performId": "night",
            "performName": "2026-08-13 周四 19:30",
            "performBeginDTStr": "202608131930",
            "dateKey": "20260813",
            "salable": "false",
        },
    ]
    base = _subpage_payload(
        item_id=item_id,
        current_id="pm",
        sessions=sessions,
        prices=[],
        date_ids=["20260813"],
        price_range="",
    )
    night = _subpage_payload(
        item_id=item_id,
        current_id="night",
        sessions=sessions,
        prices=[],
        date_ids=["20260813"],
        price_range="",
    )

    async def fake_fetch(
        _page,
        _item_id,
        *,
        data_id="",
        data_type="",
        **_kwargs,
    ):
        if not data_id:
            return base
        if data_type == "2" and data_id == "night":
            return night
        raise AssertionError(f"unexpected subpage request {data_type=} {data_id=}")

    monkeypatch.setattr(detail_module, "fetch_subpage", AsyncMock(side_effect=fake_fetch))
    monkeypatch.setattr(detail_module, "fetch_item_static", AsyncMock(return_value={}))
    item = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id=item_id,
        title="A",
    )

    with pytest.raises(PcDetailNoPriceError, match="未展示价格"):
        await enrich_item_detail(item=item, page=object(), delay_s=0)


def test_parse_description_sections_troupe_and_artists():
    from app.crawlers.damai.detail import parse_description_sections, parse_price_text_to_ladder

    text = """
曲目
马勒第四
演出团体
国家大剧院管弦乐团
音乐总监：吕嘉
指挥
俞峰
艺术家
李晶晶
票价：80 / 180 / 280 / VIP 680
地点：星海音乐厅 交响乐演奏大厅
主办：广州交响乐团 星海音乐厅
"""
    p = parse_description_sections(text)
    assert p["troupe"] == "国家大剧院管弦乐团"
    assert "俞峰" in p["performers"] or p["conductor"] == "俞峰"
    assert "广州交响乐团" in p["organizers"] or "星海音乐厅" in p["organizers"]
    assert parse_price_text_to_ladder(p["price_text"]) == "80|180|280|680"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("￥280 - ￥1280", True),
        ("票价：80 / 180 / 280 / VIP 680", True),
        ("680元", True),
        ("双人套票（2人）", False),
        ("儿童1.2米以下免票", False),
        ("2026年待定", False),
    ],
)
def test_price_presence_rejects_non_price_numbers(text, expected):
    import app.crawlers.damai.detail as detail_module

    assert detail_module._text_has_price_amount(text) is expected


@pytest.mark.asyncio
async def test_enrich_items_emits_each_completed_detail_immediately(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    events: list[str] = []

    async def fake_enrich(_page, item, **_kwargs):
        events.append(f"fetch:{item.source_id}")
        item.sessions_raw = [
            {
                "id": f"session-{item.source_id}",
                "start_time": "2026-08-01 19:30",
                "date_key": "20260801",
            }
        ]
        return item

    async def on_item(item):
        events.append(f"persist:{item.source_id}")

    monkeypatch.setattr(detail_module, "enrich_item_detail", fake_enrich)
    items = [
        RawShowItem(source=SourcePlatform.DAMAI, source_id="1", title="A"),
        RawShowItem(source=SourcePlatform.DAMAI, source_id="2", title="B"),
    ]

    out = await detail_module.enrich_items_detail(
        object(), items, delay_s=0, on_item=on_item
    )

    assert [item.source_id for item in out] == ["1", "2"]
    assert events == ["fetch:1", "persist:1", "fetch:2", "persist:2"]


@pytest.mark.asyncio
async def test_enrich_items_uses_mobile_only_when_pc_explicitly_has_no_price(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    pc_attempts = 0
    mobile_attempts = 0

    async def failed_pc(_page, _item, **_kwargs):
        nonlocal pc_attempts
        pc_attempts += 1
        raise PcDetailNoPriceError("PC response complete but no price")

    async def mobile_success(item, **_kwargs):
        nonlocal mobile_attempts
        mobile_attempts += 1
        return item

    on_item = AsyncMock()
    monkeypatch.setattr(detail_module, "enrich_item_detail", failed_pc)
    monkeypatch.setattr(detail_module, "enrich_item_mobile_detail", mobile_success)
    item = RawShowItem(source=SourcePlatform.DAMAI, source_id="1", title="A")

    out = await detail_module.enrich_items_detail(
        object(),
        [item],
        delay_s=0,
        project_attempts=2,
        project_cooldown_s=0,
        on_item=on_item,
    )

    assert out == [item]
    assert pc_attempts == 1
    assert mobile_attempts == 1
    on_item.assert_awaited_once_with(item)


@pytest.mark.asyncio
async def test_enrich_items_never_mobile_fallbacks_on_bixi(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    async def blocked_pc(_page, _item, **_kwargs):
        raise PcDetailCircuitOpenError("bixi still active")

    mobile = AsyncMock()
    on_item = AsyncMock()
    monkeypatch.setattr(detail_module, "enrich_item_detail", blocked_pc)
    monkeypatch.setattr(detail_module, "enrich_item_mobile_detail", mobile)
    item = RawShowItem(source=SourcePlatform.DAMAI, source_id="1", title="A")

    with pytest.raises(PcDetailCircuitOpenError, match="bixi still active"):
        await detail_module.enrich_items_detail(
            object(),
            [item],
            delay_s=0,
            on_item=on_item,
        )

    mobile.assert_not_awaited()
    on_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrich_items_never_mobile_fallbacks_on_retryable_pc_failure(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    async def blocked_pc(_page, _item, **_kwargs):
        raise PcDetailRetryableError(item_id="1", reason="http_502", status=502)

    mobile = AsyncMock()
    monkeypatch.setattr(detail_module, "enrich_item_detail", blocked_pc)
    monkeypatch.setattr(detail_module, "enrich_item_mobile_detail", mobile)
    item = RawShowItem(source=SourcePlatform.DAMAI, source_id="1", title="A")

    with pytest.raises(PcDetailRetryableError) as caught:
        await detail_module.enrich_items_detail(object(), [item], delay_s=0)

    assert caught.value.reason == "http_502"
    mobile.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrich_items_share_one_circuit_breaker(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    breakers = []

    async def successful_pc(_page, item, **kwargs):
        breakers.append(kwargs["circuit_breaker"])
        return item

    monkeypatch.setattr(detail_module, "enrich_item_detail", successful_pc)
    items = [
        RawShowItem(source=SourcePlatform.DAMAI, source_id="1", title="A"),
        RawShowItem(source=SourcePlatform.DAMAI, source_id="2", title="B"),
    ]

    await detail_module.enrich_items_detail(object(), items, delay_s=0)

    assert len(breakers) == 2
    assert breakers[0] is breakers[1]


@pytest.mark.asyncio
async def test_enrich_items_skips_failed_project_and_continues(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    async def pc_enrich(_page, item, **_kwargs):
        if item.source_id == "1":
            raise DetailCompletenessError("blocked")
        return item

    on_item = AsyncMock()
    mobile_enrich = AsyncMock()
    monkeypatch.setattr(detail_module, "enrich_item_detail", pc_enrich)
    monkeypatch.setattr(detail_module, "enrich_item_mobile_detail", mobile_enrich)
    failed = RawShowItem(source=SourcePlatform.DAMAI, source_id="1", title="A")
    successful = RawShowItem(source=SourcePlatform.DAMAI, source_id="2", title="B")

    out = await detail_module.enrich_items_detail(
        object(),
        [failed, successful],
        delay_s=0,
        project_attempts=2,
        project_cooldown_s=90,
        on_item=on_item,
    )

    assert out == [successful]
    on_item.assert_awaited_once_with(successful)
    mobile_enrich.assert_not_awaited()


def test_detail_retry_defaults_are_fixed_and_non_blocking():
    from app.core.config import CrawlConfig

    config = CrawlConfig()

    assert config.detail_delay_seconds >= 1.5
    assert config.detail_date_limit == 0
    assert config.detail_retry_attempts == 3
    assert config.detail_retry_delay_seconds == 2
    assert config.detail_project_attempts == 1
    assert config.detail_project_cooldown_seconds == 0
    assert config.detail_punish_cooldown_min_seconds == 105
    assert config.detail_punish_cooldown_max_seconds == 135
    assert config.detail_punish_retry_cooldown_min_seconds == 240
    assert config.detail_punish_retry_cooldown_max_seconds == 360
    assert config.detail_punish_max_cooldowns == 2
