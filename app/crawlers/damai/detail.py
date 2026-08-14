"""大麦详情页：场次 / 票档 / 场馆补全。

列表 searchajax 只有项目摘要；常规场次与票档在详情 subpage 接口：

  GET https://detail.damai.cn/subpage
    ?itemId=...&apiVersion=2.0&dmChannel=pc@damai_pc
    &bizCode=ali.china.damai&scenario=itemsku
    &dataType=&dataId=          # 默认（当前场次+票档+日历）
    &dataType=4&dataId=YYYYMMDD # 按日期切换场次

响应为 JSONP：__jp0({...})。

仅当 PC 详情已完整、语义校验通过，并确认票档/价格区间/价格文字均无
可用价格时，才切换官方移动端 ``m.damai.cn`` 对应的 MTop 详情协议。
网络、HTTP、HTML、登录页、跨域、风控或语义失败都不得触发移动端降级。

在已建立 cookie 的 Playwright page 上用 BrowserContext.request 调用，
避免 headless 直接 goto detail 被 302 到 404，也不依赖页面 JS 上下文。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode, urljoin, urlparse

from playwright.async_api import Page

from app.crawlers.damai.mobile_detail import (
    fetch_mobile_item_detail,
    mobile_detail_url,
)
from app.models import RawShowItem
from app.utils.text import clean_text

logger = logging.getLogger(__name__)


class DetailCompletenessError(RuntimeError):
    """详情重试耗尽后仍不完整；调用方不得把该项目当成功入库。"""


class PcDetailRetryableError(RuntimeError):
    """PC 详情通道临时不可用；只能原请求恢复，禁止移动端降级。"""

    def __init__(
        self,
        *,
        item_id: str,
        reason: str,
        data_type: str = "",
        data_id: str = "",
        status: int = 0,
        content_type: str = "",
        response_url: str = "",
        body_chars: int = 0,
    ) -> None:
        self.item_id = str(item_id)
        self.reason = str(reason or "unknown")
        self.data_type = str(data_type or "")
        self.data_id = str(data_id or "")
        self.status = int(status or 0)
        self.content_type = str(content_type or "")
        self.response_url = str(response_url or "")
        self.body_chars = int(body_chars or 0)
        super().__init__(
            "大麦 PC 详情通道暂时不可用 "
            f"reason={self.reason} item={self.item_id} "
            f"dataType={self.data_type or '-'} dataId={self.data_id or '-'}"
        )

    def checkpoint_fields(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "reason": self.reason,
            "data_type": self.data_type,
            "data_id": self.data_id,
            "http_status": self.status,
            "content_type": self.content_type,
            "response_url": self.response_url,
            "body_chars": self.body_chars,
        }


class PcDetailSemanticError(DetailCompletenessError):
    """PC 返回可解析响应，但项目或场次语义不匹配；禁止移动端降级。"""


class PcDetailNoPriceError(DetailCompletenessError):
    """PC 详情完整且明确没有价格；这是唯一允许移动端降级的信号。"""


class PcDetailAppOnlyError(PcDetailNoPriceError):
    """PC 项目正常存在但明确仅支持 App 购买；允许移动端补全。"""


class BixiPunishError(PcDetailRetryableError):
    """PC 详情接口返回了 bixi ``action=deny`` 风控引导页。"""

    def __init__(
        self,
        *,
        item_id: str,
        data_type: str = "",
        data_id: str = "",
        status: int = 0,
        content_type: str = "",
        response_url: str = "",
        body_chars: int = 0,
    ) -> None:
        super().__init__(
            item_id=item_id,
            reason="bixi",
            data_type=data_type,
            data_id=data_id,
            status=status,
            content_type=content_type,
            response_url=response_url,
            body_chars=body_chars,
        )


class PcDetailCircuitOpenError(RuntimeError):
    """PC 通道冷却恢复已耗尽；停止本批详情，且不得移动端降级。"""


def is_bixi_punish(body: str, content_type: str = "", response_url: str = "") -> bool:
    """只识别 bixi 强特征，避免把普通 HTML/业务空壳误判为风控。"""
    text = str(body or "")
    lower = text.lower()
    url_lower = str(response_url or "").lower()
    if "bixi.alicdn.com/punish" in lower or "bixi.alicdn.com/punish" in url_lower:
        return True
    if "rgv587_flag:sm" in lower:
        return True
    html_like = (
        "text/html" in str(content_type or "").lower()
        or "<html" in lower
        or "<script" in lower
    )
    return bool(
        html_like
        and "action=deny" in lower
        and ("x5secdata" in lower or "window._config_" in lower or "/punish" in lower)
    )


def _response_host(url: str) -> str:
    try:
        return str(urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def _is_unexpected_detail_url(url: str) -> bool:
    host = _response_host(url)
    return bool(host and host != "detail.damai.cn")


def _is_login_or_challenge_html(body: str) -> bool:
    """识别详情 HTML 中足够强的登录/安全页特征。"""
    lower = str(body or "").lower()
    if "bixi.alicdn.com/punish" in lower or "rgv587_flag:sm" in lower:
        return True

    title_match = re.search(r"<title\b[^>]*>(.*?)</title>", lower, re.I | re.S)
    title = clean_text(title_match.group(1)) if title_match else ""
    if "登录" in title and any(name in title for name in ("淘宝", "大麦", "天猫")):
        return True

    # 正常大麦详情的导航和埋点脚本也会包含 passport/login.taobao.com；
    # 只有真实密码输入框与登录表单同时出现时，才把同域 HTML 判成登录页。
    has_password_input = bool(
        re.search(
            r"<input\b[^>]*\btype\s*=\s*['\"]?password\b",
            lower,
            re.I,
        )
    )
    has_login_form = bool(
        re.search(
            r"<(?:form|div|section)\b[^>]*(?:id|class)\s*=\s*['\"][^'\"]*"
            r"(?:login[-_ ]?(?:form|box)|j_loginbox)[^'\"]*['\"]",
            lower,
            re.I,
        )
    )
    return has_password_input and has_login_form


def _item_error_shell_reason(body: str) -> str:
    """识别同域 HTTP 200 的 404/错误壳，避免把失败页面当作正常无价。"""
    lower = str(body or "").lower()
    title_match = re.search(r"<title\b[^>]*>(.*?)</title>", lower, re.I | re.S)
    title = clean_text(title_match.group(1)) if title_match else ""
    if re.search(r"(?:大麦网\s*)?404\s*$", title, re.I):
        return "http_200_404_shell"
    if any(
        marker in title
        for marker in (
            "页面不存在",
            "项目不存在",
            "项目已下架",
            "访问出错",
            "页面出错",
            "系统维护",
            "服务异常",
        )
    ):
        return "http_200_error_shell"
    return ""


class _SubpageCircuitBreaker:
    """一次详情批次共享的 PC 通道熔断器；始终原地重放失败请求。"""

    def __init__(
        self,
        *,
        cooldown_min_s: float = 105.0,
        cooldown_max_s: float = 135.0,
        retry_cooldown_min_s: float = 240.0,
        retry_cooldown_max_s: float = 360.0,
        max_cooldowns: int = 2,
        checkpoint_path: str | Path | None = None,
    ) -> None:
        first = sorted((max(0.0, float(cooldown_min_s)), max(0.0, float(cooldown_max_s))))
        second = sorted(
            (
                max(0.0, float(retry_cooldown_min_s)),
                max(0.0, float(retry_cooldown_max_s)),
            )
        )
        self._cooldowns = (tuple(first), tuple(second))
        self._max_cooldowns = max(0, int(max_cooldowns))
        self._checkpoint_path = Path(checkpoint_path) if checkpoint_path else None
        self._batch_id = uuid.uuid4().hex
        self._round = 0
        self._item_index = 0
        self._total_items = 0
        self._pending_items: list[RawShowItem] = []
        self._checkpoint_active = False
        self._checkpoint_item_id = ""
        self._last_error: PcDetailRetryableError | None = None
        self._last_request_label = ""

    def set_batch_progress(
        self,
        item_index: int,
        items: list[RawShowItem],
    ) -> None:
        """记录当前项目和待处理列表；只在真正触发风控时写盘。"""
        self._item_index = max(1, int(item_index))
        self._total_items = len(items)
        self._pending_items = list(items[self._item_index - 1 :])

    def _checkpoint_payload(
        self,
        *,
        state: str,
        error: PcDetailRetryableError,
        request_label: str,
        resume_at: datetime | None,
    ) -> dict[str, Any]:
        return {
            "version": 1,
            "source": "damai",
            "batch_id": self._batch_id,
            "state": state,
            "strategy": "restart_current_item_from_base",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "resume_after": resume_at.isoformat() if resume_at else None,
            "cooldown_round": self._round,
            "max_cooldowns": self._max_cooldowns,
            "request_label": request_label,
            "item_index": self._item_index,
            "total_items": self._total_items,
            "request": error.checkpoint_fields(),
            # 当前项目的内存中间票档不跨进程拼接；重启时从 base 整项重抓，
            # 避免把两个时间点的票档混成一个快照。
            "pending_items": [
                item.model_dump(mode="json") for item in self._pending_items
            ],
        }

    def _save_checkpoint(
        self,
        *,
        state: str,
        error: PcDetailRetryableError,
        request_label: str,
        resume_at: datetime | None,
    ) -> bool:
        if self._checkpoint_path is None:
            return False
        try:
            payload = self._checkpoint_payload(
                state=state,
                error=error,
                request_label=request_label,
                resume_at=resume_at,
            )
            self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._checkpoint_path.with_suffix(
                self._checkpoint_path.suffix + ".tmp"
            )
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(self._checkpoint_path)
            self._checkpoint_active = True
            self._checkpoint_item_id = str(error.item_id or "")
            self._last_error = error
            self._last_request_label = request_label
            return True
        except Exception as exc:  # noqa: BLE001 - checkpoint 必须是 best effort
            logger.warning(
                "damai pc checkpoint save failed path=%s reason=%s",
                self._checkpoint_path,
                exc,
            )
            return False

    def _clear_checkpoint(self) -> None:
        if self._checkpoint_path is None:
            return
        try:
            if not self._checkpoint_path.exists():
                self._checkpoint_active = False
                self._checkpoint_item_id = ""
                return
            payload = json.loads(self._checkpoint_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("batch_id") != self._batch_id:
                return
            self._checkpoint_path.unlink(missing_ok=True)
            self._checkpoint_active = False
            self._checkpoint_item_id = ""
        except Exception as exc:  # noqa: BLE001 - 清理失败不得影响详情成功
            logger.warning(
                "damai pc checkpoint clear failed path=%s reason=%s",
                self._checkpoint_path,
                exc,
            )

    async def recover(
        self,
        error: PcDetailRetryableError,
        *,
        request_label: str,
        trigger: str = "bixi",
    ) -> None:
        """打开熔断、可取消地冷却；返回后调用方重放完全相同的请求。"""
        next_round = self._round + 1
        if next_round > self._max_cooldowns:
            checkpoint_saved = self._save_checkpoint(
                state="suspended",
                error=error,
                request_label=request_label,
                resume_at=None,
            )
            logger.error(
                "damai pc circuit exhausted item=%s label=%s dataType=%s dataId=%s "
                "cooldowns=%s checkpoint_saved=%s trigger=%s",
                error.item_id,
                request_label,
                error.data_type or "-",
                error.data_id or "-",
                self._round,
                str(checkpoint_saved).lower(),
                trigger,
            )
            checkpoint_message = "已保存断点" if checkpoint_saved else "断点保存失败"
            raise PcDetailCircuitOpenError(
                f"大麦 PC 详情通道连续异常，{checkpoint_message}并停止本批详情 "
                f"item={error.item_id} dataType={error.data_type or '-'} "
                f"dataId={error.data_id or '-'}"
            ) from error

        self._round = next_round
        low, high = self._cooldowns[0 if self._round == 1 else 1]
        cooldown_s = random.uniform(low, high)
        resume_at = datetime.now(timezone.utc) + timedelta(seconds=cooldown_s)
        checkpoint_saved = self._save_checkpoint(
            state="cooling_down",
            error=error,
            request_label=request_label,
            resume_at=resume_at,
        )
        logger.warning(
            "damai pc circuit open item=%s label=%s dataType=%s dataId=%s "
            "round=%s/%s cooldown=%.1fs resume_at=%s checkpoint_saved=%s trigger=%s",
            error.item_id,
            request_label,
            error.data_type or "-",
            error.data_id or "-",
            self._round,
            self._max_cooldowns,
            cooldown_s,
            resume_at.isoformat(),
            str(checkpoint_saved).lower(),
            trigger,
        )
        try:
            if cooldown_s > 0:
                await asyncio.sleep(cooldown_s)
        except asyncio.CancelledError:
            self._save_checkpoint(
                state="cancelled_during_cooldown",
                error=error,
                request_label=request_label,
                resume_at=None,
            )
            raise
        logger.info(
            "damai pc circuit probe item=%s label=%s dataType=%s dataId=%s round=%s",
            error.item_id,
            request_label,
            error.data_type or "-",
            error.data_id or "-",
            self._round,
        )

    def record_healthy_response(self, *, item_id: str, request_label: str) -> None:
        """通过业务校验的原请求证明风控解除；断点等项目落库后再删。"""
        if not self._round:
            return
        logger.info(
            "damai pc circuit closed item=%s label=%s recovered_round=%s",
            item_id,
            request_label,
            self._round,
        )
        self._round = 0
        if self._checkpoint_active and self._last_error is not None:
            self._save_checkpoint(
                state="channel_recovered_pending_persist",
                error=self._last_error,
                request_label=self._last_request_label or request_label,
                resume_at=None,
            )

    def mark_item_persisted(self, item_id: str) -> None:
        """当前项目已经进入 out/on_item；此时才安全删除该项目的风控断点。"""
        if self._checkpoint_active and str(item_id or "") == self._checkpoint_item_id:
            self._clear_checkpoint()


class _SubpageRequestPacer:
    """全局 subpage 请求节拍器，避免长档期项目形成突发流量。"""

    def __init__(self, interval_s: float) -> None:
        self.interval_s = max(0.0, float(interval_s))
        self.jitter_s = self.interval_s * 0.25
        self._next_at = 0.0

    async def wait_turn(self) -> None:
        if self.interval_s <= 0:
            return
        loop = asyncio.get_running_loop()
        wait_s = self._next_at - loop.time()
        if wait_s > 0:
            await asyncio.sleep(wait_s)
        jitter = random.uniform(0.0, self.jitter_s)
        self._next_at = loop.time() + self.interval_s + jitter

SUBPAGE_BASE = "https://detail.damai.cn/subpage"
ITEM_PAGE = "https://detail.damai.cn/item.htm"

# 桌面 Chrome UA 兜底。大麦对 subpage / item.htm 会校验 UA：Playwright 的
# context.request 是独立 HTTP 栈，默认 UA（APIRequest/…）或 headless 的
# HeadlessChrome 会被判为非浏览器请求，直接返回裸 "error" 或空 body，导致
# 95% 详情拉取失败、场次全丢。请求必须带一个正常浏览器 UA。
DAMAI_DESKTOP_UA = (
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
        return DAMAI_DESKTOP_UA
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


def _is_pc_app_only_subpage_candidate(payload: dict[str, Any]) -> bool:
    """识别 PC ``subpage`` 返回的已知 App 专购业务壳。

    这个响应本身不带 itemId，因此只能作为候选信号；调用方还必须用
    item.htm 的 staticDataDefault 精确核对项目，再验证 dataDefault 的
    购买按钮状态，才能允许移动端补全。
    """
    response_info = (
        payload.get("responseInfo")
        if isinstance(payload.get("responseInfo"), dict)
        else {}
    )
    action_control = (
        payload.get("actionControl")
        if isinstance(payload.get("actionControl"), dict)
        else {}
    )
    calculate_control = (
        action_control.get("calculatePriceControl")
        if isinstance(action_control.get("calculatePriceControl"), dict)
        else {}
    )
    rendering_control = (
        action_control.get("renderingControl")
        if isinstance(action_control.get("renderingControl"), dict)
        else {}
    )
    trade_control = (
        action_control.get("tradeControl")
        if isinstance(action_control.get("tradeControl"), dict)
        else {}
    )

    # 正常详情或错配详情只要携带任一核心对象，就不能按 App 专购壳放行。
    if any(key in payload for key in ("itemBasicInfo", "perform", "performCalendar")):
        return False
    if not (
        isinstance(payload.get("itemAdditionalInfo"), dict)
        and isinstance(payload.get("skuRelatedText"), dict)
        and isinstance(payload.get("tradeInfo"), dict)
        and isinstance(payload.get("holidayCalendar"), list)
    ):
        return False
    return (
        str(response_info.get("responseSuccess") or "").lower() == "true"
        and str(calculate_control.get("calcFailSafe") or "").lower() == "true"
        and str(calculate_control.get("needCalc") or "").lower() == "true"
        and str(rendering_control.get("renderingType") or "") == "1"
        and str(action_control.get("srcVerify") or "") == "0"
        and str(trade_control.get("rtc") or "").lower() == "true"
    )


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
    """优先解析页面展示时间，结构化字段只作兜底。

    大麦偶尔会返回与展示名称不一致的 performBeginDTStr，例如名称为
    ``2026-08-13 周四 14:30``，字段却是 ``202608131400``。
    """
    label = str(name or "").strip()
    full = re.search(
        r"(\d{4})[-./年](\d{1,2})[-./月](\d{1,2})日?.*?(\d{1,2}):(\d{2})",
        label,
    )
    if full:
        year, month, day, hour, minute = (int(x) for x in full.groups())
        return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"

    s = str(begin or "").strip()
    label_time = re.search(r"(\d{1,2}):(\d{2})", label)
    if len(s) >= 8 and s[:8].isdigit() and label_time:
        hour, minute = (int(x) for x in label_time.groups())
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {hour:02d}:{minute:02d}"
    if len(s) >= 12 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}"
    if label:
        return label
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
        price_value: Any = None
        for field in ("price", "salePrice", "priceValue", "skuPrice", "dashPrice"):
            candidate = sku.get(field)
            if candidate not in (None, ""):
                price_value = candidate
                break
        price = _parse_price(price_value)
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
    """解析 item.htm 的静态信息，并保留 PC 购买状态供业务校验。"""
    data = _extract_json_object(html, 'id="staticDataDefault"')
    if not data:
        data = _extract_json_object(html, "staticDataDefault")
    if not data:
        return {}

    dynamic = _extract_json_object(html, 'id="dataDefault"')
    if not dynamic:
        dynamic = _extract_json_object(html, "id='dataDefault'")
    if not dynamic:
        dynamic = {}

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
        # 以下字段只用于确认“目标项目在 PC 正常存在，但明确仅支持 App
        # 购买”。不得直接展示或当作 PC 票档入库。
        "_source_item_id": str(item_base.get("itemId") or ""),
        "_project_status": item_base.get("projectStatus"),
        "_buy_btn_status": dynamic.get("buyBtnStatus"),
        "_buy_btn_origin": dynamic.get("buyBtnOrigin"),
        "_buy_btn_text": clean_text(str(dynamic.get("buyBtnText") or "")),
        "_buy_btn_tip": clean_text(str(dynamic.get("buyBtnTip") or "")),
        "_perform_bases": dynamic.get("performBases"),
    }


def _is_pc_app_only_static(static: dict[str, Any], expected_item_id: str) -> bool:
    """严格确认 item.htm 表示目标项目仅支持大麦 App 购买。"""
    button_text = clean_text(str(static.get("_buy_btn_text") or ""))
    button_tip = clean_text(str(static.get("_buy_btn_tip") or ""))
    tip_lower = button_tip.lower()
    unsupported_text = (
        "渠道不支持购票" in button_text or "渠道不支持购买" in button_text
    )
    app_purchase_tip = (
        ("大麦app" in tip_lower or "手机" in button_tip)
        and ("购买" in button_tip or "购票" in button_tip)
    )
    perform_bases = static.get("_perform_bases")
    return (
        str(static.get("_source_item_id") or "") == str(expected_item_id)
        and str(static.get("_project_status") or "") == "1"
        and str(static.get("_buy_btn_status") or "") == "100"
        and str(static.get("_buy_btn_origin") or "") == "109"
        and unsupported_text
        and app_purchase_tip
        and isinstance(perform_bases, list)
        and not perform_bases
    )


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


def extract_detail_from_mobile(
    payload: dict[str, Any],
    *,
    expected_item_id: str,
) -> dict[str, Any]:
    """从移动端 MTop ``itemDetail`` 结果抽取场次和静态详情。

    这个响应包含 PC ``subpage`` 缺失项目的基础资料、完整场次列表和项目
    介绍，但不包含逐场票档。因此移动兜底以全局价格区间入库，并明确
    记录票档来源，避免把区间价格伪造成每场票档。
    """
    component_map = payload.get("detailViewComponentMap")
    item_root = component_map.get("item") if isinstance(component_map, dict) else None
    if not isinstance(item_root, dict):
        return {}

    static = item_root.get("staticData")
    static = static if isinstance(static, dict) else {}
    item_base = static.get("itemBase")
    item_base = item_base if isinstance(item_base, dict) else {}
    actual_item_id = str(item_base.get("itemId") or "")
    if actual_item_id != str(expected_item_id):
        return {}

    venue = static.get("venue")
    venue = venue if isinstance(venue, dict) else {}
    dynamic = item_root.get("dynamicExtData")
    dynamic = dynamic if isinstance(dynamic, dict) else {}
    item_data = item_root.get("item")
    item_data = item_data if isinstance(item_data, dict) else {}

    sessions: list[dict[str, Any]] = []
    for perform_base in item_data.get("performBases") or []:
        if not isinstance(perform_base, dict):
            continue
        for perform in perform_base.get("performs") or []:
            if not isinstance(perform, dict):
                continue
            perform_id = str(perform.get("performId") or "")
            if not perform_id:
                continue
            perform_name = clean_text(
                str(perform.get("performName") or perform.get("performTime") or "")
            )
            start_date = str(perform.get("performStartDate") or "")
            begin_time = str(perform.get("performBeginTime") or "")
            structured = re.sub(r"\D", "", f"{start_date}{begin_time}")
            start_time = _perform_begin_to_raw(structured, perform_name)
            date_key = re.sub(r"\D", "", start_date)
            sessions.append(
                {
                    "id": perform_id,
                    "session_id": perform_id,
                    "name": perform_name,
                    "start_time": start_time,
                    "time": start_time,
                    "showTime": start_time,
                    "status": "onsale",
                    "date_key": date_key,
                    "tags": [],
                    "ticket_tiers": [],
                }
            )
    sessions.sort(key=lambda value: str(value.get("start_time") or ""))

    extend_info = static.get("itemExtendInfo")
    extend_info = extend_info if isinstance(extend_info, dict) else {}
    description = _html_to_text(str(extend_info.get("itemExtend") or ""))
    parsed_description = parse_description_sections(description)

    performers = [
        clean_text(str(artist.get("artistName") or artist.get("name") or ""))
        for artist in (dynamic.get("artists") or [])
        if isinstance(artist, dict)
    ]
    performers = [name for name in performers if name]
    for name in parsed_description.get("performers") or []:
        cleaned = clean_text(str(name))
        if cleaned and cleaned not in performers:
            performers.append(cleaned)

    organizers = list(parsed_description.get("organizers") or [])
    for note in item_base.get("serviceNotes") or []:
        if not isinstance(note, dict):
            continue
        note_text = _html_to_text(
            str(note.get("tagDesc") or note.get("tagDescWithStyle") or "")
        )
        match = re.search(r"发票开具方[：:]\s*([^\n<]+)", note_text)
        if not match:
            continue
        organizer = clean_text(match.group(1))
        if organizer and organizer not in organizers:
            organizers.append(organizer)
        break

    venue_address = clean_text(str(venue.get("venueAddr") or ""))
    date_ids = sorted(
        {str(session.get("date_key") or "") for session in sessions if session.get("date_key")}
    )

    def as_float(value: Any) -> float | None:
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return {
        "title": clean_text(str(item_base.get("itemName") or "")),
        "city": clean_text(
            str(
                venue.get("venueCityName")
                or item_base.get("cityName")
                or venue.get("venueProvinceName")
                or ""
            )
        ),
        "venue_name": clean_text(str(venue.get("venueName") or "")),
        "venue_address": venue_address,
        "district": _district_from_address(venue_address),
        "lat": as_float(venue.get("lat")),
        "lng": as_float(venue.get("lng")),
        "venue_id": venue.get("venueId"),
        "price_range": clean_text(str(item_data.get("priceRange") or "")),
        "date_ids": date_ids,
        "sessions": sessions,
        "calendar_date_count": len(date_ids),
        "calendar_dates_fetched": len(date_ids),
        "calendar_dates_failed": [],
        "ticket_sessions_requested": 0,
        "ticket_sessions_fetched": 0,
        "ticket_sessions_failed": [],
        "ticket_tier_source": "mobile_price_range",
        "description": description[:8000],
        "troupe": parsed_description.get("troupe") or "",
        "organizers": organizers,
        "performers": performers,
        "conductor": parsed_description.get("conductor") or "",
        "program": parsed_description.get("program") or "",
        "price_text": parsed_description.get("price_text") or "",
        "place_text": parsed_description.get("place_text") or "",
        "detail_source": "damai_mobile_mtop",
        "detail_url": mobile_detail_url(expected_item_id),
        "detail_complete": bool(sessions),
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


def _text_has_price_amount(value: Any) -> bool:
    text = clean_text(str(value or ""))
    if not text:
        return False
    if re.search(r"(?:[￥¥]\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*元)", text):
        return True
    normalized = re.sub(r"^(?:票价|价格|售价)\s*[：:]?\s*", "", text)
    normalized = re.sub(r"\bVIP\b", "", normalized, flags=re.I).strip()
    return bool(
        re.fullmatch(
            r"\d+(?:\.\d+)?(?:\s*(?:[-~—–至|/,])\s*\d+(?:\.\d+)?)*",
            normalized,
        )
    )


def _detail_has_price(detail: dict[str, Any]) -> bool:
    """只检查本次 PC 详情中的价格，避免列表页旧价格干扰降级判断。"""
    for session in detail.get("sessions") or []:
        if not isinstance(session, dict):
            continue
        for tier in session.get("ticket_tiers") or []:
            if not isinstance(tier, dict):
                continue
            if _parse_price(tier.get("price")) is not None:
                return True
            for field in ("name", "raw"):
                if _text_has_price_amount(tier.get(field)):
                    return True
    return any(_text_has_price_amount(detail.get(field)) for field in ("price_range", "price_text"))


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
                item.price_raw = (
                    str(pr).replace("￥", "").replace("¥", "").replace(" ", "")
                )

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
        "detail_complete": bool(detail.get("detail_complete", sessions)),
        "calendar_date_count": int(detail.get("calendar_date_count") or 0),
        "calendar_dates_fetched": int(detail.get("calendar_dates_fetched") or 0),
        "calendar_dates_failed": detail.get("calendar_dates_failed") or [],
        "ticket_sessions_requested": int(detail.get("ticket_sessions_requested") or 0),
        "ticket_sessions_fetched": int(detail.get("ticket_sessions_fetched") or 0),
        "ticket_sessions_failed": detail.get("ticket_sessions_failed") or [],
        "ticket_tier_source": detail.get("ticket_tier_source") or "pc_subpage",
        "detail_source": detail.get("detail_source") or "damai_pc_subpage",
        "detail_url": detail.get("detail_url") or item.url,
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

    不用 page.evaluate(fetch)：页面导航或风控跳转不能中断独立 HTTP 请求。
    """
    url = _build_subpage_url(item_id, data_id=data_id, data_type=data_type)
    text = ""
    status = 0
    content_type = ""
    response_url = ""
    response_location = ""
    response_ok = False
    request_error: Exception | None = None
    ua = await _browser_ua(page)
    resp = None
    try:
        # context.request 继承 storage_state cookies
        req = page.context.request
        resp = await req.get(
            url,
            timeout=timeout_ms,
            max_redirects=0,
            headers={
                "accept": "*/*",
                "referer": f"https://detail.damai.cn/item.htm?id={item_id}",
                "x-requested-with": "XMLHttpRequest",
                "user-agent": ua,
            },
        )
        status = int(resp.status)
        response_ok = bool(resp.ok)
        headers = getattr(resp, "headers", {}) or {}
        content_type = str(headers.get("content-type") or "")
        response_url = str(getattr(resp, "url", "") or "")
        response_location = str(headers.get("location") or "")
        text = await resp.text()
    except Exception as exc:  # noqa: BLE001
        request_error = exc
    finally:
        if resp is not None:
            try:
                await resp.dispose()
            except Exception:  # noqa: BLE001
                pass

    resolved_location = (
        urljoin(response_url or url, response_location) if response_location else ""
    )
    risk_url = " ".join(part for part in (response_url, resolved_location) if part)
    if is_bixi_punish(text, content_type, risk_url):
        logger.warning(
            "subpage bixi punish item=%s dataType=%s dataId=%s status=%s "
            "content_type=%s chars=%s",
            item_id,
            data_type or "-",
            data_id or "-",
            status,
            content_type or "-",
            len(text),
        )
        raise BixiPunishError(
            item_id=item_id,
            data_type=data_type,
            data_id=data_id,
            status=status,
            content_type=content_type,
            response_url=response_location or response_url,
            body_chars=len(text),
        )

    def retryable_error(reason: str) -> PcDetailRetryableError:
        logger.warning(
            "subpage pc unavailable item=%s dataType=%s dataId=%s reason=%s "
            "status=%s content_type=%s chars=%s",
            item_id,
            data_type or "-",
            data_id or "-",
            reason,
            status,
            content_type or "-",
            len(text),
        )
        return PcDetailRetryableError(
            item_id=item_id,
            reason=reason,
            data_type=data_type,
            data_id=data_id,
            status=status,
            content_type=content_type,
            response_url=resolved_location or response_url,
            body_chars=len(text),
        )

    if request_error is not None:
        raise retryable_error("request_error") from request_error
    if response_location or 300 <= status < 400:
        reason = (
            "cross_domain_redirect"
            if _is_unexpected_detail_url(resolved_location)
            else "unexpected_redirect"
        )
        raise retryable_error(reason)
    if _is_unexpected_detail_url(response_url):
        raise retryable_error("cross_domain_response")
    if not response_ok:
        logger.warning(
            "subpage http %s item=%s dataId=%s", status, item_id, data_id or "-"
        )
        if status in {401, 403, 408, 425, 429} or status >= 500:
            raise retryable_error(f"http_{status or 'error'}")
        raise PcDetailSemanticError(
            f"大麦 PC 详情业务状态异常 item={item_id} status={status}"
        )
    if not text.strip():
        raise retryable_error("empty_response")
    if "text/html" in content_type.lower() or re.search(
        r"<\s*(?:!doctype\s+html|html|head|body|script)\b",
        text,
        re.I,
    ):
        raise retryable_error("html_response")
    data = parse_jsonp(text)
    if not data:
        raise retryable_error("invalid_jsonp")
    resp_info = data.get("responseInfo") if isinstance(data.get("responseInfo"), dict) else {}
    if resp_info and str(resp_info.get("responseSuccess", "true")).lower() == "false":
        logger.warning(
            "subpage response fail item=%s code=%s", item_id, resp_info.get("responseCode")
        )
        raise PcDetailSemanticError(
            "大麦 PC 详情业务响应失败 "
            f"item={item_id} code={resp_info.get('responseCode') or '-'}"
        )
    return data


