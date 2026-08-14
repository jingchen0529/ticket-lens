"""大麦官方移动端详情 MTop 协议。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.crawlers.damai.mobile_detail import (
    DamaiMobileDetailClient,
    MobileDetailError,
    MTOP_HOST,
    MTOP_ITEM_DETAIL_API,
    mobile_detail_url,
    mtop_h5_sign,
    parse_mobile_item_result,
)


ITEM_ID = "1073716080825"


def _success_payload() -> dict:
    result = {
        "detailViewComponentMap": {
            "item": {
                "staticData": {
                    "itemBase": {
                        "itemId": ITEM_ID,
                        "itemName": "【北京】音乐剧《大江东去》",
                    }
                },
                "item": {"performCount": "3"},
            }
        }
    }
    return {
        "ret": ["SUCCESS::调用成功"],
        "data": {"result": json.dumps(result, ensure_ascii=False)},
    }


def test_mtop_h5_sign_matches_captured_mobile_request():
    data = (
        '{"itemId":"1073716080825","platform":"8","comboChannel":"2",'
        '"dmChannel":"damai@damaih5_h5"}'
    )

    assert mtop_h5_sign(
        "7b7e4df74ac9ffb65f849df5f5ee8ff1",
        "1786527823408",
        data,
    ) == "b5c591b4af9c3fa6f12b94668a0247e3"


def test_mobile_result_rejects_wrong_item_id():
    payload = _success_payload()
    result = json.loads(payload["data"]["result"])
    result["detailViewComponentMap"]["item"]["staticData"]["itemBase"][
        "itemId"
    ] = "1056876653291"
    payload["data"]["result"] = json.dumps(result, ensure_ascii=False)

    with pytest.raises(MobileDetailError, match="项目编号不匹配"):
        parse_mobile_item_result(payload, ITEM_ID)


@pytest.mark.asyncio
async def test_mobile_client_bootstraps_token_and_stays_on_damai_hosts():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"ret": ["FAIL_SYS_TOKEN_EMPTY::令牌为空"]},
                headers={
                    "set-cookie": (
                        "_m_h5_tk=mobile-token_1786530000000; "
                        "Domain=.damai.cn; Path=/; HttpOnly"
                    )
                },
            )
        return httpx.Response(200, json=_success_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as http:
        client = DamaiMobileDetailClient(client=http)
        result = await client.fetch_item_detail(ITEM_ID)

    assert result["detailViewComponentMap"]["item"]["item"]["performCount"] == "3"
    assert len(requests) == 2
    assert {request.url.host for request in requests} == {MTOP_HOST}
    assert all(request.url.params["api"] == MTOP_ITEM_DETAIL_API for request in requests)
    assert all(
        request.headers["referer"] == mobile_detail_url(ITEM_ID)
        for request in requests
    )
    second = requests[1]
    assert second.url.params["sign"] == mtop_h5_sign(
        "mobile-token",
        second.url.params["t"],
        second.url.params["data"],
    )


@pytest.mark.asyncio
async def test_mobile_client_never_follows_redirects():
    requested_hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(
            302,
            headers={"location": "https://example.invalid/redirected"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as http:
        client = DamaiMobileDetailClient(client=http)
        with pytest.raises(MobileDetailError, match="禁止跟随重定向"):
            await client.fetch_item_detail(ITEM_ID)

    assert requested_hosts == [MTOP_HOST]
