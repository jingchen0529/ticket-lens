"""将各平台 RawShowItem 统一规范化为 Show。"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from app.core.config import PipelineConfig
from app.models import (
    PriceRange,
    RawShowItem,
    Show,
    ShowSession,
    ShowStatus,
    TicketTier,
    Venue,
)
from app.utils.text import clean_poster_url, clean_text, split_artists
from app.utils.timeparse import parse_chinese_datetime, parse_price_range

logger = logging.getLogger(__name__)


_STATUS_MAP: list[tuple[tuple[str, ...], ShowStatus]] = [
    (("售罄", "已售罄", "sold out", "soldout"), ShowStatus.SOLD_OUT),
    (("预售", "即将开售", "pending", "presale"), ShowStatus.PRESALE),
    (("在售", "热卖", "可购", "onsale", "on sale"), ShowStatus.ONSALE),
    (("延期", "delay"), ShowStatus.DELAYED),
    (("取消", "cancel"), ShowStatus.CANCELLED),
    (("结束", "已结束", "ended"), ShowStatus.ENDED),
]


def map_status(raw: str | None) -> ShowStatus:
    text = (raw or "").strip().lower()
    if not text:
        return ShowStatus.UNKNOWN
    for keys, status in _STATUS_MAP:
        if any(k.lower() in text for k in keys):
            return status
    return ShowStatus.UNKNOWN


def _fmt_price_num(p: float) -> str:
    if float(p) == int(p):
        return str(int(p))
    return str(p)


def format_price_ladder(prices: list[float]) -> str:
    """全部票档价格 → `80|180|280`（升序去重）。"""
    if not prices:
        return ""
    uniq = sorted(set(float(p) for p in prices))
    return "|".join(_fmt_price_num(p) for p in uniq)


def build_price_range(
    *,
    tier_prices: list[float],
    price_raw: str,
) -> PriceRange:
    """优先用票档全量价格拼 ladder；否则解析列表摘要区间。"""
    if tier_prices:
        ladder = format_price_ladder(tier_prices)
        return PriceRange(
            min_price=min(tier_prices),
            max_price=max(tier_prices),
            raw=ladder,
        )
    raw = (price_raw or "").strip()
    # 已是 90|180|280 形式
    if "|" in raw and re.search(r"\d", raw):
        nums: list[float] = []
        for part in raw.split("|"):
            part = part.strip().replace("元", "").replace("￥", "").replace("¥", "")
            try:
                nums.append(float(part))
            except ValueError:
                continue
        if nums:
            return PriceRange(
                min_price=min(nums),
                max_price=max(nums),
                raw=format_price_ladder(nums),
            )
    parsed = parse_price_range(price_raw)
    return parsed if parsed.raw or parsed.min_price is not None else PriceRange(raw=price_raw or "")


def normalize_one(raw: RawShowItem) -> Show | None:
    title = clean_text(raw.title)
    source_id = clean_text(raw.source_id)
    if not title:
        return None
    if not source_id:
        # 仍然尝试生成，但 pipeline 可选择丢弃
        source_id = f"unknown-{hash(title) & 0xFFFFFFFF:x}"

    start = parse_chinese_datetime(raw.start_time_raw)
    end = parse_chinese_datetime(raw.end_time_raw)

    rec = raw.raw_payload.get("record") if isinstance(raw.raw_payload, dict) else None
    rec = rec if isinstance(rec, dict) else {}

    artists = list(raw.artists) if raw.artists else []
    if not artists and rec:
        for key in ("actors", "artists", "performer", "artistName"):
            if key in rec and rec[key]:
                artists = split_artists(re.sub(r"^艺人[：:]\s*", "", str(rec[key])))
                break
    detail_blob = raw.raw_payload.get("detail") if isinstance(raw.raw_payload, dict) else None
    detail_blob = detail_blob if isinstance(detail_blob, dict) else {}
    if detail_blob.get("troupe") and detail_blob["troupe"] not in artists:
        artists = [str(detail_blob["troupe"]), *artists]
    for name in detail_blob.get("performers") or []:
        name = clean_text(str(name))
        if name and name not in artists:
            artists.append(name)

    sessions: list[ShowSession] = []
    for s in raw.sessions_raw:
        st = parse_chinese_datetime(
            str(s.get("start_time") or s.get("time") or s.get("showTime") or s.get("name") or "")
        )
        tiers: list[TicketTier] = []
        for t in s.get("ticket_tiers") or s.get("skus") or []:
            if not isinstance(t, dict):
                continue
            tp = t.get("price")
            try:
                price_val = float(tp) if tp is not None and tp != "" else None
            except (TypeError, ValueError):
                price_val = None
            tiers.append(
                TicketTier(
                    sku_id=str(t.get("sku_id") or t.get("skuId") or ""),
                    name=clean_text(str(t.get("name") or t.get("priceName") or "")),
                    price=price_val,
                    status=str(t.get("status") or ""),
                    salable=bool(t.get("salable")),
                    raw=clean_text(str(t.get("raw") or t.get("name") or "")),
                )
            )
        sessions.append(
            ShowSession(
                session_id=str(s.get("id") or s.get("session_id") or s.get("sessionId") or ""),
                name=clean_text(str(s.get("name") or "")),
                start_time=st,
                status=map_status(str(s.get("status") or "")),
                raw_time=str(
                    s.get("start_time") or s.get("time") or s.get("name") or s.get("showTime") or ""
                ),
                ticket_tiers=tiers,
            )
        )

    # 若无场次但有列表时间，补一条主场次
    if not sessions and (start or raw.start_time_raw):
        sessions.append(
            ShowSession(
                start_time=start,
                status=map_status(raw.status_raw),
                raw_time=raw.start_time_raw,
            )
        )

    venue_name = clean_text(raw.venue_name)
    # 大麦有时 venue 带城市前缀「北京 | 工人体育馆」
    if "|" in venue_name:
        parts = [p.strip() for p in venue_name.split("|") if p.strip()]
        if len(parts) >= 2:
            # 若 city 空则取前段
            if not raw.city and re.search(r"市|城", parts[0]) is None and len(parts[0]) <= 6:
                pass
            venue_name = parts[-1]

    city = clean_text(raw.city)
    # 从 venue 文本抽城市
    if not city and venue_name:
        m = re.match(r"^(北京|上海|广州|深圳|成都|杭州|武汉|南京|西安|重庆|天津|苏州|长沙)", venue_name)
        if m:
            city = m.group(1)

    venue_address = clean_text(raw.venue_address)
    if not venue_address and city and venue_name:
        venue_address = f"{city} | {venue_name}"

    # 主时间：优先最早有解析结果的场次
    if sessions:
        timed = [s.start_time for s in sessions if s.start_time is not None]
        if timed:
            start = min(timed)

    # 汇总全部票档价格 → 80|180|280
    tier_prices: list[float] = []
    for s in sessions:
        for t in s.ticket_tiers:
            if t.price is not None:
                tier_prices.append(float(t.price))
    price = build_price_range(tier_prices=tier_prices, price_raw=raw.price_raw)

    show = Show(
        id=Show.make_id(raw.source, source_id),
        source=raw.source,
        source_id=source_id,
        url=raw.url,
        title=title,
        category=clean_text(raw.category),
        artists=artists,
        venue=Venue(
            name=venue_name,
            city=city,
            address=venue_address,
        ),
        price=price,
        status=map_status(raw.status_raw),
        start_time=start,
        end_time=end,
        sessions=sessions,
        poster_url=clean_poster_url(raw.poster_url),
        crawled_at=raw.crawled_at,
        normalized_at=datetime.utcnow(),
        extras={
            "status_raw": raw.status_raw,
            "start_time_raw": raw.start_time_raw,
            "price_raw": price.raw or raw.price_raw,
            "price_ladder": price.raw if "|" in (price.raw or "") else "",
            "from_api": raw.raw_payload.get("from_api"),
            "detail_enriched": bool(detail_blob),
            "session_count": len(sessions),
            "ticket_tier_count": sum(len(s.ticket_tiers) for s in sessions),
            # 演出二级分类：大麦 record.subcategoryname（如 话剧/音乐会/儿童剧）
            "subcategory": clean_text(
                str(rec.get("subcategoryname") or rec.get("subCategoryName") or "")
            ),
            # 详情富化 → 模板列
            "troupe": clean_text(str(detail_blob.get("troupe") or "")),
            "organizer": clean_text(str(detail_blob.get("organizer") or "")),
            "organizers": detail_blob.get("organizers") or [],
            "performers": detail_blob.get("performers") or [],
            "conductor": clean_text(str(detail_blob.get("conductor") or "")),
            "program": clean_text(str(detail_blob.get("program") or "")),
            "norm_venue": clean_text(
                str(detail_blob.get("norm_venue") or venue_name or "")
            ),
            "district": clean_text(str(detail_blob.get("district") or "")),
            "group_city": clean_text(str(detail_blob.get("group_city") or city or "")),
            "organizer_city": clean_text(
                str(detail_blob.get("organizer_city") or city or "")
            ),
            "hk_mo_tw": clean_text(str(detail_blob.get("hk_mo_tw") or "")),
            "holiday": clean_text(str(detail_blob.get("holiday") or "")),
            "troupe_attr": clean_text(str(detail_blob.get("troupe_attr") or "")),
        },
    )
    return show


def normalize_items(
    raw_items: list[RawShowItem],
    config: PipelineConfig | None = None,
) -> list[Show]:
    cfg = config or PipelineConfig()
    shows: list[Show] = []
    dropped = 0

    for raw in raw_items:
        try:
            show = normalize_one(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("normalize failed: %s raw=%s", exc, raw.source_id)
            dropped += 1
            continue

        if show is None:
            dropped += 1
            continue
        if cfg.drop_invalid and (not show.title or not show.source_id):
            dropped += 1
            continue
        shows.append(show)

    if cfg.dedupe:
        seen: set[str] = set()
        unique: list[Show] = []
        for s in shows:
            if s.id in seen:
                continue
            seen.add(s.id)
            unique.append(s)
        shows = unique

    logger.info("normalize: in=%s out=%s dropped=%s", len(raw_items), len(shows), dropped)
    return shows