async def _fetch_subpage_with_retry(
    page: Page,
    item_id: str,
    *,
    data_id: str = "",
    data_type: str = "",
    attempts: int = 3,
    retry_delay_s: float = 2.0,
    max_retry_delay_s: float = 2.0,
    pacer: _SubpageRequestPacer | None = None,
    circuit_breaker: _SubpageCircuitBreaker | None = None,
    validator: Callable[[dict[str, Any]], bool] | None = None,
    request_label: str = "base",
) -> dict[str, Any] | None:
    """按全局节拍请求；失败时固定间隔重试并验证业务语义。"""
    # 保留参数是为了兼容旧配置/调用方；重试策略现在固定间隔，不再递增。
    _ = max_retry_delay_s
    total = max(1, attempts)
    immediate_cooldown_reasons = {
        "bixi",
        "html_response",
        "cross_domain_redirect",
        "cross_domain_response",
        "unexpected_redirect",
        "http_401",
        "http_403",
        "http_429",
    }

    def is_valid(data: dict[str, Any] | None) -> bool:
        return bool(data) and (validator(data) if validator is not None else True)

    async def request_once() -> dict[str, Any] | None:
        if pacer is not None:
            await pacer.wait_turn()
        return await fetch_subpage(
            page,
            item_id,
            data_id=data_id,
            data_type=data_type,
        )

    async def recover_and_replay(
        error: PcDetailRetryableError,
        *,
        trigger: str,
    ) -> dict[str, Any]:
        if circuit_breaker is None:
            raise error
        current_error = error
        current_trigger = trigger
        while True:
            await circuit_breaker.recover(
                current_error,
                request_label=request_label,
                trigger=current_trigger,
            )
            try:
                probe = await request_once()
            except PcDetailRetryableError as probe_error:
                current_error = probe_error
                current_trigger = probe_error.reason
                continue
            except PcDetailSemanticError:
                probe = None
            if is_valid(probe):
                circuit_breaker.record_healthy_response(
                    item_id=item_id,
                    request_label=request_label,
                )
                return probe
            logger.warning(
                "damai pc circuit probe invalid item=%s label=%s dataType=%s "
                "dataId=%s response=%s",
                item_id,
                request_label,
                data_type or "-",
                data_id or "-",
                "semantic_mismatch" if probe else "unavailable",
            )
            current_trigger = "probe_invalid"

    last_retryable_error: PcDetailRetryableError | None = None
    semantic_error: PcDetailSemanticError | None = None
    for attempt in range(1, total + 1):
        try:
            data = await request_once()
        except PcDetailRetryableError as error:
            if error.reason in immediate_cooldown_reasons:
                return await recover_and_replay(
                    error,
                    trigger=error.reason,
                )
            last_retryable_error = error
            data = None
        except PcDetailSemanticError as error:
            last_retryable_error = None
            semantic_error = error
            data = None
        else:
            last_retryable_error = None
        if is_valid(data):
            return data
        if data and validator is not None:
            semantic_error = PcDetailSemanticError(
                "大麦 PC 详情内容不匹配 "
                f"item={item_id} label={request_label}"
            )
            logger.warning(
                "subpage semantic mismatch item=%s label=%s dataType=%s dataId=%s "
                "attempt=%s/%s",
                item_id,
                request_label,
                data_type or "-",
                data_id or "-",
                attempt,
                total,
            )
        if attempt < total:
            retry_in = max(0.0, retry_delay_s)
            logger.warning(
                "subpage retry scheduled item=%s label=%s attempt=%s/%s retry_in=%.1fs",
                item_id,
                request_label,
                attempt + 1,
                total,
                retry_in,
            )
            if retry_in > 0:
                await asyncio.sleep(retry_in)

    if last_retryable_error is not None:
        return await recover_and_replay(
            last_retryable_error,
            trigger=f"{last_retryable_error.reason}_retries_exhausted",
        )
    logger.warning(
        "subpage retries exhausted item=%s label=%s dataType=%s dataId=%s attempts=%s",
        item_id,
        request_label,
        data_type or "-",
        data_id or "-",
        total,
    )
    if semantic_error is not None:
        raise semantic_error
    raise PcDetailSemanticError(
        f"大麦 PC 详情子项不可用 item={item_id} label={request_label}"
    )


