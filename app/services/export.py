"""导出清洗后的数据为 CSV / Excel。

表头严格对齐《北京市演出信息》模板（36 列，含带换行注释的表头），
以便直接并入下游台账。能从 Show / 详情富化推导的列自动填充；
场馆综合体 / 座位数 / 区号 / 演艺之都分类等仍依赖外部主数据的列留空。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any

from app.utils.holiday import holiday_label
from app.utils.showstate import performance_status

# --- 模板表头（顺序即列顺序，字符串须与模板逐字一致，含换行注释）---
# 每项 (internal_key, 模板表头)；internal_key 为空串表示该列暂无数据、留空待补。
COLUMNS: list[tuple[str, str]] = [
    ("id", "id"),
    ("seq", "序号"),
    ("city", "城市"),
    ("venue_name", "原始剧场"),
    ("norm_venue", "规范剧场"),
    ("", "场馆综合体"),
    ("", "场馆座位数"),
    ("district", "所在区"),
    ("", "场馆类型\n（新标准）"),
    ("", "区号"),
    ("", "演艺集聚区"),
    ("title", "原名称"),
    ("norm_title", "规范剧目名称"),
    ("start_time", "演出时间"),
    ("year", "年份"),
    ("month", "月份"),
    ("quarter", "季度"),
    ("day", "日"),
    ("weekday", "星期"),
    ("holiday", "节假日"),
    ("troupe", "演出团体"),
    ("group_city", "团体城市"),
    ("hk_mo_tw", "港澳台"),
    ("organizer", "主办方名称"),
    ("organizer_city", "主办方城市"),
    ("category", "演出大类"),
    ("subcategory", "演出二级分类"),
    ("", "演出三级分类"),
    ("", "演艺之都分类"),
    ("", "类型顺序"),
    ("sessions", "场次\n（筛选的时候注意0为取消的演出）"),
    (
        "status",
        "状态\n1. 状态为2的信息是对的信息 只是节庆文旅局不想对外，周报数据依旧统计；\n2. 状态3是有问题的数据",
    ),
    ("troupe_attr", "院团属性"),
    ("performers", "演员"),
    ("price", "规范价格"),
    ("url", "url"),
]

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 「《冰雪女王1-爱的力量》」——从含前后缀的原名称里抠出书名号剧目名
_TITLE_RE = re.compile(r"《[^《》]+》")


def _parse_dt(value: Any) -> datetime | None:
    """把 Show.start_time（ISO 字符串）解析成 datetime。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    # 去掉时区，Excel 单元格用 naive datetime
    return dt.replace(tzinfo=None)


def _norm_title(title: str) -> str:
    """规范剧目名称：取原名称里第一处《…》，无书名号则留空待人工规范。"""
    m = _TITLE_RE.search(title or "")
    return m.group(0) if m else ""


def _fmt_price(val: Any) -> str:
    """价格数值格式化：整数去掉小数点。"""
    if isinstance(val, (int, float)) and val == int(val):
        return str(int(val))
    return str(val)


def _price(show: dict[str, Any]) -> str:
    """规范价格：汇总各票档的去重价格，升序拼成 `90|180|280`。

    无票档时回退票价区间 min|max，再回退原始文案。
    """
    prices: list[float] = []
    for s in show.get("sessions") or []:
        for t in s.get("ticket_tiers") or []:
            p = t.get("price")
            if isinstance(p, (int, float)):
                prices.append(float(p))
    if prices:
        uniq = sorted(set(prices))
        return "|".join(_fmt_price(p) for p in uniq)

    price = show.get("price") or {}
    lo, hi = price.get("min_price"), price.get("max_price")
    parts = [_fmt_price(p) for p in (lo, hi) if p is not None]
    # min==max 时只留一个
    parts = list(dict.fromkeys(parts))
    if parts:
        return "|".join(parts)
    return (price.get("raw") or "").strip()


def _flatten(show: dict[str, Any], seq: int) -> dict[str, Any]:
    """把一条 Show 拍平成模板行（按 internal_key 取值）。"""
    venue = show.get("venue") or {}
    artists = show.get("artists") or []
    sessions = show.get("sessions") or []
    extras = show.get("extras") or {}
    dt = _parse_dt(show.get("start_time"))
    status = str(show.get("status") or "").lower()

    troupe = str(extras.get("troupe") or "").strip()
    if not troupe and isinstance(artists, list) and artists:
        troupe = str(artists[0])
    performers = extras.get("performers") or []
    if isinstance(performers, list):
        performers_s = "、".join(str(x) for x in performers if x)
    else:
        performers_s = str(performers or "")
    if not performers_s and isinstance(artists, list):
        performers_s = "、".join(str(x) for x in artists if x)

    city = venue.get("city", "") or ""

    return {
        "id": show.get("id", ""),
        "seq": seq,
        "city": city,
        "venue_name": venue.get("name", ""),
        "norm_venue": extras.get("norm_venue") or venue.get("name", ""),
        "district": extras.get("district") or "",
        "title": show.get("title", ""),
        "norm_title": _norm_title(show.get("title", "")),
        "start_time": dt,
        "year": dt.year if dt else "",
        "month": dt.month if dt else "",
        "quarter": f"Q{(dt.month - 1) // 3 + 1}" if dt else "",
        "day": dt.day if dt else "",
        "weekday": _WEEKDAYS[dt.weekday()] if dt else "",
        "holiday": holiday_label(dt) if dt else (extras.get("holiday") or ""),
        "troupe": troupe,
        "group_city": extras.get("group_city") or city,
        "hk_mo_tw": extras.get("hk_mo_tw") or "",
        "organizer": extras.get("organizer") or "",
        "organizer_city": extras.get("organizer_city") or city,
        "artists": " / ".join(artists) if isinstance(artists, list) else str(artists),
        "performers": performers_s,
        "category": show.get("category", ""),
        "subcategory": extras.get("subcategory", "") or "",
        "sessions": len(sessions),
        "status": performance_status(dt, raw_status=status),
        "troupe_attr": extras.get("troupe_attr") or "",
        "price": _price(show),
        "url": show.get("url", ""),
    }


def _cell(row: dict[str, Any], key: str, *, as_text: bool) -> Any:
    """取一列的值；空 key 或缺失 → 空串。as_text 时 datetime 转字符串。"""
    if not key:
        return ""
    val = row.get(key, "")
    if val is None:
        return ""
    if as_text and isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return val


def to_csv(shows: list[dict[str, Any]]) -> bytes:
    """导出 CSV。带 UTF-8 BOM，Excel 直接打开中文不乱码。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([header for _, header in COLUMNS])
    for i, show in enumerate(shows, start=1):
        row = _flatten(show, i)
        writer.writerow([_cell(row, key, as_text=True) for key, _ in COLUMNS])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def to_xlsx(shows: list[dict[str, Any]]) -> bytes:
    """导出 Excel（.xlsx）。演出时间写为真正的日期单元格。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "演出数据"
    ws.append([header for _, header in COLUMNS])
    for i, show in enumerate(shows, start=1):
        row = _flatten(show, i)
        ws.append([_cell(row, key, as_text=False) for key, _ in COLUMNS])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
