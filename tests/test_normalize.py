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


def test_date_range_is_not_counted_as_a_concrete_session():
    raw = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="range-summary",
        title="长档期演出",
        city="北京",
        start_time_raw="2026.08.07-08.23",
    )

    aggregate = normalize_one(raw)
    assert aggregate is not None
    assert aggregate.sessions == []

    split = normalize_items([raw])
    assert len(split) == 1
    assert split[0].start_time is None
    assert split[0].sessions == []


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
    # 拆分后无有效日期的兜底条 id 带 :1 后缀
    ids = {s.id for s in shows}
    assert ids == {"maoyan:1:1", "damai:1:1"}


def _raw_with_sessions(source_id: str, session_times: list[str], title: str = "拆分测试"):
    return RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id=source_id,
        title=title,
        sessions_raw=[
            {"id": f"s{i}", "name": t, "start_time": t}
            for i, t in enumerate(session_times, start=1)
        ],
    )


def test_split_multi_day_into_multiple_rows():
    """跨多日的演出按场次拆成多条，id 带序号且按时间升序。"""
    raw = _raw_with_sessions(
        "978489769120",
        ["2026-07-28 15:00", "2026-07-26 15:00", "2026-07-27 11:00"],
    )
    shows = normalize_items([raw])
    assert len(shows) == 3
    # 序号按场次时间升序：最早的 07-26 是 :1
    ids = [s.id for s in shows]
    assert ids == [
        "damai:978489769120:1",
        "damai:978489769120:2",
        "damai:978489769120:3",
    ]
    starts = [s.start_time.strftime("%Y-%m-%d") for s in shows]
    assert starts == ["2026-07-26", "2026-07-27", "2026-07-28"]
    # 每条只保留自身一个场次
    assert all(len(s.sessions) == 1 for s in shows)


def test_split_same_day_multiple_sessions_each_row():
    """同一天多个场次也各拆一条（每场次一条）。"""
    raw = _raw_with_sessions(
        "950252691257",
        ["2026-07-26 15:00", "2026-07-26 17:00", "2026-07-26 19:00"],
    )
    shows = normalize_items([raw])
    assert len(shows) == 3
    assert {s.id for s in shows} == {
        "damai:950252691257:1",
        "damai:950252691257:2",
        "damai:950252691257:3",
    }
    hours = sorted(s.start_time.hour for s in shows)
    assert hours == [15, 17, 19]


def test_split_uses_date_key_when_session_name_contains_other_numbers():
    """dateKey 应覆盖场次名称里的生日/曲目数字，不能误解析成 0520 年。"""
    raw = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="date-key-1",
        title="日期键测试",
        sessions_raw=[
            {
                "id": "p1",
                "name": "2026-07-26 周日(陈粒生日) 16:00，歌曲专题",
                "start_time": "2026-07-26 周日(陈粒生日) 16:00，歌曲专题",
                "date_key": "20260726",
            },
            {
                "id": "p2",
                "name": "7.26周日22:00～打烊，R&B/民谣",
                "start_time": "7.26周日22:00～打烊，R&B/民谣",
                "date_key": "20260726",
            },
        ],
    )

    shows = normalize_items([raw])

    assert len(shows) == 2
    assert [(s.start_time.year, s.start_time.hour) for s in shows] == [
        (2026, 16),
        (2026, 22),
    ]


def test_split_skips_invalid_year_sessions():
    """年份越界（如 0520/2820）的场次视为无效日期被跳过。"""
    raw = _raw_with_sessions(
        "844032523185",
        ["0520-08-01 16:00", "2026-07-26 16:00", "2820-07-01 20:00"],
    )
    shows = normalize_items([raw])
    # 只有 2026-07-26 那条有效
    assert len(shows) == 1
    assert shows[0].id == "damai:844032523185:1"
    assert shows[0].start_time.year == 2026


def test_split_all_invalid_dates_keeps_one_fallback():
    """整条演出所有场次都无有效日期时保留一条兜底，start_time 置 None。"""
    raw = _raw_with_sessions("999", ["0520-08-01 16:00", "2820-07-01 20:00"])
    shows = normalize_items([raw])
    assert len(shows) == 1
    assert shows[0].id == "damai:999:1"
    assert shows[0].start_time is None


def test_split_recomputes_price_per_session():
    """拆分后价格按各自场次的票档重算。"""
    raw = RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id="price-split",
        title="分场价格",
        sessions_raw=[
            {
                "id": "s1",
                "name": "早场",
                "start_time": "2026-08-01 15:00",
                "ticket_tiers": [{"name": "A", "price": 80}, {"name": "B", "price": 180}],
            },
            {
                "id": "s2",
                "name": "晚场",
                "start_time": "2026-08-02 19:30",
                "ticket_tiers": [{"name": "C", "price": 280}, {"name": "D", "price": 580}],
            },
        ],
    )
    shows = normalize_items([raw])
    assert len(shows) == 2
    by_id = {s.id: s for s in shows}
    assert by_id["damai:price-split:1"].price.raw == "80|180"
    assert by_id["damai:price-split:2"].price.raw == "280|580"