async def fetch_item_static(
    page: Page,
    item_id: str,
    *,
    timeout_ms: int = 20000,
    pacer: _SubpageRequestPacer | None = None,
    circuit_breaker: _SubpageCircuitBreaker | None = None,
    attempts: int = 3,
    retry_delay_s: float = 2.0,
    max_retry_delay_s: float = 2.0,
) -> dict[str, Any]:
    """GET item.htm，解析 staticDataDefault（场馆地址 + 项目介绍）。"""
    url = f"{ITEM_PAGE}?id={item_id}"
    ua = await _browser_ua(page)
    transient_error: PcDetailRetryableError | None = None
    attempt = 0
    total = max(1, int(attempts))
    immediate_cooldown_reasons = {
        "bixi",
        "login_or_challenge_html",
        "cross_domain_redirect",
        "cross_domain_response",
        "unexpected_redirect",
        "http_401",
        "http_403",
        "http_429",
    }
    while True:
        attempt += 1
        if pacer is not None:
            await pacer.wait_turn()
        resp = None
        html = ""
        status = 0
        content_type = ""
        response_url = ""
        response_location = ""
        response_ok = False
        request_error: Exception | None = None
        try:
            resp = await page.context.request.get(
                url,
                timeout=timeout_ms,
                max_redirects=0,
                headers={
                    "accept": "text/html,application/xhtml+xml",
                    "referer": "https://search.damai.cn/",
                    "user-agent": ua,
                },
            )
            status = int(resp.status)
            response_ok = bool(resp.ok)
            headers = getattr(resp, "headers", {}) or {}
            content_type = str(headers.get("content-type") or "")
            response_url = str(getattr(resp, "url", "") or "")
            response_location = str(headers.get("location") or "")
            html = await resp.text()
        except Exception as exc:  # noqa: BLE001
            request_error = exc
        finally:
            if resp is not None:
                try:
                    await resp.dispose()
                except Exception:  # noqa: BLE001
                    pass

        resolved_location = (
            urljoin(response_url or url, response_location)
            if response_location
            else ""
        )
        risk_url = " ".join(part for part in (response_url, resolved_location) if part)
        error: PcDetailRetryableError | None = None
        if is_bixi_punish(html, content_type, risk_url):
            error = BixiPunishError(
                item_id=item_id,
                data_type="item_static",
                status=status,
                content_type=content_type,
                response_url=response_location or response_url,
                body_chars=len(html),
            )
            logger.warning(
                "item.htm bixi punish item=%s status=%s content_type=%s chars=%s",
                item_id,
                status,
                content_type or "-",
                len(html),
            )
        elif request_error is not None:
            error = PcDetailRetryableError(
                item_id=item_id,
                reason="request_error",
                data_type="item_static",
            )
        elif response_location or 300 <= status < 400:
            reason = (
                "cross_domain_redirect"
                if _is_unexpected_detail_url(resolved_location)
                else "unexpected_redirect"
            )
            error = PcDetailRetryableError(
                item_id=item_id,
                reason=reason,
                data_type="item_static",
                status=status,
                content_type=content_type,
                response_url=resolved_location or response_url,
                body_chars=len(html),
            )
        elif _is_unexpected_detail_url(response_url):
            error = PcDetailRetryableError(
                item_id=item_id,
                reason="cross_domain_response",
                data_type="item_static",
                status=status,
                content_type=content_type,
                response_url=response_url,
                body_chars=len(html),
            )
        elif not response_ok:
            error = PcDetailRetryableError(
                item_id=item_id,
                reason=f"http_{status or 'error'}",
                data_type="item_static",
                status=status,
                content_type=content_type,
                response_url=response_url,
                body_chars=len(html),
            )
        elif not html.strip():
            error = PcDetailRetryableError(
                item_id=item_id,
                reason="empty_response",
                data_type="item_static",
                status=status,
                content_type=content_type,
                response_url=response_url,
            )
        elif _is_login_or_challenge_html(html):
            error = PcDetailRetryableError(
                item_id=item_id,
                reason="login_or_challenge_html",
                data_type="item_static",
                status=status,
                content_type=content_type,
                response_url=response_url,
                body_chars=len(html),
            )
        else:
            error_shell_reason = _item_error_shell_reason(html)
            if error_shell_reason:
                logger.warning(
                    "item.htm pc semantic failure item=%s reason=%s status=%s chars=%s",
                    item_id,
                    error_shell_reason,
                    status,
                    len(html),
                )
                raise PcDetailSemanticError(
                    "大麦 PC item.htm 返回错误页面 "
                    f"reason={error_shell_reason} item={item_id}"
                )

        if error is not None:
            logger.warning(
                "item.htm pc unavailable item=%s reason=%s status=%s "
                "content_type=%s chars=%s",
                item_id,
                error.reason,
                status,
                content_type or "-",
                len(html),
            )
            if circuit_breaker is None:
                raise error from request_error
            if (
                transient_error is None
                and error.reason not in immediate_cooldown_reasons
                and attempt < total
            ):
                retry_in = min(
                    max(0.0, float(max_retry_delay_s)),
                    max(0.0, float(retry_delay_s)) * (2 ** (attempt - 1)),
                )
                logger.warning(
                    "item.htm pc retry scheduled item=%s reason=%s attempt=%s/%s "
                    "retry_in=%.1fs",
                    item_id,
                    error.reason,
                    attempt + 1,
                    total,
                    retry_in,
                )
                if retry_in > 0:
                    await asyncio.sleep(retry_in)
                continue
            transient_error = error
            await circuit_breaker.recover(
                error,
                request_label="item_static",
                trigger=(
                    error.reason
                    if error.reason in immediate_cooldown_reasons
                    else f"{error.reason}_retries_exhausted"
                ),
            )
            attempt = 0
            continue

        if transient_error is not None and circuit_breaker is not None:
            circuit_breaker.record_healthy_response(
                item_id=item_id,
                request_label="item_static",
            )
        return parse_item_static_html(html)


