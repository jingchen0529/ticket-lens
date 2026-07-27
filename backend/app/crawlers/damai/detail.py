"""大麦详情页：场次 / 票档 / 场馆补全。

列表 searchajax 只有项目摘要；场次与票档在详情 subpage 接口：

  GET https://detail.damai.cn/subpage
    ?itemId=...&apiVersion=2.0&dmChannel=pc@damai_pc
    &bizCode=ali.china.damai&scenario=itemsku
    &dataType=&dataId=          # 默认（当前场次+票档+日历）
    &dataType=4&dataId=YYYYMMDD # 按日期切换场次

响应为 JSONP：__jp0({...})。

在已建立 cookie 的 Playwright page 上用 page.evaluate(fetch) 调用，
避免 headless 直接 goto detail 被 302 到 404。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlencode

from playwright.async_api import Page

from app.models import RawShowItem
from app.utils.text import clean_text

logger = logging.getLogger(__name__)

SUBPAGE_BASE = "https://detail.damai.cn/subpage"
ITEM_PAGE = "https://detail.damai.cn/item.htm"

# 桌面 Chrome UA 兜底。大麦对 subpage / item.htm 会校验 UA：Playwright 的
# context.request 是独立 HTTP 栈，默认 UA（APIRequest/…）或 headless 的
# HeadlessChrome 会被判为非浏览器请求，直接返回裸 "error" 或空 body，导致
# 95% 详情拉取失败、场次全丢。请求必须带一个正常浏览器 UA。
_FALLBACK_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


async def _browser_ua(page: Page) -> str:
    """取当前 page 的真实 UA；剥掉 Headless 标记，取不到则用桌面兜底。"""
    try:
        ua = await page.evaluate("() => navigator.userAgent")
    except Exception:  # noqa: BLE001
        ua = ""
    ua = str(ua or "").strip()
    if not ua:
        return _FALLBACK_UA
    # headless 的 "HeadlessChrome/…" 同样会被识别为非真人浏览器
    return ua.replace("HeadlessChrome", "Chrome")


# 详情介绍里常见「小节标题」
_SECTION_TITLES = (
    "主办",
    "承办",
    "协办",
    "演出团体",
    "艺术家",
    "演员",
    "指挥",
    "演出曲目",
    "曲目",
    "票价",
    "时间",
    "地点",
    "温馨提示",
)

_HK_MO_TW = re.compile(r"香港|澳门|澳門|台湾|台灣|台北|高雄")
# 「北京市西城区…」→ 西城区；「朝阳区…」→ 朝阳区（不含省市字）
_DISTRICT_RE = re.compile(r"((?:(?![省市])[\u4e00-\u9fff]){1,4}(?:区|县))")

_STATUS_TAGS = {
    "缺货登记": "sold_out",
    "售罄": "sold_out",
    "预售": "presale",
    "在售": "onsale",
}


def parse_jsonp(text: str) -> dict[str, Any] | None:
    """解析 __jp0({...}) / callback({...}) / 纯 JSON。"""
    if not text:
        return None
    s = text.strip()
    if s.startswith("{") or s.startswith("["):
        try:
            data = json.loads(s)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    m = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", s, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _build_subpage_url(item_id: str, *, data_id: str = "", data_type: str = "") -> str:
    params = {
        "itemId": str(item_id),
        "apiVersion": "2.0",
        "dmChannel": "pc@damai_pc",
        "bizCode": "ali.china.damai",
        "scenario": "itemsku",
        "dataType": data_type or "",
        "dataId": data_id or "",
        "privilegeActId": "",
    }
    return f"{SUBPAGE_BASE}?{urlencode(params)}"


def _sku_status(sku: dict[str, Any]) -> str:
    tags = sku.get("tags") or []
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, dict):
                desc = str(t.get("tagDesc") or "")
                for k, v in _STATUS_TAGS.items():
                    if k in desc:
                        return v
    other = sku.get("otherTag") if isinstance(sku.get("otherTag"), dict) else {}
    desc = str(other.get("tagDesc") or "")
    for k, v in _STATUS_TAGS.items():
        if k in desc:
            return v
    salable = str(sku.get("skuSalable") or "").lower()
    if salable == "true":
        return "onsale"
    if salable == "false":
        return "sold_out"
    return "unknown"


def _parse_price(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _perform_begin_to_raw(begin: str | None, name: str | None) -> str:
    """202608141900 → 2026-08-14 19:00；优先用 performName。"""
    if name and str(name).strip():
        return str(name).strip()
    s = str(begin or "").strip()
    if len(s) >= 12 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}"
    return s


def _session_from_perform_view(pv: dict[str, Any], skus: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    name = str(pv.get("performName") or pv.get("mainText") or "")
    begin = str(pv.get("performBeginDTStr") or "")
    raw_time = _perform_begin_to_raw(begin, name)
    tiers: list[dict[str, Any]] = []
    for sku in skus or []:
        if not isinstance(sku, dict):
            continue
        # 尝试多个价格字段；大麦不同接口版本字段名不同
        price = _parse_price(
            sku.get("price") or sku.get("salePrice") or sku.get("priceValue")
            or sku.get("skuPrice") or sku.get("dashPrice")
        )
        tiers.append(
            {
                "sku_id": str(sku.get("skuId") or ""),
                "name": clean_text(str(sku.get("priceName") or "")),
                "price": price,
                "status": _sku_status(sku),
                "salable": str(sku.get("skuSalable") or "").lower() == "true",
                "raw": clean_text(str(sku.get("priceName") or ""))
                + (f" {price}元" if price is not None else ""),
            }
        )
    tags = []
    for t in pv.get("tags") or []:
        if isinstance(t, dict) and t.get("tagDesc"):
            tags.append(str(t["tagDesc"]))
    status = "onsale"
    if str(pv.get("salable") or "").lower() == "false":
        status = "sold_out"
    return {
        "id": str(pv.get("performId") or ""),
        "session_id": str(pv.get("performId") or ""),
        "name": name,
        "start_time": raw_time,
        "time": raw_time,
        "showTime": raw_time,
        "status": status,
        "date_key": str(pv.get("dateKey") or ""),
        "tags": tags,
        "ticket_tiers": tiers,
    }


def extract_detail_from_subpage(data: dict[str, Any]) -> dict[str, Any]:
    """从单次 subpage 响应抽取场馆/当前场次/票档/日历日期。"""
    basic = data.get("itemBasicInfo") if isinstance(data.get("itemBasicInfo"), dict) else {}
    perform = data.get("perform") if isinstance(data.get("perform"), dict) else {}
    cal = data.get("performCalendar") if isinstance(data.get("performCalendar"), dict) else {}

    city = clean_text(str(basic.get("cityName") or ""))
    venue_name = clean_text(str(basic.get("venueName") or ""))
    # 详情页展示多为「城市 | 场馆」；无街道地址时用该组合作为 address 展示
    venue_address = ""
    if city and venue_name:
        venue_address = f"{city} | {venue_name}"
    elif venue_name:
        venue_address = venue_name

    price_range = clean_text(str(basic.get("priceRange") or ""))
    title = clean_text(str(basic.get("projectTitle") or basic.get("itemTitle") or ""))

    date_views = cal.get("dateViews") if isinstance(cal.get("dateViews"), list) else []
    date_ids = [
        str(d.get("dateId"))
        for d in date_views
        if isinstance(d, dict) and d.get("dateId") and str(d.get("clickable", "true")).lower() != "false"
    ]

    perform_views = cal.get("performViews") if isinstance(cal.get("performViews"), list) else []
    sku_list = perform.get("skuList") if isinstance(perform.get("skuList"), list) else []
    current_pid = str(perform.get("performId") or cal.get("currentPerformId") or "")

    sessions: list[dict[str, Any]] = []
    for pv in perform_views:
        if not isinstance(pv, dict):
            continue
        pid = str(pv.get("performId") or "")
        skus = sku_list if pid and pid == current_pid else None
        # 若只有一场，直接挂票档
        if skus is None and len(perform_views) == 1:
            skus = sku_list
        sessions.append(_session_from_perform_view(pv, skus))

    # 日历里没有 performViews 时，用当前 perform
    if not sessions and perform.get("performId"):
        sessions.append(
            _session_from_perform_view(
                {
                    "performId": perform.get("performId"),
                    "performName": perform.get("performName"),
                    "performBeginDTStr": perform.get("performBeginDTStr"),
                    "performDateTS": perform.get("performDateTS"),
                    "dateKey": perform.get("dateKey"),
                    "salable": perform.get("performSalable"),
                    "tags": [],
                },
                sku_list,
            )
        )

    return {
        "title": title,
        "city": city,
        "venue_name": venue_name,
        "venue_address": venue_address,
        "price_range": price_range,
        "date_ids": date_ids,
        "sessions": sessions,
        "current_perform_id": current_pid,
        "sku_list_raw": sku_list,
        "basic": basic,
    }


def merge_sessions(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 performId 合并场次；后到的票档非空则覆盖。"""
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for group in groups:
        for s in group:
            sid = str(s.get("id") or s.get("session_id") or s.get("name") or "")
            if not sid:
                continue
            if sid not in by_id:
                by_id[sid] = dict(s)
                order.append(sid)
            else:
                old = by_id[sid]
                new_tiers = s.get("ticket_tiers") or []
                if new_tiers:
                    old["ticket_tiers"] = new_tiers
                for k, v in s.items():
                    if k == "ticket_tiers":
                        continue
                    if v and not old.get(k):
                        old[k] = v
    return [by_id[i] for i in order]


