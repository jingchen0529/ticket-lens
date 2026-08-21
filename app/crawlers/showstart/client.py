"""秀动签名 HTTP API 客户端。"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import string
import time
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("crawler.showstart.client")

_BASE_URL = "https://www.showstart.com"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_ALPHABET = string.digits + string.ascii_uppercase + string.ascii_lowercase
_DEVICE_INFO = {
    "vendorName": "",
    "deviceMode": "",
    "deviceName": "",
    "systemName": "",
    "systemVersion": "",
    "cpuMode": " ",
    "cpuCores": "",
    "cpuArch": "",
    "memerySize": "",
    "diskSize": "",
    "network": "",
    "resolution": "1920*1080",
    "pixelResolution": "",
}


class ShowstartClient:
    """秀动签名 HTTP API 客户端。"""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http_client = http_client
        self._owns_client = http_client is None
        self._access_token = ""
        self._cookies = {"token": self._make_device_token()}

    @staticmethod
    def _md5(value: str) -> str:
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _random_chars(length: int) -> str:
        return "".join(random.choice(_ALPHABET) for _ in range(length))

    @classmethod
    def _make_device_token(cls) -> str:
        seed = cls._random_chars(32) + str(int(time.time() * 1000))
        return cls._md5(seed)

    @classmethod
    def _make_nonce(cls) -> str:
        return cls._random_chars(32) + str(int(time.time() * 1000))

    @staticmethod
    def _signature(
        *,
        cusat: str,
        device_token: str,
        body_str: str,
        request_path: str,
        trace_id: str,
    ) -> str:
        source = cusat + "web" + device_token + body_str + request_path + "999web" + trace_id
        return ShowstartClient._md5(source)

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=_BASE_URL,
                timeout=20.0,
                trust_env=True,
            )
        return self._http_client

    def _headers(self, path: str, body_str: str, cusat: str, trace_id: str) -> dict[str, str]:
        device_token = self._cookies["token"]
        return {
            "cdeviceinfo": quote(json.dumps(_DEVICE_INFO, separators=(",", ":"))),
            "cdeviceno": device_token,
            "cookie": "; ".join(f"{key}={value}" for key, value in self._cookies.items()),
            "crpsign": self._signature(
                cusat=cusat,
                device_token=device_token,
                body_str=body_str,
                request_path=path,
                trace_id=trace_id,
            ),
            "crtraceid": trace_id,
            "csappid": "web",
            "cterminal": "web",
            "cusat": cusat,
            "cusid": "",
            "cusit": "",
            "cusname": "",
            "cusut": "",
            "cversion": "999",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": _USER_AGENT,
            "Origin": _BASE_URL,
            "Referer": f"{_BASE_URL}/",
        }

    async def _send(self, path: str, payload: dict[str, str] | None, cusat: str) -> dict[str, Any]:
        body_str = (
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            if payload is not None
            else ""
        )
        trace_id = self._make_nonce()
        response = await self._client().post(
            f"/api{path}",
            content=body_str.encode("utf-8"),
            headers=self._headers(path, body_str, cusat, trace_id),
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _is_success(response: dict[str, Any]) -> bool:
        return str(response.get("state")) == "1"

    @staticmethod
    def _failure(response: dict[str, Any]) -> RuntimeError:
        return RuntimeError(str(response.get("msg") or "showstart API request failed"))

    async def _bootstrap(self) -> None:
        throwaway = self._md5(str(int(time.time() * 1000)))
        response = await self._send("/waf/gettoken", None, throwaway)
        if not self._is_success(response):
            raise self._failure(response)
        result = response["result"]
        self._access_token = str(result["accessToken"]["access_token"])
        self._cookies["accessToken"] = self._access_token
        self._cookies["idToken"] = str(result["idToken"]["id_token"])

    async def post(self, path: str, payload: dict[str, str] | None = None) -> Any:
        if not self._access_token:
            await self._bootstrap()
        response = await self._send(path, payload, self._access_token)
        if self._is_success(response):
            return response.get("result")
        logger.warning("showstart API business failure; refreshing token path=%s", path)
        await self._bootstrap()
        response = await self._send(path, payload, self._access_token)
        if not self._is_success(response):
            raise self._failure(response)
        return response.get("result")

    async def list_params(self) -> list[dict[str, Any]]:
        return await self.post("/web/activity/list/params")

    async def activity_list(
        self,
        *,
        page_no: int,
        city_code: str,
        show_style: str = "",
        keyword: str = "",
        sort_type: str = "2",
    ) -> dict[str, Any]:
        payload = {
            "pageNo": str(page_no),
            "pageSize": "30",
            "cityCode": str(city_code),
            "sortType": sort_type,
        }
        if show_style:
            payload["showStyle"] = show_style
        if keyword:
            payload["keyword"] = keyword
        return await self.post("/web/activity/list", payload)

    async def activity_info(self, activity_id: str) -> dict[str, Any]:
        return await self.post("/web/activity/info", {"activityId": str(activity_id)})

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