async def enrich_item_detail(
    page: Page,
    item: RawShowItem,
    *,
    fetch_all_dates: bool = True,
    date_limit: int = 0,
    delay_s: float = 0.25,
    pacer: _SubpageRequestPacer | None = None,
    circuit_breaker: _SubpageCircuitBreaker | None = None,
    request_attempts: int = 3,
    retry_delay_s: float = 2.0,
    max_retry_delay_s: float = 2.0,
) -> RawShowItem:
    """拉取完整详情并写回 item；可靠性重试耗尽时抛错，禁止降级入库。"""
    item_id = (item.source_id or "").strip()
    if not item_id or not item_id.isdigit():
        # 尝试从 url 抠 id
        m = re.search(r"[?&]id=(\d+)", item.url or "")
        item_id = m.group(1) if m else ""
    if not item_id:
        raise DetailCompletenessError(
            f"大麦详情缺少可用项目 ID source_id={item.source_id!r} url={item.url!r}"
        )

    async def fetch_reliable(
        *,
        data_id: str = "",
        data_type: str = "",
        validator: Callable[[dict[str, Any]], bool] | None = None,
        label: str,
    ) -> dict[str, Any] | None:
        return await _fetch_subpage_with_retry(
            page,
            item_id,
            data_id=data_id,
            data_type=data_type,
            attempts=request_attempts,
            retry_delay_s=retry_delay_s,
            max_retry_delay_s=max_retry_delay_s,
            pacer=pacer,
            circuit_breaker=circuit_breaker,
            validator=validator,
            request_label=label,
        )

    # 1) subpage：场次 + 票档
    detail: dict[str, Any] = {}

    def is_expected_base(payload: dict[str, Any]) -> bool:
        basic = payload.get("itemBasicInfo")
        if isinstance(basic, dict):
            return str(basic.get("itemId") or "") == item_id
        return _is_pc_app_only_subpage_candidate(payload)

    base = await fetch_reliable(validator=is_expected_base, label="base")
    if base:
        if _is_pc_app_only_subpage_candidate(base):
            # subpage 的 App 专购壳不带 itemId，必须再以 PC item.htm 的
            # 结构化数据同时核对目标项目和购买状态，不能仅凭缺字段下沉。
            static = await fetch_item_static(
                page,
                item_id,
                pacer=pacer,
                circuit_breaker=circuit_breaker,
                attempts=request_attempts,
                retry_delay_s=retry_delay_s,
                max_retry_delay_s=max_retry_delay_s,
            )
            if _is_pc_app_only_static(static, item_id):
                logger.info(
                    "damai pc app only item=%s buy_status=%s buy_origin=%s",
                    item_id,
                    static.get("_buy_btn_status"),
                    static.get("_buy_btn_origin"),
                )
                raise PcDetailAppOnlyError(
                    f"大麦 PC 项目正常存在但仅支持 App 购买 item={item_id}"
                )
            raise PcDetailSemanticError(
                "大麦 PC App 专购候选响应未通过项目与购买状态校验 "
                f"item={item_id}"
            )

        detail = extract_detail_from_subpage(base)
        all_sessions = list(detail.get("sessions") or [])
        ticket_details_fetched: set[str] = set()

        def record_explicit_ticket_response(payload: dict[str, Any]) -> None:
            perform = payload.get("perform")
            if not isinstance(perform, dict) or not isinstance(
                perform.get("skuList"), list
            ):
                return
            perform_id = str(perform.get("performId") or perform.get("id") or "")
            if perform_id:
                ticket_details_fetched.add(perform_id)

        record_explicit_ticket_response(base)

        date_ids = list(detail.get("date_ids") or [])
        limited_date_ids = date_ids if date_limit <= 0 else date_ids[:date_limit]
        fetched_dates: set[str] = set()
        failed_dates: list[str] = []
        if fetch_all_dates and date_ids:
            seen_dates = {
                str(s.get("date_key") or "") for s in all_sessions if s.get("date_key")
            }
            fetched_dates.update(d for d in limited_date_ids if d in seen_dates)
            for date_id in limited_date_ids:
                if date_id in seen_dates:
                    continue
                day = await fetch_reliable(
                    data_id=date_id,
                    data_type="4",
                    validator=lambda payload, expected=date_id: any(
                        str(session.get("date_key") or "") == expected
                        for session in (
                            extract_detail_from_subpage(payload).get("sessions") or []
                        )
                    ),
                    label=f"calendar:{date_id}",
                )
                if not day:
                    raise DetailCompletenessError(
                        f"大麦详情日期场次重试耗尽 item={item_id} date={date_id}"
                    )
                day_detail = extract_detail_from_subpage(day)
                day_sessions = day_detail.get("sessions") or []
                all_sessions = merge_sessions(all_sessions, day_sessions)
                record_explicit_ticket_response(day)
                seen_dates.add(date_id)
                fetched_dates.add(date_id)

        # dataType=4 只返回所选日期的默认场次票档。同日其它场次必须再按
        # performId + dataType=2 切换，不能复制默认场次票档。
        ticket_sessions_requested = 0
        ticket_sessions_fetched = 0
        failed_perform_ids: list[str] = []
        for session in all_sessions:
            perform_id = str(session.get("id") or session.get("session_id") or "")
            if not perform_id:
                raise DetailCompletenessError(
                    f"大麦详情场次缺少 performId item={item_id}"
                )
            if perform_id in ticket_details_fetched:
                continue
            ticket_sessions_requested += 1

            def has_requested_tiers(
                payload: dict[str, Any], expected: str = perform_id
            ) -> bool:
                perform = payload.get("perform")
                if not isinstance(perform, dict):
                    return False
                response_perform_id = str(
                    perform.get("performId") or perform.get("id") or ""
                )
                sku_list = perform.get("skuList")
                # 空票档可能是业务上的合法结果；关键是响应明确属于
                # 目标场次，且确实返回了 skuList 字段。
                return response_perform_id == expected and isinstance(sku_list, list)

            perform_data = await fetch_reliable(
                data_id=perform_id,
                data_type="2",
                validator=has_requested_tiers,
                label=f"perform:{perform_id}",
            )
            if not perform_data:
                raise DetailCompletenessError(
                    f"大麦详情票档重试耗尽 item={item_id} perform={perform_id}"
                )
            perform_detail = extract_detail_from_subpage(perform_data)
            current_session = next(
                (
                    fetched
                    for fetched in (perform_detail.get("sessions") or [])
                    if str(fetched.get("id") or fetched.get("session_id") or "")
                    == perform_id
                ),
                None,
            )
            if not current_session:
                raise DetailCompletenessError(
                    f"大麦详情票档响应缺少目标场次 item={item_id} "
                    f"perform={perform_id}"
                )
            all_sessions = merge_sessions(all_sessions, perform_detail.get("sessions") or [])
            record_explicit_ticket_response(perform_data)
            ticket_sessions_fetched += 1

        detail["sessions"] = all_sessions
        detail["calendar_date_count"] = len(date_ids)
        detail["calendar_dates_fetched"] = len(fetched_dates)
        detail["calendar_dates_failed"] = failed_dates
        detail["ticket_sessions_requested"] = ticket_sessions_requested
        detail["ticket_sessions_fetched"] = ticket_sessions_fetched
        detail["ticket_sessions_failed"] = failed_perform_ids
        dates_complete = not date_ids or (
            fetch_all_dates
            and len(date_ids) <= len(limited_date_ids)
            and len(fetched_dates) == len(date_ids)
            and not failed_dates
        )
        detail["detail_complete"] = (
            dates_complete and not failed_dates and not failed_perform_ids
        )
    else:
        raise DetailCompletenessError(
            f"大麦详情基础响应重试耗尽 item={item_id} attempts={request_attempts}"
        )

    if not detail.get("detail_complete"):
        raise DetailCompletenessError(
            f"大麦详情不完整 item={item_id} "
            f"dates={len(limited_date_ids)}/{len(date_ids)}"
        )
    if not detail.get("sessions"):
        raise PcDetailSemanticError(f"大麦 PC 详情未返回场次 item={item_id}")

    # 2) item.htm staticData：真实地址 + 主办/团体/艺术家介绍
    # 已从 subpage 拿到价格时，static 只是可选元数据，失败不能推翻完整票档；
    # subpage 无价格时才要求 static 成功，以确认 PC 确实没有展示价格。
    subpage_has_price = _detail_has_price(detail)
    if delay_s > 0:
        await asyncio.sleep(min(delay_s, 0.2))
    try:
        static = await fetch_item_static(
            page,
            item_id,
            pacer=pacer,
            circuit_breaker=None if subpage_has_price else circuit_breaker,
            attempts=request_attempts,
            retry_delay_s=retry_delay_s,
            max_retry_delay_s=max_retry_delay_s,
        )
    except PcDetailRetryableError as static_error:
        if not subpage_has_price:
            raise
        static = {}
        logger.warning(
            "damai item static skipped item=%s price_confirmed=true reason=%s",
            item_id,
            static_error.reason,
        )
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

    if not _detail_has_price(detail):
        logger.info(
            "damai pc price absent item=%s sessions=%s explicit_ticket_sessions=%s",
            item_id,
            len(detail.get("sessions") or []),
            len(ticket_details_fetched),
        )
        raise PcDetailNoPriceError(
            f"大麦 PC 详情已完整返回但未展示价格 item={item_id}"
        )

    logger.info(
        "damai detail item=%s venue=%s addr=%s sessions=%s complete=%s "
        "dates=%s/%s ticket_sessions=%s/%s troupe=%s organizers=%s",
        item_id,
        detail.get("venue_name"),
        (detail.get("venue_address") or "")[:40],
        len(detail.get("sessions") or []),
        bool(detail.get("detail_complete")),
        int(detail.get("calendar_dates_fetched") or 0),
        int(detail.get("calendar_date_count") or 0),
        int(detail.get("ticket_sessions_fetched") or 0),
        int(detail.get("ticket_sessions_requested") or 0),
        detail.get("troupe") or "",
        detail.get("organizers") or [],
    )
    return apply_detail_to_raw(item, detail)


