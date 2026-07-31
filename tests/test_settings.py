from __future__ import annotations

import ssl

import httpx
import pytest
import yaml

from app.routers import settings


def test_saving_bingtop_credentials_enables_provider_first(monkeypatch, tmp_path):
    frontend_path = tmp_path / "frontend_settings.yaml"
    config_path = tmp_path / "configs" / "default.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "captcha": {
                    "provider": "bingtop",
                    "fruit_strategy": "local_first",
                    "fruit_max_rounds": 2,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "_settings_path", lambda: frontend_path)

    from app.core import paths

    monkeypatch.setattr(paths, "config_path", lambda: config_path)
    req = settings.SettingsData(
        bingtuo=settings.BingtuoCredentials(username="demo", password="secret"),
        captcha_mode="auto",
    )

    result = settings.update_settings(req)
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert result["success"] is True
    assert saved["captcha"]["fruit_strategy"] == "provider_first"
    assert saved["captcha"]["fruit_max_rounds"] == 3


async def test_bingtop_balance_uses_bundled_ca_without_environment(monkeypatch):
    captured: dict = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "data": {"points": 321}}

    class AsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, *, data):
            captured["url"] = url
            captured["data"] = data
            return Response()

    monkeypatch.setattr(
        settings,
        "_load_settings",
        lambda: settings.SettingsData(
            bingtuo=settings.BingtuoCredentials(username="demo", password="secret")
        ),
    )
    monkeypatch.setattr(httpx, "AsyncClient", AsyncClient)
    monkeypatch.setenv("SSL_CERT_FILE", "/missing/cert.pem")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")

    result = await settings.get_bingtuo_balance()

    assert result == {"configured": True, "points": 321, "error": ""}
    assert isinstance(captured["verify"], ssl.SSLContext)
    assert captured["trust_env"] is False
    assert captured["data"] == {"username": "demo", "password": "secret"}


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("", ""),
        ("demo", ""),
        ("", "secret"),
        ("   ", "\t"),
    ],
)
async def test_bingtop_balance_requires_complete_credentials(
    monkeypatch, username, password
):
    class UnexpectedClient:
        def __init__(self, **kwargs):
            raise AssertionError("未配置完整凭据时不应请求冰拓")

    monkeypatch.setattr(
        settings,
        "_load_settings",
        lambda: settings.SettingsData(
            bingtuo=settings.BingtuoCredentials(
                username=username,
                password=password,
            )
        ),
    )
    monkeypatch.setattr(httpx, "AsyncClient", UnexpectedClient)

    result = await settings.get_bingtuo_balance()

    assert result == {
        "configured": False,
        "points": None,
        "error": "未配置冰拓账号",
    }


async def test_bingtop_balance_returns_transport_error(monkeypatch):
    class AsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            raise httpx.ConnectError("连接超时")

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr(
        settings,
        "_load_settings",
        lambda: settings.SettingsData(
            bingtuo=settings.BingtuoCredentials(username="demo", password="secret")
        ),
    )
    monkeypatch.setattr(httpx, "AsyncClient", AsyncClient)

    result = await settings.get_bingtuo_balance()

    assert result == {"configured": True, "points": None, "error": "查询失败: 连接超时"}
