"""导出清洗后的数据为 CSV / Excel。

表头严格对齐《北京市演出信息》模板（37 列，含带换行注释的表头），
以便直接并入下游台账。能从 Show 推导的列自动填充，人工标注/富化列
（规范剧场、场馆座位数、主办方、演艺之都分类等）留空待补。
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

# --- 模板表头（顺序即列顺序，字符串须与模板逐字一致，含换行注释）---
# 每项 (internal_key, 模板表头)；internal_key 为空串表示该列无数据、留空。
COLUMNS: list[tuple[str, str]] = [
    ("id", "id"),
    ("seq", "序号"),
    ("city", "城市"),
    ("venue_name", "原始剧场"),
    ("", "规范剧场"),
    ("", "场馆综合体"),
    ("", "场馆座位数"),
    ("", "所在区"),
    ("", "场馆类型\n（新标准）"),
    ("", "区号"),
    ("", "演艺集聚区"),
    ("title", "原名称"),
    ("", "规范剧目名称"),
    ("start_time", "演出时间"),
    ("year", "年份"),
    ("month", "月份"),
    ("quarter", "季度"),
    ("day", "日"),
    ("weekday", "星期"),
    ("", "节假日"),
    ("artists", "演出团体"),
    ("", "团体城市"),
    ("", "港澳台"),
    ("", "主办方名称"),
    ("", "主办方城市"),
    ("category", "演出大类"),
    ("", "演出二级分类"),
    ("", "演出三级分类"),
    ("", "演艺之都分类"),
    ("", "类型顺序"),
    ("sessions", "场次\n（筛选的时候注意0为取消的演出）"),
    (
        "status",
        "状态\n1. 状态为2的信息是对的信息 只是节庆文旅局不想对外，周报数据依旧统计；\n2. 状态3是有问题的数据",
    ),
    ("", "院团属性"),
    ("", "演员"),
    ("price", "规范价格"),
    ("url", "url"),
]

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# Show.status → 模板中文状态（onsale/unknown 按模板惯例留空）
_STATUS_ZH = {
    "cancelled": "取消",
    "sold_out": "售罄",
    "ended": "已结束",
    "delayed": "延期",
    "presale": "预售",
    "onsale": "",
    "unknown": "",
}


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


def _price(show: dict[str, Any]) -> str:
    """规范价格：优先原始文案，其次 min|max。"""
    price = show.get("price") or {}
    raw = (price.get("raw") or "").strip()
    if raw:
        return raw
    lo, hi = price.get("min_price"), price.get("max_price")
    parts = [str(int(p)) if isinstance(p, (int, float)) and p == int(p) else str(p)
             for p in (lo, hi) if p is not None]
    return "|".join(parts)


def _flatten(show: dict[str, Any], seq: int) -> dict[str, Any]:
    """把一条 Show 拍平成模板行（按 internal_key 取值）。"""
    venue = show.get("venue") or {}
    artists = show.get("artists") or []
    sessions = show.get("sessions") or []
    dt = _parse_dt(show.get("start_time"))
    status = str(show.get("status") or "").lower()

    return {
        "id": show.get("id", ""),
        "seq": seq,
        "city": venue.get("city", ""),
        "venue_name": venue.get("name", ""),
        "title": show.get("title", ""),
        "start_time": dt,
        "year": dt.year if dt else "",
        "month": dt.month if dt else "",
        "quarter": f"Q{(dt.month - 1) // 3 + 1}" if dt else "",
        "day": dt.day if dt else "",
        "weekday": _WEEKDAYS[dt.weekday()] if dt else "",
        "artists": " / ".join(artists) if isinstance(artists, list) else str(artists),
        "category": show.get("category", ""),
        "sessions": len(sessions),
        "status": _STATUS_ZH.get(status, ""),
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