async def _fetch_mobile_detail_with_retry(
    item_id: str,
    *,
    attempts: int = 3,
    retry_delay_s: float = 2.0,
) -> dict[str, Any] | None:
    """固定 2 秒间隔重试移动端详情；失败由批处理跳过当前项目。"""
    total = max(1, int(attempts))
    last_error: Exception | None = None
    for attempt in range(1, total + 1):
        try:
            return await fetch_mobile_item_detail(item_id)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "damai mobile detail failed item=%s attempt=%s/%s reason=%s",
                item_id,
                attempt,
                total,
                exc,
            )
        if attempt < total:
            retry_in = max(0.0, float(retry_delay_s))
            logger.warning(
                "damai mobile detail retry item=%s attempt=%s/%s retry_in=%.1fs",
                item_id,
                attempt + 1,
                total,
                retry_in,
            )
            if retry_in > 0:
                await asyncio.sleep(retry_in)
    logger.warning(
        "damai mobile detail exhausted item=%s attempts=%s reason=%s",
        item_id,
        total,
        last_error,
    )
    return None


async def enrich_item_mobile_detail(
    item: RawShowItem,
    *,
    request_attempts: int = 3,
    retry_delay_s: float = 2.0,
) -> RawShowItem:
    """用官方大麦移动端 MTop 补全 PC 详情不可用的项目。"""
    item_id = str(item.source_id or "").strip()
    if not item_id.isdigit():
        match = re.search(r"[?&](?:id|itemId)=(\d+)", item.url or "")
        item_id = match.group(1) if match else ""
    if not item_id:
        raise DetailCompletenessError("大麦移动端详情缺少可用项目编号")

    payload = await _fetch_mobile_detail_with_retry(
        item_id,
        attempts=request_attempts,
        retry_delay_s=retry_delay_s,
    )
    if not payload:
        raise DetailCompletenessError(
            f"大麦移动端详情重试耗尽 item={item_id} attempts={request_attempts}"
        )
    detail = extract_detail_from_mobile(payload, expected_item_id=item_id)
    if not detail.get("detail_complete") or not _detail_has_price(detail):
        raise DetailCompletenessError(f"大麦移动端详情缺少场次或价格 item={item_id}")

    # 使用真正可访问的官方移动详情链接，避免保留会返回业务 404 的
    # PC 链接。
    item.url = mobile_detail_url(item_id)
    logger.info(
        "damai mobile detail success item=%s url=%s sessions=%s",
        item_id,
        item.url,
        len(detail.get("sessions") or []),
    )
    logger.info(
        "damai detail item=%s venue=%s addr=%s sessions=%s complete=%s "
        "dates=%s/%s ticket_sessions=%s/%s troupe=%s organizers=%s",
        item_id,
        detail.get("venue_name"),
        (detail.get("venue_address") or "")[:40],
        len(detail.get("sessions") or []),
        bool(detail.get("detail_complete")),
        int(detail.get("calendar_dates_fetched") or 0),
        int(detail.get("calendar_date_count") or 0),
        int(detail.get("ticket_sessions_fetched") or 0),
        int(detail.get("ticket_sessions_requested") or 0),
        detail.get("troupe") or "",
        detail.get("organizers") or [],
    )
    return apply_detail_to_raw(item, detail)


