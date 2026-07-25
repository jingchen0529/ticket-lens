"""大麦详情 subpage 解析与写回 RawShowItem。"""

from __future__ import annotations

import json
from pathlib import Path

from app.crawlers.damai.detail import (
    apply_detail_to_raw,
    extract_detail_from_subpage,
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