def _html_to_text(raw: str) -> str:
    s = unquote(raw or "")
    s = s.replace("\xa0", " ").replace("\u2003", " ").replace("\u3000", " ")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(?:p|div|li|h\d|tr)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _extract_json_object(html: str, marker: str) -> dict[str, Any] | None:
    """从 HTML 中定位 marker 后的 JSON 对象（花括号配对）。"""
    i = html.find(marker)
    if i < 0:
        return None
    j = html.find("{", i)
    if j < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for k, ch in enumerate(html[j : j + 800_000]):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(html[j : j + k + 1])
                except json.JSONDecodeError:
                    return None
                return data if isinstance(data, dict) else None
    return None


def parse_item_static_html(html: str) -> dict[str, Any]:
    """解析 item.htm 内嵌 staticDataDefault（场馆地址 + 项目介绍）。"""
    data = _extract_json_object(html, 'id="staticDataDefault"')
    if not data:
        data = _extract_json_object(html, "staticDataDefault")
    if not data:
        return {}

    venue = data.get("venue") if isinstance(data.get("venue"), dict) else {}
    item_base = data.get("itemBase") if isinstance(data.get("itemBase"), dict) else {}
    extend_info = data.get("itemExtendInfo") if isinstance(data.get("itemExtendInfo"), dict) else {}
    desc_html = str(extend_info.get("itemExtend") or "")
    desc_text = _html_to_text(desc_html)
    parsed = parse_description_sections(desc_text)

    # 发票开具方常含主办机构
    organizer_from_notes = ""
    for note in item_base.get("serviceNotes") or []:
        if not isinstance(note, dict):
            continue
        tag = str(note.get("tagDesc") or note.get("tagDescWithStyle") or "")
        m = re.search(r"发票开具方[：:]\s*([^\n<]+)", _html_to_text(tag))
        if m:
            organizer_from_notes = clean_text(m.group(1))
            break

    venue_name = clean_text(str(venue.get("venueName") or ""))
    venue_addr = clean_text(str(venue.get("venueAddr") or ""))
    city = clean_text(str(venue.get("venueCityName") or venue.get("venueProvinceName") or ""))
    district = ""
    if venue_addr:
        m = _DISTRICT_RE.search(venue_addr)
        if m:
            district = m.group(1)

    lat = venue.get("lat")
    lng = venue.get("lng")
    try:
        lat_f = float(lat) if lat is not None else None
    except (TypeError, ValueError):
        lat_f = None
    try:
        lng_f = float(lng) if lng is not None else None
    except (TypeError, ValueError):
        lng_f = None

    organizers = list(parsed.get("organizers") or [])
    if organizer_from_notes and organizer_from_notes not in organizers:
        organizers.append(organizer_from_notes)

    return {
        "venue_name": venue_name,
        "venue_address": venue_addr,
        "city": city,
        "district": district,
        "lat": lat_f,
        "lng": lng_f,
        "venue_id": venue.get("venueId"),
        "description": desc_text[:8000],
        "troupe": parsed.get("troupe") or "",
        "conductor": parsed.get("conductor") or "",
        "performers": parsed.get("performers") or [],
        "organizers": organizers,
        "program": parsed.get("program") or "",
        "price_text": parsed.get("price_text") or "",
        "place_text": parsed.get("place_text") or "",
    }