async def enrich_items_detail(
    page: Page,
    items: list[RawShowItem],
    *,
    delay_s: float = 1.5,
    fetch_all_dates: bool = True,
    date_limit: int = 0,
    request_attempts: int = 3,
    retry_delay_s: float = 2.0,
    max_retry_delay_s: float = 2.0,
    project_attempts: int = 1,
    project_cooldown_s: float = 0.0,
    punish_cooldown_min_s: float = 105.0,
    punish_cooldown_max_s: float = 135.0,
    punish_retry_cooldown_min_s: float = 240.0,
    punish_retry_cooldown_max_s: float = 360.0,
    punish_max_cooldowns: int = 2,
    checkpoint_path: str | Path | None = None,
    on_item: Callable[[RawShowItem], Awaitable[None] | None] | None = None,
) -> list[RawShowItem]:
    """批量补全详情；仅 PC 明确无价格时下沉，通道失败绝不降级。"""
    # 兼容旧调用签名；整项目冷却重跑已取消，避免一个项目阻塞
    # 整批任务。
    _ = (project_attempts, project_cooldown_s)
    out: list[RawShowItem] = []
    total = len(items)
    skipped = 0
    pacer = _SubpageRequestPacer(delay_s)
    circuit_breaker = _SubpageCircuitBreaker(
        cooldown_min_s=punish_cooldown_min_s,
        cooldown_max_s=punish_cooldown_max_s,
        retry_cooldown_min_s=punish_retry_cooldown_min_s,
        retry_cooldown_max_s=punish_retry_cooldown_max_s,
        max_cooldowns=punish_max_cooldowns,
        checkpoint_path=checkpoint_path,
    )
    for idx, item in enumerate(items, 1):
        circuit_breaker.set_batch_progress(idx, items)
        logger.info("damai detail processing %s/%s id=%s", idx, total, item.source_id)
        try:
            enriched = await enrich_item_detail(
                page,
                item,
                fetch_all_dates=fetch_all_dates,
                date_limit=date_limit,
                delay_s=delay_s,
                pacer=pacer,
                circuit_breaker=circuit_breaker,
                request_attempts=request_attempts,
                retry_delay_s=retry_delay_s,
                max_retry_delay_s=max_retry_delay_s,
            )
        except PcDetailNoPriceError as no_price_error:
            fallback_reason = (
                "pc_app_only"
                if isinstance(no_price_error, PcDetailAppOnlyError)
                else "pc_no_price"
            )
            logger.info(
                "damai mobile detail fallback item=%s url=%s reason=%s",
                item.source_id,
                mobile_detail_url(str(item.source_id or "")),
                fallback_reason,
            )
            try:
                enriched = await enrich_item_mobile_detail(
                    item,
                    request_attempts=request_attempts,
                    retry_delay_s=retry_delay_s,
                )
            except Exception as mobile_error:  # noqa: BLE001
                skipped += 1
                logger.warning(
                    "damai detail skipped item=%s reason=%s",
                    item.source_id,
                    mobile_error,
                )
                logger.info("damai detail progress %s/%s id=%s", idx, total, item.source_id)
                continue
        except (PcDetailRetryableError, PcDetailCircuitOpenError) as pc_error:
            logger.error(
                "damai pc detail batch suspended item=%s progress=%s/%s reason=%s",
                item.source_id,
                idx,
                total,
                pc_error,
            )
            # 不能继续下一个项目，也不能把区间价移动兜底冒充完整票档。
            raise
        except DetailCompletenessError as pc_error:
            skipped += 1
            logger.warning(
                "damai pc detail skipped item=%s reason=%s",
                item.source_id,
                pc_error,
            )
            logger.info("damai detail progress %s/%s id=%s", idx, total, item.source_id)
            continue
        out.append(enriched)
        if on_item is not None:
            callback_result = on_item(enriched)
            if inspect.isawaitable(callback_result):
                await callback_result
        circuit_breaker.mark_item_persisted(str(enriched.source_id or ""))
        if idx == 1 or idx == total or idx % 10 == 0:
            logger.info("damai detail progress %s/%s id=%s", idx, total, item.source_id)
        if delay_s > 0 and idx < total:
            await asyncio.sleep(delay_s)
    logger.info(
        "damai detail batch done success=%s skipped=%s total=%s",
        len(out),
        skipped,
        total,
    )
    return out
