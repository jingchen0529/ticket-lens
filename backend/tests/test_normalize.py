from app.models import RawShowItem, SourcePlatform, ShowStatus
from app.pipeline.normalize import normalize_items, normalize_one, map_status
from app.utils.timeparse import parse_price_range, parse_chinese_datetime


def test_map_status():
    assert map_status("在售") == ShowStatus.ONSALE
    assert map_status("已售罄") == ShowStatus.SOLD_OUT
    assert map_status("预售中") == ShowStatus.PRESALE
    assert map_status("") == ShowStatus.UNKNOWN


def test_parse_price_range():
    p = parse_price_range("280-1280元")
    assert p.min_price == 280
    assert p.max_price == 1280

    p2 = parse_price_range("￥580")
    assert p2.min_price == 580
    assert p2.max_price == 580

    p3 = parse_price_range("票价待定")
    assert p3.min_price is None


def test_parse_datetime():
    dt = parse_chinese_datetime("2026.07.18 19:30")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 18
    assert dt.tzinfo is None


def test_price_ladder_from_ticket_tiers():
    from app.pipeline.normalize import format_price_ladder, build_price_range

    assert format_price_ladder([280, 80, 180, 80]) == "80|180|280"
    pr = build_price_range(tier_prices=[1080, 80, 180], price_raw="旧")
    assert pr.raw == "80|180|1080"
    assert pr.min_price == 80
    assert pr.max_price == 1080

    raw = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="p1",
        title="票档测试",
        sessions_raw=[
            {
                "id": "s1",
                "name": "场1",
                "start_time": "2026-08-01 19:30",
                "ticket_tiers": [
                    {"name": "A", "price": 90},
                    {"name": "B", "price": 180},
                    {"name": "C", "price": 280},
                ],
            }
        ],
    )
    show = normalize_one(raw)
    assert show is not None
    assert show.price.raw == "90|180|280"


def test_parse_datetime_date_range_uses_start_and_stays_naive():
    """大麦区间时间不得被 dateutil 误解析成非法时区 offset。"""
    dt = parse_chinese_datetime("2026.07.18-2026.07.20")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2026, 7, 18)
    assert dt.tzinfo is None

    # 曾触发: offset must be a timedelta strictly between ±24h
    dt2 = parse_chinese_datetime("2026.01.01-12.31")
    assert dt2 is not None
    assert (dt2.year, dt2.month, dt2.day) == (2026, 1, 1)
    assert dt2.tzinfo is None

    dt3 = parse_chinese_datetime("2026.07.18 19:30-21:30")
    assert dt3 is not None
    assert (dt3.hour, dt3.minute) == (19, 30)
    assert dt3.tzinfo is None


def test_normalize_date_range_does_not_raise():
    raw = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="range-1",
        title="区间时间演出",
        city="北京",
        start_time_raw="2026.01.01-12.31",
    )
    show = normalize_one(raw)
    assert show is not None
    assert show.start_time is not None
    # 可 JSON 序列化（曾在 model_dump 时炸 offset）
    payload = show.model_dump(mode="json")
    assert "2026-01-01" in (payload.get("start_time") or "")


def test_normalize_damai_raw():
    raw = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="12345",
        title="周杰伦演唱会",
        city="北京",
        venue_name="北京 | 国家体育场",
        price_raw="380-1680",
        status_raw="在售",
        start_time_raw="2026-08-01 19:30",
        url="https://detail.damai.cn/item.htm?id=12345",
    )
    show = normalize_one(raw)
    assert show is not None
    assert show.id == "damai:12345"
    assert show.source == SourcePlatform.DAMAI
    assert show.venue.city == "北京"
    assert show.price.min_price == 380
    assert show.status == ShowStatus.ONSALE
    assert show.start_time is not None


def test_normalize_dedupe():
    raws = [
        RawShowItem(source=SourcePlatform.MAOYAN, source_id="1", title="A"),
        RawShowItem(source=SourcePlatform.MAOYAN, source_id="1", title="A"),
        RawShowItem(source=SourcePlatform.DAMAI, source_id="1", title="A"),
    ]
    shows = normalize_items(raws)
    assert len(shows) == 2
    ids = {s.id for s in shows}
    assert ids == {"maoyan:1", "damai:1"}