def parse_description_sections(text: str) -> dict[str, Any]:
    """从项目介绍纯文本解析主办/团体/指挥/艺术家/票价/地点。"""
    if not text:
        return {}
    # 统一空白
    t = text.replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()

    def _section(name: str) -> str:
        # 「演出团体\n国家大剧院…」或「主办：xxx」
        pat = rf"(?:^|\n)\s*{re.escape(name)}\s*[：:：]?\s*\n?(.*?)(?=\n\s*(?:{'|'.join(map(re.escape, _SECTION_TITLES))})\s*[：:：]?\s*\n|\Z)"
        m = re.search(pat, "\n" + t, re.S)
        if not m:
            return ""
        body = m.group(1).strip()
        # 只取首段有实质内容的短行，去掉长篇简介
        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
        short: list[str] = []
        for ln in lines:
            # 简介段落通常很长
            if len(ln) > 60 and short:
                break
            if len(ln) > 80:
                continue
            # 跳过「音乐总监：」这类职务行进指挥/艺术家
            short.append(ln)
            if name in ("演出团体", "主办", "承办") and short:
                # 团体/主办通常 1～3 行短名
                if len(short) >= 3:
                    break
        return "\n".join(short).strip()

    troupe = _section("演出团体")
    # 第一行作为团体名
    if troupe:
        troupe = troupe.split("\n")[0].strip()

    organizers: list[str] = []
    for key in ("主办", "承办", "协办"):
        block = _section(key)
        if not block:
            # 同行「主办：A B」
            m = re.search(rf"{key}\s*[：:]\s*([^\n]+)", t)
            if m:
                block = m.group(1)
        if block:
            for part in re.split(r"[\s、,/|]+", block.replace("\n", " ")):
                part = clean_text(part)
                if part and part not in organizers and len(part) <= 40:
                    organizers.append(part)

    conductor = ""
    m = re.search(r"(?:^|\n)\s*指挥\s*[：:]\s*([^\n]{1,40})", t)
    if m:
        conductor = clean_text(m.group(1))
    else:
        block = _section("指挥")
        if block:
            conductor = block.split("\n")[0].strip()

    performers: list[str] = []
    if conductor:
        performers.append(conductor)
    # 艺术家小节：第一行短名
    art_block = _section("艺术家") or _section("演员")
    if art_block:
        first = art_block.split("\n")[0].strip()
        if first and first not in performers and len(first) <= 40:
            performers.append(first)
    # 曲目里的「女高音：李晶晶」
    for m in re.finditer(
        r"(?:指挥|女高音|男高音|钢琴|小提琴|中提琴|大提琴|独唱|演奏)[：:]\s*([^\n，,]{1,20})",
        t,
    ):
        name = clean_text(m.group(1))
        if name and name not in performers and len(name) <= 20:
            performers.append(name)

    program = _section("曲目") or _section("演出曲目")
    if program and len(program) > 500:
        program = program[:500]

    price_text = ""
    m = re.search(r"票价\s*[：:]\s*([^\n]+)", t)
    if m:
        price_text = clean_text(m.group(1))

    place_text = ""
    m = re.search(r"地点\s*[：:]\s*([^\n]+)", t)
    if m:
        place_text = clean_text(m.group(1))

    return {
        "troupe": troupe,
        "organizers": organizers,
        "conductor": conductor,
        "performers": performers,
        "program": program,
        "price_text": price_text,
        "place_text": place_text,
    }


