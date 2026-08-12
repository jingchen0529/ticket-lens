"""大麦移动端详情 MTop 协议客户端。

PC 详情页并不覆盖所有大麦项目；部分有效项目会在 ``detail.damai.cn``
返回业务 404，但 ``m.damai.cn`` 仍能正常展示。移动页的数据来自大麦自己的
``mtop.damai.cn``，这里直接复现其 H5 token + MD5 签名请求，避免浏览器跳转
和页面端域名重定向。
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from urllib.parse import urlparse

import httpx


MOBILE_DETAIL_PAGE = "https://m.damai.cn/shows/item.html"
MTOP_HOST = "mtop.damai.cn"
MTOP_APP_KEY = "12574478"
MTOP_ITEM_DETAIL_API = "mtop.alibaba.damai.detail.getdetail"
MTOP_ITEM_DETAIL_VERSION = "1.2"
MTOP_ITEM_DETAIL_URL = (
    f"https://{MTOP_HOST}/h5/{MTOP_ITEM_DETAIL_API}/{MTOP_ITEM_DETAIL_VERSION}/"
)

_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Mobile Safari/537.36"
)


class MobileDetailError(RuntimeError):
    """移动端详情协议未返回可用且属于目标项目的数据。"""


def mobile_detail_url(item_id: str) -> str:
    """生成不会经过第三方票务域名的官方大麦移动详情地址。"""
    return f"{MOBILE_DETAIL_PAGE}?itemId={str(item_id).strip()}"


def _compact_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def mtop_h5_sign(token: str, timestamp_ms: str, data: str) -> str:
    """计算标准 MTop H5 签名：MD5(token&t&appKey&data)。"""
    material = f"{token}&{timestamp_ms}&{MTOP_APP_KEY}&{data}"
    return hashlib.md5(material.encode("utf-8")).hexdigest()  # noqa: S324


def _cookie_token(cookies: httpx.Cookies) -> str:
    """读取 ``_m_h5_tk`` 的签名 token 部分，兼容同名多域 cookie。"""
    for cookie in cookies.jar:
        if cookie.name != "_m_h5_tk":
            continue
        value = str(cookie.value or "")
        return value.split("_", 1)[0]
    return ""


def _ret_values(payload: dict[str, Any]) -> list[str]:
    ret = payload.get("ret")
    if isinstance(ret, list):
        return [str(value) for value in ret]
    if ret is None:
        return []
    return [str(ret)]


def _is_success(payload: dict[str, Any]) -> bool:
    return any(value.upper().startswith("SUCCESS::") for value in _ret_values(payload))


def _is_token_error(payload: dict[str, Any]) -> bool:
    return any("TOKEN" in value.upper() for value in _ret_values(payload))


def parse_mobile_item_result(payload: dict[str, Any], item_id: str) -> dict[str, Any]:
    """解开 MTop 的 ``data.result`` 字符串并校验项目编号。"""
    data = payload.get("data")
    if not isinstance(data, dict):
        raise MobileDetailError("移动端详情响应缺少 data")
    result: Any = data.get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError as exc:
            raise MobileDetailError("移动端详情 result 不是有效数据格式") from exc
    if not isinstance(result, dict):
        raise MobileDetailError("移动端详情响应缺少 result")

    component_map = result.get("detailViewComponentMap")
    item_root = component_map.get("item") if isinstance(component_map, dict) else None
    static = item_root.get("staticData") if isinstance(item_root, dict) else None
    item_base = static.get("itemBase") if isinstance(static, dict) else None
    actual_id = str(item_base.get("itemId") or "") if isinstance(item_base, dict) else ""
    if actual_id != str(item_id):
        raise MobileDetailError(
            f"移动端详情项目编号不匹配 expected={item_id} actual={actual_id or '-'}"
        )
    return result


class DamaiMobileDetailClient:
    """可复用 token cookie 的异步大麦移动详情客户端。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=False,
            headers={
                "accept": "application/json, text/plain, */*",
                "user-agent": _MOBILE_UA,
            },
        )

    async def __aenter__(self) -> DamaiMobileDetailClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, *, item_id: str, token: str) -> dict[str, Any]:
        request_data = _compact_json(
            {
                "itemId": str(item_id),
                "platform": "8",
                "comboChannel": "2",
                "dmChannel": "damai@damaih5_h5",
            }
        )
        timestamp_ms = str(int(time.time() * 1000))
        params = {
            "jsv": "2.7.5",
            "appKey": MTOP_APP_KEY,
            "t": timestamp_ms,
            "sign": mtop_h5_sign(token, timestamp_ms, request_data),
            "api": MTOP_ITEM_DETAIL_API,
            "v": MTOP_ITEM_DETAIL_VERSION,
            "H5Request": "true",
            "type": "originaljson",
            "timeout": "10000",
            "dataType": "json",
            "valueType": "original",
            "forceAntiCreep": "true",
            "AntiCreep": "true",
            "data": request_data,
        }
        response = await self._client.get(
            MTOP_ITEM_DETAIL_URL,
            params=params,
            follow_redirects=False,
            headers={
                "origin": "https://m.damai.cn",
                "referer": mobile_detail_url(item_id),
            },
        )

        # 正式协议只允许留在大麦 MTop 主机；即使调用方传入了会自动跟随
        # 重定向的 client，也不能把详情请求带到其它站点。
        response_host = (urlparse(str(response.url)).hostname or "").lower()
        if response_host != MTOP_HOST:
            raise MobileDetailError(
                f"移动端详情响应域名异常 host={response_host or '-'}"
            )
        if response.is_redirect:
            raise MobileDetailError(
                f"移动端详情禁止跟随重定向 status={response.status_code}"
            )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise MobileDetailError("移动端详情响应不是有效数据格式") from exc
        if not isinstance(payload, dict):
            raise MobileDetailError("移动端详情响应结构无效")
        return payload

    async def fetch_item_detail(self, item_id: str) -> dict[str, Any]:
        """拉取一个项目；首次访问自动完成 MTop token 握手。"""
        normalized_id = str(item_id or "").strip()
        if not normalized_id.isdigit():
            raise MobileDetailError(f"移动端详情项目编号无效 item={normalized_id!r}")

        token_before = _cookie_token(self._client.cookies)
        payload = await self._request(item_id=normalized_id, token=token_before)
        if _is_success(payload):
            return parse_mobile_item_result(payload, normalized_id)

        token_after = _cookie_token(self._client.cookies)
        if _is_token_error(payload) and token_after and token_after != token_before:
            payload = await self._request(item_id=normalized_id, token=token_after)
            if _is_success(payload):
                return parse_mobile_item_result(payload, normalized_id)

        ret = " | ".join(_ret_values(payload)) or "UNKNOWN"
        raise MobileDetailError(f"移动端详情业务响应失败 ret={ret}")


async def fetch_mobile_item_detail(
    item_id: str,
    *,
    timeout_s: float = 15.0,
) -> dict[str, Any]:
    """用一次短生命周期会话拉取移动详情。"""
    async with DamaiMobileDetailClient(timeout_s=timeout_s) as client:
        return await client.fetch_item_detail(item_id)
