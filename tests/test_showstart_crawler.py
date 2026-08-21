"""Showstart crawler behavior."""

from importlib import import_module

import pytest

from app.core.config import AppConfig
from app.models import SourcePlatform


def _list_record(activity_id: int = 101, *, sold_out: int = 0) -> dict:
    return {
        "id": activity_id,
        "title": "北京爵士夜",
        "poster": "https://img.example/poster.jpg",
        "price": "120-380",
        "showTime": "2026/09/03 20:00",
        "siteName": "Blue Note",
        "cityName": "北京",
        "soldOut": sold_out,
    }


def _detail_record() -> dict:
    return {
        "styles": "爵士",
        "performers": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
        "site": {"id": 9, "name": "Blue Note", "address": "前门东大街 23 号"},
        "tickets": [
            {
                "id": 11,
                "ticketName": "预售票",
                "sellPriceStr": "180.00",
                "originalPriceStr": "220.00",
                "status": 0,
            },
            {
                "id": 12,
                "ticketName": "停售票",
                "sellPriceStr": "待定",
                "originalPriceStr": "",
                "status": 1,
            },
        ],
        "content": "<p>must not be stored</p>",
    }


@pytest.mark.asyncio
async def test_crawler_maps_list_and_detail_and_emits_callbacks(monkeypatch):
    module = import_module("app.crawlers.showstart.crawler")
    calls: list[dict] = []

    class FakeClient:
        async def list_params(self):
            return [
                {
                    "cityName": "北京",
                    "cityCode": 10,
                    "styles": [{"key": 10, "showName": "爵士"}],
                }
            ]

        async def activity_list(self, **kwargs):
            calls.append(kwargs)
            return {"pageNo": 1, "totalPage": 1, "result": [_list_record()]}

        async def activity_info(self, activity_id):
            assert activity_id == "101"
            return _detail_record()

        async def aclose(self):
            return None

    monkeypatch.setattr(module, "ShowstartClient", FakeClient)
    config = AppConfig()
    config.crawl.request_delay_seconds = 0
    config.crawl.detail_delay_seconds = 0
    emitted = []
    discovered = []
    crawler = module.ShowstartCrawler(None, config)

    items = await crawler.crawl(
        cities=["北京"],
        keywords=["爵士"],
        max_pages=1,
        category="爵士",
        on_item=emitted.append,
        on_items_discovered=discovered.extend,
    )

    assert calls == [
        {
            "page_no": 1,
            "city_code": "10",
            "show_style": "10",
            "keyword": "爵士",
        }
    ]
    assert emitted == items
    assert [item.source_id for item in discovered] == ["101"]
    item = items[0]
    assert (item.source, item.url, item.city) == (
        SourcePlatform.SHOWSTART,
        "https://www.showstart.com/event/101",
        "北京",
    )
    assert (item.venue_name, item.venue_address) == ("Blue Note", "前门东大街 23 号")
    assert (item.price_raw, item.status_raw, item.start_time_raw) == (
        "120-380",
        "在售",
        "2026/09/03 20:00",
    )
    assert item.artists == ["Alice", "Bob"]
    assert item.category == "爵士"
    assert item.sessions_raw[0]["ticket_tiers"] == [
        {
            "name": "预售票",
            "price": 180.0,
            "status": "onsale",
            "salable": True,
            "raw": "预售票 180.00",
        },
        {
            "name": "停售票",
            "price": None,
            "status": "",
            "salable": False,
            "raw": "停售票 待定",
        },
    ]
    assert item.raw_payload["detail"]["performers"] == ["Alice", "Bob"]
    assert "content" not in str(item.raw_payload)


@pytest.mark.asyncio
async def test_detail_failure_keeps_list_item(monkeypatch):
    module = import_module("app.crawlers.showstart.crawler")

    class FakeClient:
        async def list_params(self):
            return [{"cityName": "北京", "cityCode": 10, "styles": []}]

        async def activity_list(self, **_kwargs):
            return {"totalPage": 1, "result": [_list_record()]}

        async def activity_info(self, _activity_id):
            raise RuntimeError("detail unavailable")

        async def aclose(self):
            return None

    monkeypatch.setattr(module, "ShowstartClient", FakeClient)
    config = AppConfig()
    config.crawl.detail_delay_seconds = 0
    emitted = []

    items = await module.ShowstartCrawler(None, config).crawl(
        cities=["北京"], keywords=[], max_pages=0, on_item=emitted.append
    )

    assert emitted == items
    assert items[0].status_raw == "在售"
    assert items[0].sessions_raw == []
    assert items[0].raw_payload["detail"] == {}


@pytest.mark.parametrize(
    ("show_time", "expected_status"),
    [
        ("2099/01/01 20:00", "在售"),  # 未来场次（列表 soldOut 恒为 1，不可信）
        ("2020/01/01 20:00", "已结束"),  # 历史场次
        ("not-a-date", "在售"),  # 无法解析按在售处理
        ("", "在售"),
    ],
)
def test_status_derived_from_show_time(show_time, expected_status):
    module = import_module("app.crawlers.showstart.crawler")
    assert module.ShowstartCrawler._status_from_show_time(show_time) == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_pages", "total_page", "empty_page", "expected_pages"),
    [
        (2, 9, 0, [1, 2]),
        (0, 2, 0, [1, 2]),
        (0, 9, 2, [1, 2]),
    ],
)
async def test_pagination_stop_conditions(
    monkeypatch,
    max_pages,
    total_page,
    empty_page,
    expected_pages,
):
    module = import_module("app.crawlers.showstart.crawler")
    requested_pages = []

    class FakeClient:
        async def list_params(self):
            return [{"cityName": "北京", "cityCode": 10, "styles": []}]

        async def activity_list(self, **kwargs):
            page_no = kwargs["page_no"]
            requested_pages.append(page_no)
            records = [] if page_no == empty_page else [_list_record(page_no)]
            return {"totalPage": total_page, "result": records}

        async def aclose(self):
            return None

    monkeypatch.setattr(module, "ShowstartClient", FakeClient)
    config = AppConfig()
    config.crawl.enrich_detail = False
    config.crawl.request_delay_seconds = 0

    await module.ShowstartCrawler(None, config).crawl(
        cities=["北京"], keywords=[], max_pages=max_pages
    )

    assert requested_pages == expected_pages


@pytest.mark.asyncio
async def test_unknown_filters_and_dedupe_across_keywords(monkeypatch, caplog):
    module = import_module("app.crawlers.showstart.crawler")
    list_calls = []
    discovered_sizes = []

    class FakeClient:
        async def list_params(self):
            return [{"cityName": "北京", "cityCode": 10, "styles": []}]

        async def activity_list(self, **kwargs):
            list_calls.append(kwargs)
            return {"totalPage": 1, "result": [_list_record()]}

        async def aclose(self):
            return None

    monkeypatch.setattr(module, "ShowstartClient", FakeClient)
    config = AppConfig()
    config.crawl.enrich_detail = False

    items = await module.ShowstartCrawler(None, config).crawl(
        cities=["不存在", "北京"],
        keywords=["A", "B"],
        max_pages=1,
        category="未知风格",
        on_items_discovered=lambda batch: discovered_sizes.append(len(batch)),
    )

    assert len(items) == 1
    assert [call["show_style"] for call in list_calls] == ["", ""]
    assert discovered_sizes == [1, 0]
    assert "unknown showstart category" in caplog.text
    assert "unknown showstart city" in caplog.text