def parse_price_text_to_ladder(price_text: str) -> str:
    """把「80 / 180 / 280 / VIP 680」→ `80|180|280|680`。"""
    if not price_text:
        return ""
    nums: list[float] = []
    for m in re.finditer(r"(?:VIP\s*)?(\d+(?:\.\d+)?)", price_text, re.I):
        try:
            nums.append(float(m.group(1)))
        except ValueError:
            continue
    if not nums:
        return ""
    uniq = sorted(set(nums))
    return "|".join(str(int(p)) if p == int(p) else str(p) for p in uniq)


def _district_from_address(addr: str) -> str:
    if not addr:
        return ""
    m = _DISTRICT_RE.search(addr)
    return m.group(1) if m else ""


def _is_hk_mo_tw(*parts: str) -> str:
    blob = " ".join(p for p in parts if p)
    return "是" if _HK_MO_TW.search(blob) else "否"


def apply_detail_to_raw(item: RawShowItem, detail: dict[str, Any]) -> RawShowItem:
    """把详情结果写回 RawShowItem（sessions / 场馆 / 票价 / 主办演员等）。"""
    sessions = detail.get("sessions") or []
    if sessions:
        item.sessions_raw = sessions

    if detail.get("venue_name"):
        item.venue_name = detail["venue_name"]
    # 优先真实街道地址
    if detail.get("venue_address"):
        item.venue_address = detail["venue_address"]
    elif detail.get("place_text"):
        item.venue_address = detail["place_text"]
    if detail.get("city") and not item.city:
        item.city = detail["city"]

    # 全部票档价格升序去重 → 80|180|280
    prices: list[float] = []
    for s in sessions:
        for t in s.get("ticket_tiers") or []:
            p = t.get("price")
            if isinstance(p, (int, float)):
                prices.append(float(p))
    if prices:
        uniq = sorted(set(prices))
        item.price_raw = "|".join(
            str(int(p)) if float(p) == int(p) else str(p) for p in uniq
        )
    else:
        ladder = parse_price_text_to_ladder(str(detail.get("price_text") or ""))
        if ladder:
            item.price_raw = ladder
        else:
            pr = detail.get("price_range") or ""
            if pr:
                item.price_raw = pr.replace("￥", "").replace(" ", "")

    # 主时间
    if sessions and not item.start_time_raw:
        item.start_time_raw = str(sessions[0].get("start_time") or sessions[0].get("name") or "")

    # 艺术家 / 团体
    artists: list[str] = []
    troupe = clean_text(str(detail.get("troupe") or ""))
    if troupe:
        artists.append(troupe)
    for name in detail.get("performers") or []:
        name = clean_text(str(name))
        if name and name not in artists:
            artists.append(name)
    # 列表 actors 兜底
    if not artists and item.artists:
        artists = list(item.artists)
    if artists:
        item.artists = artists

    organizers = [clean_text(str(x)) for x in (detail.get("organizers") or []) if clean_text(str(x))]
    district = clean_text(str(detail.get("district") or "")) or _district_from_address(
        item.venue_address
    )
    city = clean_text(item.city or str(detail.get("city") or ""))

    payload = dict(item.raw_payload or {})
    payload["detail"] = {
        "venue_name": detail.get("venue_name") or item.venue_name,
        "venue_address": item.venue_address,
        "city": city,
        "district": district,
        "lat": detail.get("lat"),
        "lng": detail.get("lng"),
        "price_range": detail.get("price_range"),
        "session_count": len(sessions),
        "troupe": troupe,
        "organizer": "、".join(organizers),
        "organizers": organizers,
        "performers": [clean_text(str(x)) for x in (detail.get("performers") or []) if x],
        "conductor": clean_text(str(detail.get("conductor") or "")),
        "program": clean_text(str(detail.get("program") or ""))[:800],
        "place_text": clean_text(str(detail.get("place_text") or "")),
        # 模板列可直接用的富化字段
        "norm_venue": detail.get("venue_name") or item.venue_name,
        "group_city": city,
        "organizer_city": city,
        "hk_mo_tw": _is_hk_mo_tw(city, item.title, item.venue_name),
        "enriched_at": datetime.utcnow().isoformat() + "Z",
    }
    item.raw_payload = payload
    return item


