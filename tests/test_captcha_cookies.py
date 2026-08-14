"""验证码浏览器状态的域隔离。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import orjson
import pytest

from app.browser.captcha.cookies import (
    filter_storage_state,
    load_storage_state,
    save_storage_state,
)


def _mixed_state() -> dict:
    return {
        "cookies": [
            {"name": "root", "value": "1", "domain": ".damai.cn"},
            {"name": "search", "value": "2", "domain": "search.damai.cn"},
            {"name": "taobao", "value": "3", "domain": ".taobao.com"},
            {"name": "fake", "value": "4", "domain": "damai.cn.evil.example"},
        ],
        "origins": [
            {"origin": "https://search.damai.cn", "localStorage": []},
            {"origin": "https://login.taobao.com", "localStorage": []},
            {"origin": "https://damai.cn.evil.example", "localStorage": []},
        ],
    }


def test_filter_storage_state_keeps_only_exact_domain_or_subdomain():
    filtered = filter_storage_state(_mixed_state(), ("damai.cn",))

    assert [cookie["name"] for cookie in filtered["cookies"]] == ["root", "search"]
    assert [origin["origin"] for origin in filtered["origins"]] == [
        "https://search.damai.cn"
    ]


@pytest.mark.asyncio
async def test_load_storage_state_filters_existing_pollution(tmp_path):
    path = tmp_path / "damai_storage.json"
    path.write_bytes(orjson.dumps(_mixed_state()))

    state = await load_storage_state(path, allowed_domains=("damai.cn",))

    assert state is not None
    assert [cookie["name"] for cookie in state["cookies"]] == ["root", "search"]
    assert len(state["origins"]) == 1


@pytest.mark.asyncio
async def test_save_storage_state_never_persists_taobao_for_damai(tmp_path):
    path = tmp_path / "damai_storage.json"
    context = AsyncMock()
    context.storage_state.return_value = _mixed_state()

    await save_storage_state(
        context,
        path,
        allowed_domains=("damai.cn",),
    )

    saved = orjson.loads(path.read_bytes())
    assert [cookie["name"] for cookie in saved["cookies"]] == ["root", "search"]
    assert [origin["origin"] for origin in saved["origins"]] == [
        "https://search.damai.cn"
    ]
    context.storage_state.assert_awaited_once_with()
