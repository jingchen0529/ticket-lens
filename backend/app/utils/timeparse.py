"""时间与价格解析（中文票务页面常见格式）。"""

from __future__ import annotations

import re
from datetime import datetime

from dateutil import parser as date_parser

from app.models import PriceRange


_PRICE_RE = re.compile(
    r"(?P<min>\d+(?:\.\d+)?)\s*[-~至到]\s*(?P<max>\d+(?:\.\d+)?)"
    r"|(?P<single>\d+(?:\.\d+)?)\s*元?"
)

# 大麦列表常见「2026.07.18-2026.07.20」「2026.01.01-12.31」
# fuzzy dateutil 会把后半段误判成时区，offset 越界直接抛错。
_DATE_RANGE_RE = re.compile(
    r"^(?P<start>\d{4}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)"
    r"\s*[-~～至到]\s*"
    r"(?:\d{4}-)?\d{1,2}-\d{1,2}"
)

# 同日时段「19:30-21:30」只保留起点
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2}:\d{2}(?::\d{2})?)\s*[-~～至到]\s*\d{1,2}:\d{2}(?::\d{2})?"
)


def parse_price_range(raw: str | None) -> PriceRange:
    text = (raw or "").strip()
    if not text or "待定" in text or "票价" in text and "元" not in text and not re.search(r"\d", text):
        return PriceRange(raw=text)

    m = _PRICE_RE.search(text.replace(",", "").replace("￥", "").replace("¥", ""))
    if not m:
        return PriceRange(raw=text)

    if m.group("min") and m.group("max"):
        return PriceRange(
            min_price=float(m.group("min")),
            max_price=float(m.group("max")),
            raw=text,
        )
    if m.group("single"):
        val = float(m.group("single"))
        return PriceRange(min_price=val, max_price=val, raw=text)
    return PriceRange(raw=text)


def _strip_tz(dt: datetime) -> datetime:
    """演出时间一律按本地墙钟 naive 存，丢掉 fuzzy 解析出的假时区。"""
    if dt.tzinfo is None:
        return dt
    try:
        return dt.replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return datetime(
            dt.year,
            dt.month,
            dt.day,
            dt.hour,
            dt.minute,
            dt.second,
            dt.microsecond,
        )


def parse_chinese_datetime(raw: str | None) -> datetime | None:
    """尽力解析中文时间字符串。

    支持示例：
    - 2026.07.18 19:30
    - 2026-07-18 19:30:00
    - 7月18日 19:30
    - 2026/07/18
    - 2026.07.18-2026.07.20（取起始日）
    - 2026.01.01-12.31（取起始日）
    - 2026.07.18 19:30-21:30（取起始时刻）
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    if "待定" in text and not re.search(r"\d{4}", text):
        return None

    # 归一化中文月日与分隔符
    text = text.replace("年", "-").replace("月", "-").replace("日", " ")
    text = text.replace(".", "-").replace("/", "-")
    text = re.sub(r"\s+", " ", text).strip()

    # 去掉「周x」
    text = re.sub(r"周[一二三四五六日天]", "", text).strip()

    # 日期区间：只保留起点，避免 dateutil 把「-12.31」吃成非法 tz offset
    m = _DATE_RANGE_RE.match(text)
    if m:
        text = m.group("start").strip()
    else:
        text = _TIME_RANGE_RE.sub(r"\1", text, count=1).strip()

    try:
        dt = date_parser.parse(
            text,
            fuzzy=True,
            default=datetime(datetime.now().year, 1, 1),
        )
    except (ValueError, OverflowError, TypeError):
        return None

    if dt is None:
        return None
    return _strip_tz(dt)