async def fetch_subpage(
    page: Page,
    item_id: str,
    *,
    data_id: str = "",
    data_type: str = "",
    timeout_ms: int = 15000,
) -> dict[str, Any] | None:
    """用 Playwright request（带 cookie、无 CORS）拉 subpage 并解析 JSONP。

    不用 page.evaluate(fetch)：从 search.damai.cn 调 detail.damai.cn 会被浏览器 CORS 拦截。
    """
    url = _build_subpage_url(item_id, data_id=data_id, data_type=data_type)
    text = ""
    ua = await _browser_ua(page)
    try:
        # context.request 继承 storage_state cookies
        req = page.context.request
        resp = await req.get(
            url,
            timeout=timeout_ms,
            headers={
                "accept": "*/*",
                "referer": f"https://detail.damai.cn/item.htm?id={item_id}",
                "x-requested-with": "XMLHttpRequest",
                "user-agent": ua,
            },
        )
        if not resp.ok:
            logger.warning(
                "subpage http %s item=%s dataId=%s", resp.status, item_id, data_id or "-"
            )
            return None
        text = await resp.text()
    except Exception as exc:  # noqa: BLE001
        # 回退：页内 fetch（若当前已在 detail 域）
        logger.debug("subpage request failed, try page fetch: %s", exc)
        try:
            text = await asyncio.wait_for(
                page.evaluate(
                    """async ({ url, timeoutMs }) => {
                      const ctrl = new AbortController();
                      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
                      try {
                        const r = await fetch(url, {
                          credentials: 'include',
                          signal: ctrl.signal,
                          headers: { accept: '*/*' },
                        });
                        return await r.text();
                      } catch (e) {
                        return '';
                      } finally {
                        clearTimeout(timer);
                      }
                    }""",
                    {"url": url, "timeoutMs": int(timeout_ms)},
                ),
                timeout=max(5.0, timeout_ms / 1000.0 + 3.0),
            )
        except Exception as exc2:  # noqa: BLE001
            logger.warning("subpage fetch failed item=%s: %s", item_id, exc2)
            return None

    if not text:
        return None
    data = parse_jsonp(text)
    if not data:
        logger.warning("subpage parse failed item=%s head=%s", item_id, text[:80])
        return None
    resp_info = data.get("responseInfo") if isinstance(data.get("responseInfo"), dict) else {}
    if resp_info and str(resp_info.get("responseSuccess", "true")).lower() == "false":
        logger.warning(
            "subpage response fail item=%s code=%s", item_id, resp_info.get("responseCode")
        )
        return None
    return data


