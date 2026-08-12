"""大麦详情 subpage 解析与写回 RawShowItem。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.crawlers.damai.detail import (
    DetailCompletenessError,
    _fetch_subpage_with_retry,
    apply_detail_to_raw,
    enrich_item_detail,
    enrich_item_mobile_detail,
    extract_detail_from_subpage,
    extract_detail_from_mobile,
    fetch_item_static,
    fetch_subpage,
    merge_sessions,
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


def test_parse_jsonp_jp0():
    data = parse_jsonp('__jp0({"a":1,"b":"x"})')
    assert data == {"a": 1, "b": "x"}
    assert parse_jsonp('{"a":2}') == {"a": 2}
    assert parse_jsonp("") is None


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
    assert all(
        call.args == ("() => navigator.userAgent",)
        for call in page.evaluate.await_args_list
    )
    subpage_response.dispose.assert_awaited_once()
    static_response.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_detail_parse_failure_logs_response_shape(caplog):
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

    with caplog.at_level("WARNING"):
        data = await fetch_subpage(page, "123")

    assert data is None
    assert "subpage invalid response" in caplog.text
    assert "status=200" in caplog.text
    assert "content_type=text/html" in caplog.text
    assert "risk control" in caplog.text
    response.dispose.assert_awaited_once()


def _subpage_payload(
    *,
    item_id: str,
    current_id: str,
    sessions: list[dict],
    prices: list[float],
    date_ids: list[str] | None = None,
) -> dict:
    current = next(session for session in sessions if session["performId"] == current_id)
    return {
        "responseInfo": {"responseSuccess": "true"},
        "itemBasicInfo": {
            "itemId": item_id,
            "cityName": "北京市",
            "venueName": "北京艺术中心",
            "priceRange": "￥280.00 - ￥1280.00",
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

    with pytest.raises(DetailCompletenessError, match="基础响应重试耗尽"):
        await enrich_item_detail(
            object(),  # type: ignore[arg-type]
            item,
            delay_s=0,
            request_attempts=1,
        )

    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_enrich_accepts_explicitly_empty_ticket_tier_list(monkeypatch):
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
async def test_enrich_items_uses_mobile_fallback_without_project_retry(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    pc_attempts = 0
    mobile_attempts = 0

    async def failed_pc(_page, _item, **_kwargs):
        nonlocal pc_attempts
        pc_attempts += 1
        raise DetailCompletenessError("PC business 404")

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
async def test_enrich_items_skips_failed_project_and_continues(monkeypatch):
    import app.crawlers.damai.detail as detail_module

    async def pc_enrich(_page, item, **_kwargs):
        if item.source_id == "1":
            raise DetailCompletenessError("blocked")
        return item

    async def mobile_enrich(_item, **_kwargs):
        raise DetailCompletenessError("mobile blocked")

    on_item = AsyncMock()
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


def test_detail_retry_defaults_are_fixed_and_non_blocking():
    from app.core.config import CrawlConfig

    config = CrawlConfig()

    assert config.detail_delay_seconds >= 1.5
    assert config.detail_date_limit == 0
    assert config.detail_retry_attempts == 3
    assert config.detail_retry_delay_seconds == 2
    assert config.detail_project_attempts == 1
    assert config.detail_project_cooldown_seconds == 0
