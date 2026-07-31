"""冰拓 1358 双图：表单拼装、图片校验、newslidecaptcha 解析（不默认烧点）。

真实上传：
  BINGTOP_LIVE=1 pytest tests/test_bingtop_1358.py -k live -v
或：
  python scripts/test_bingtop_1358_newslidecaptcha.py --offline
  python scripts/test_bingtop_1358_newslidecaptcha.py --live
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser.captcha.providers import (
    BingtopProvider,
    is_valid_image_b64,
    is_valid_image_bytes,
    to_b64,
)
from app.crawlers.damai.fruit_slider import decode_newslidecaptcha_json
from app.crawlers.damai.fruit_slider import (
    CaptchaPayload,
    ValidationEvent,
    ValidationTracker,
    decode_newslidevalidate_code,
    detect_fruit_slider,
)

ROOT = Path(__file__).resolve().parents[1]
_SAMPLE_PAIRS = [
    (
        ROOT / "data/captcha_probe/bingtop_1358/live_imageData.jpg",
        ROOT / "data/captcha_probe/bingtop_1358/live_ques.png",
    ),
    (
        ROOT / "data/captcha_probe/fruit_live/imageData.jpg",
        ROOT / "data/captcha_probe/fruit_live/ques.png",
    ),
]


def _sample_paths() -> tuple[Path, Path] | None:
    for a, b in _SAMPLE_PAIRS:
        if a.is_file() and b.is_file():
            return a, b
    return None


def _has_samples() -> bool:
    return _sample_paths() is not None


def _samples() -> tuple[bytes, bytes]:
    paths = _sample_paths()
    assert paths is not None
    return paths[0].read_bytes(), paths[1].read_bytes()


@pytest.mark.skipif(not _has_samples(), reason="missing dual-image samples")
def test_samples_are_real_images():
    img, ques = _samples()
    assert is_valid_image_bytes(img)
    assert is_valid_image_bytes(ques, min_size=80)
    assert is_valid_image_b64(to_b64(img))
    assert is_valid_image_b64(to_b64(ques))


def test_refuse_garbage_as_image():
    assert not is_valid_image_bytes(b"17iaz")
    assert not is_valid_image_bytes(b"<html>not image</html>")
    assert not is_valid_image_b64(base64.b64encode(b"not-an-image").decode())


def test_decode_newslidecaptcha_json_roundtrip():
    # 最小合法 JPEG + PNG 魔数即可通过解码；用真实样张若存在
    if _has_samples():
        img, ques = _samples()
        img_b64 = base64.b64encode(img).decode()
        ques_b64 = base64.b64encode(ques).decode()
    else:
        # 1x1 jpeg / png stubs with magics
        img_b64 = base64.b64encode(
            b"\xff\xd8\xff\xe0" + b"\x00" * 300
        ).decode()
        ques_b64 = base64.b64encode(
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 300
        ).decode()

    body = {
        "code": 0,
        "success": True,
        "data": {
            "encryptToken": "abc123token",
            "imageData": img_b64,
            "ques": ques_b64,
        },
    }
    payload = decode_newslidecaptcha_json(json.dumps(body))
    assert payload is not None
    assert payload.encrypt_token == "abc123token"
    assert payload.image_data
    assert payload.ques
    assert is_valid_image_bytes(payload.image_data) or len(payload.image_data) > 200


def test_decode_newslidevalidate_code_requires_zero_result_code():
    assert decode_newslidevalidate_code(
        json.dumps({"code": 0, "success": True, "result": {"code": 0}})
    ) == 0
    assert decode_newslidevalidate_code(
        json.dumps({"code": 306, "success": True, "result": {"code": 306}})
    ) == 306
    assert decode_newslidevalidate_code("not-json") is None


def test_payload_content_key_hashes_the_complete_puzzle():
    left = CaptchaPayload(
        encrypt_token="same",
        image_data=b"same-head" + b"A" * 32 + b"same-tail",
        ques=b"question",
    )
    right = CaptchaPayload(
        encrypt_token="same",
        image_data=b"same-head" + b"B" * 32 + b"same-tail",
        ques=b"question",
    )
    assert len(left.image_data or b"") == len(right.image_data or b"")
    assert left.content_key() != right.content_key()


def test_validation_tracker_only_returns_current_drag_event():
    tracker = ValidationTracker(
        request_seq=3,
        events=[
            ValidationEvent(2, "old", 0, True, 0.4, 272),
            ValidationEvent(4, "current", 0, True, 0.6, 272),
            ValidationEvent(5, "current", 306, True, 0.5, 272),
        ],
    )
    event = tracker.find_event(after_seq=3, puzzle_key="current", expected_per=0.5)
    assert event is not None
    assert event.request_seq == 5
    assert event.code == 306


def test_validation_tracker_rejects_mismatched_token():
    tracker = ValidationTracker(
        request_seq=1,
        events=[ValidationEvent(1, "current", 0, False, 0.5, 272)],
    )
    assert tracker.find_event(after_seq=0, puzzle_key="current", expected_per=0.5) is None


@pytest.mark.asyncio
async def test_detect_fruit_slider_does_not_treat_url_as_visible_ui():
    class FakePage:
        url = "https://search.damai.cn/path/captchacapslidev2"
        frames: list = []

        async def content(self):
            return "<html><body>validation complete</body></html>"

    with patch(
        "app.crawlers.damai.fruit_slider._first_visible",
        AsyncMock(return_value=None),
    ):
        assert not await detect_fruit_slider(FakePage())


@pytest.mark.asyncio
async def test_1358_upload_form_fields():
    """确认 1358 会以 captchaType=1358 + captchaData + subCaptchaData 提交。"""
    if _has_samples():
        img, ques = _samples()
        img_b64 = to_b64(img)
        ques_b64 = to_b64(ques)
    else:
        img_b64 = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 400).decode()
        ques_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 400).decode()

    provider = BingtopProvider("u", "p", fruit_type=1358)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "code": 0,
        "data": {"recognition": "188", "captchaId": "cid-test"},
    }

    captured: dict = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None, **kwargs):
            captured["url"] = url
            captured["data"] = dict(data or {})
            return mock_resp

    with patch(
        "app.browser.captcha.providers.httpx.AsyncClient",
        FakeClient,
    ):
        off = await provider.solve_fruit_offset(img_b64, ques_b64)

    assert off == 188.0
    assert captured["data"]["captchaType"] == 1358
    assert captured["data"]["captchaData"] == img_b64
    assert captured["data"]["subCaptchaData"] == ques_b64
    assert "username" in captured["data"]
    assert "password" in captured["data"]
    assert "ocr/upload" in captured["url"]


@pytest.mark.asyncio
async def test_1358_refuses_missing_sub():
    provider = BingtopProvider("u", "p", fruit_type=1358)
    img_b64 = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 400).decode()
    with patch(
        "app.browser.captcha.providers.httpx.AsyncClient",
        side_effect=AssertionError("must not upload"),
    ):
        off = await provider.solve_fruit_offset(img_b64, "")
    assert off is None


@pytest.mark.asyncio
async def test_1358_refuses_non_image_payload():
    provider = BingtopProvider("u", "p", fruit_type=1358)
    junk = base64.b64encode(b"this-is-not-an-image-blob!!!!!!").decode()
    with patch(
        "app.browser.captcha.providers.httpx.AsyncClient",
        side_effect=AssertionError("must not upload"),
    ):
        off = await provider.solve_fruit_offset(junk, junk)
    assert off is None


@pytest.mark.asyncio
async def test_1358_semantic_error_does_not_resubmit_over_http():
    img, ques = _samples()
    provider = BingtopProvider("u", "p", fruit_type=1358)
    calls: list[str] = []

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "code": 0,
        "data": {"recognition": "error", "captchaId": "cid-rejected"},
    }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None, **kwargs):
            calls.append(url)
            return response

    with patch("app.browser.captcha.providers.httpx.AsyncClient", FakeClient):
        off = await provider.solve_fruit_offset(to_b64(img), to_b64(ques))

    assert off is None
    assert calls == [provider.upload_url]


@pytest.mark.parametrize(
    "body",
    [
        {"code": 401, "success": True, "data": {"recognition": "188"}},
        {"code": 0, "success": False, "data": {"recognition": "188"}},
    ],
)
def test_1358_rejects_explicit_provider_failure(body):
    provider = BingtopProvider("u", "p", fruit_type=1358)
    assert provider._parse_recognition(body, captcha_type=1358, url=provider.upload_url) is None


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("BINGTOP_LIVE") != "1", reason="set BINGTOP_LIVE=1 to burn points")
@pytest.mark.skipif(not _has_samples(), reason="missing samples")
async def test_live_1358_offline_samples():
    """用本地真实 imageData/ques 打一枪 1358（消耗约 2 点）。"""
    from app.core.config import load_config

    cfg = load_config()
    user = cfg.captcha.username or os.environ.get("DAXI_CAPTCHA_USERNAME", "")
    pwd = cfg.captcha.password or os.environ.get("DAXI_CAPTCHA_PASSWORD", "")
    if not user or not pwd:
        pytest.skip("no bingtop credentials")

    img, ques = _samples()
    p = BingtopProvider(user, pwd, fruit_type=1358)
    off = await p.solve_fruit_offset(to_b64(img), to_b64(ques))
    assert off is not None
    assert 0 <= off <= 400
