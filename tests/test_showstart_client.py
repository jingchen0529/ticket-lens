"""Showstart signed HTTP client behavior."""

from importlib import import_module

import httpx
import pytest

from app.core.config import AppConfig
from app.crawlers.showstart.client import ShowstartClient
from app.models import CrawlJob, SourcePlatform


def test_signature_is_deterministic_for_exact_body_bytes():
    signature = ShowstartClient._signature(
        cusat="access-token",
        device_token="device-token",
        body_str='{"pageNo":"1","cityCode":"10"}',
        request_path="/web/activity/list",
        trace_id="trace-id",
    )

    assert signature == "206673d84f8577189009e941f09090ae"


@pytest.mark.asyncio
async def test_business_failure_refreshes_token_and_retries_once(monkeypatch):
    requests: list[httpx.Request] = []
    token_calls = 0
    list_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, list_calls
        requests.append(request)
        if request.url.path == "/api/waf/gettoken":
            token_calls += 1
            return httpx.Response(
                200,
                json={
                    "state": 1,
                    "status": 200,
                    "result": {
                        "accessToken": {"access_token": f"access-{token_calls}"},
                        "idToken": {"id_token": f"id-{token_calls}"},
                    },
                },
            )
        list_calls += 1
        if list_calls == 1:
            return httpx.Response(200, json={"state": "sys001", "msg": "expired"})
        return httpx.Response(
            200,
            json={"state": "1", "status": 200, "result": [{"cityName": "北京"}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://www.showstart.com",
    ) as http_client:
        client = ShowstartClient(http_client=http_client)
        monkeypatch.setattr(client, "_make_nonce", lambda: "fixed-trace")
        result = await client.list_params()

    assert result == [{"cityName": "北京"}]
    assert [request.url.path for request in requests] == [
        "/api/waf/gettoken",
        "/api/web/activity/list/params",
        "/api/waf/gettoken",
        "/api/web/activity/list/params",
    ]
    assert requests[0].content == b""
    assert requests[-1].headers["cusat"] == "access-2"
    assert requests[-1].headers["cookie"].endswith("accessToken=access-2; idToken=id-2")


@pytest.mark.asyncio
async def test_captcha_solver_is_a_noop():
    module = import_module("app.crawlers.showstart.captcha")
    solver = module.ShowstartCaptchaSolver(AppConfig())

    challenge = await solver.detect(None)
    result = await solver.solve_auto(None, None)

    assert challenge is None
    assert result.ok is True
    assert result.method == "skipped"


def test_showstart_is_a_default_source():
    assert SourcePlatform.SHOWSTART.value == "showstart"
    assert SourcePlatform.SHOWSTART in CrawlJob().sources