async def fetch_item_static(
    page: Page,
    item_id: str,
    *,
    timeout_ms: int = 20000,
) -> dict[str, Any]:
    """GET item.htm，解析 staticDataDefault（场馆地址 + 项目介绍）。"""
    url = f"{ITEM_PAGE}?id={item_id}"
    ua = await _browser_ua(page)
    try:
        resp = await page.context.request.get(
            url,
            timeout=timeout_ms,
            headers={
                "accept": "text/html,application/xhtml+xml",
                "referer": "https://search.damai.cn/",
                "user-agent": ua,
            },
        )
        if not resp.ok:
            logger.warning("item.htm http %s item=%s", resp.status, item_id)
            return {}
        html = await resp.text()
    except Exception as exc:  # noqa: BLE001
        logger.warning("item.htm fetch failed item=%s: %s", item_id, exc)
        return {}
    return parse_item_static_html(html)


async def enrich_item_detail(
    page: Page,
    item: RawShowItem,
    *,
    fetch_all_dates: bool = True,
    date_limit: int = 40,
    delay_s: float = 0.25,
) -> RawShowItem:
    """拉取详情并写回 item。失败时原样返回。"""
    item_id = (item.source_id or "").strip()
    if not item_id or not item_id.isdigit():
        # 尝试从 url 抠 id
        m = re.search(r"[?&]id=(\d+)", item.url or "")
        item_id = m.group(1) if m else ""
    if not item_id:
        return item

    # 1) subpage：场次 + 票档
    detail: dict[str, Any] = {}
    base = await fetch_subpage(page, item_id)
    if base:
        detail = extract_detail_from_subpage(base)
        all_sessions = list(detail.get("sessions") or [])

        date_ids = list(detail.get("date_ids") or [])
        if fetch_all_dates and date_ids:
            seen_dates = {
                str(s.get("date_key") or "") for s in all_sessions if s.get("date_key")
            }
            for date_id in date_ids[: max(1, date_limit)]:
                if date_id in seen_dates:
                    continue
                if delay_s > 0:
                    await asyncio.sleep(delay_s)
                day = await fetch_subpage(page, item_id, data_id=date_id, data_type="4")
                if not day:
                    continue
                day_detail = extract_detail_from_subpage(day)
                all_sessions = merge_sessions(all_sessions, day_detail.get("sessions") or [])
                seen_dates.add(date_id)

        by_date: dict[str, list[dict[str, Any]]] = {}
        for s in all_sessions:
            by_date.setdefault(str(s.get("date_key") or ""), []).append(s)
        for _dk, group in by_date.items():
            donor = next((x for x in group if x.get("ticket_tiers")), None)
            if not donor:
                continue
            for s in group:
                if not s.get("ticket_tiers"):
                    s["ticket_tiers"] = list(donor.get("ticket_tiers") or [])

        detail["sessions"] = all_sessions

    # 2) item.htm staticData：真实地址 + 主办/团体/艺术家介绍
    if delay_s > 0:
        await asyncio.sleep(min(delay_s, 0.2))
    static = await fetch_item_static(page, item_id)
    if static:
        # static 的街道地址优先于 subpage 的「城市|场馆」
        for k in (
            "venue_name",
            "venue_address",
            "city",
            "district",
            "lat",
            "lng",
            "troupe",
            "conductor",
            "performers",
            "organizers",
            "program",
            "price_text",
            "place_text",
        ):
            if static.get(k) not in (None, "", []):
                detail[k] = static[k]

    if not detail:
        return item

    logger.info(
        "damai detail item=%s venue=%s addr=%s sessions=%s troupe=%s organizers=%s",
        item_id,
        detail.get("venue_name"),
        (detail.get("venue_address") or "")[:40],
        len(detail.get("sessions") or []),
        detail.get("troupe") or "",
        detail.get("organizers") or [],
    )
    return apply_detail_to_raw(item, detail)


async def enrich_items_detail(
    page: Page,
    items: list[RawShowItem],
    *,
    delay_s: float = 0.35,
    fetch_all_dates: bool = True,
    date_limit: int = 40,
) -> list[RawShowItem]:
    """批量补全详情；逐条串行，降低风控。"""
    out: list[RawShowItem] = []
    total = len(items)
    for idx, item in enumerate(items, 1):
        try:
            enriched = await enrich_item_detail(
                page,
                item,
                fetch_all_dates=fetch_all_dates,
                date_limit=date_limit,
                delay_s=min(delay_s, 0.2),
            )
            out.append(enriched)
            if idx == 1 or idx == total or idx % 10 == 0:
                logger.info("damai detail progress %s/%s id=%s", idx, total, item.source_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("damai detail enrich error id=%s: %s", item.source_id, exc)
            out.append(item)
        if delay_s > 0 and idx < total:
            await asyncio.sleep(delay_s)
    return out
