"""水果滑块完整度打分 / 目标解析（离线，不启浏览器）。"""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from PIL import Image

import app.crawlers.damai.fruit_slider as fruit_slider
from app.crawlers.damai.fruit_slider import (
    CaptchaPayload,
    ValidationEvent,
    build_focus_boxes,
    find_best_offset_by_scores,
    parse_target_from_text,
    score_completeness,
    segment_objects,
)  # noqa: I001


def _to_png(arr: np.ndarray) -> bytes:
    buf = BytesIO()
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


def _payload(color: int) -> CaptchaPayload:
    main = np.full((180, 320, 3), color, dtype=np.uint8)
    ques = np.full((30, 288, 3), color, dtype=np.uint8)
    return CaptchaPayload(
        encrypt_token=f"token-{color}",
        image_data=_to_png(main),
        ques=_to_png(ques),
    )


def _patch_provider_loop(monkeypatch, *, geometry):
    monkeypatch.setattr(
        fruit_slider, "attach_payload_listener", AsyncMock(return_value=lambda: None)
    )
    monkeypatch.setattr(
        fruit_slider, "attach_validation_listener", AsyncMock(return_value=lambda: None)
    )
    monkeypatch.setattr(fruit_slider, "wait_fruit_slider", AsyncMock(return_value=True))
    monkeypatch.setattr(fruit_slider, "detect_fruit_slider", AsyncMock(return_value=True))
    monkeypatch.setattr(fruit_slider, "measure_geometry", geometry)
    monkeypatch.setattr(fruit_slider, "enrich_payload", lambda payload: payload)
    return SimpleNamespace(wait_for_timeout=AsyncMock())


@pytest.mark.asyncio
async def test_provider_preparation_attempts_are_bounded_without_paid_call(monkeypatch):
    geometry = AsyncMock(return_value=None)
    page = _patch_provider_loop(monkeypatch, geometry=geometry)
    provider = SimpleNamespace(
        fruit_type=1358,
        DUAL_IMAGE_TYPES=frozenset({1358}),
        solve_fruit_offset=AsyncMock(return_value=128.0),
    )

    solved = await fruit_slider.solve_by_provider_offset(
        page,
        provider,
        payload_hint=_payload(80),
        max_rounds=3,
        wait_timeout_s=0,
    )

    assert solved is False
    assert geometry.await_count == 5
    provider.solve_fruit_offset.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_none_refreshes_and_retries_up_to_paid_budget(monkeypatch):
    geo = SimpleNamespace(
        max_slide=272.0,
        image_box={"width": 320.0},
        track_box={"width": 320.0},
        button_box={"width": 48.0},
    )
    geometry = AsyncMock(return_value=geo)
    page = _patch_provider_loop(monkeypatch, geometry=geometry)

    payload_count = [0]
    async def fake_attach_payload(_page, sink):
        page._sink = sink
        return lambda: None

    async def fake_click_refresh(_page):
        payload_count[0] += 1
        if hasattr(page, "_sink") and page._sink is not None:
            page._sink.append(_payload(100 + payload_count[0]))

    monkeypatch.setattr(fruit_slider, "attach_payload_listener", fake_attach_payload)
    monkeypatch.setattr(fruit_slider, "_click_refresh", fake_click_refresh)

    provider = SimpleNamespace(
        fruit_type=1358,
        DUAL_IMAGE_TYPES=frozenset({1358}),
        solve_fruit_offset=AsyncMock(return_value=None),
    )

    solved = await fruit_slider.solve_by_provider_offset(
        page,
        provider,
        payload_hint=_payload(100),
        max_rounds=3,
        wait_timeout_s=0,
    )

    assert solved is False
    assert provider.solve_fruit_offset.call_count == 3


@pytest.mark.asyncio
async def test_paid_attempt_is_consumed_when_puzzle_changes_during_provider_call(monkeypatch):
    geo = SimpleNamespace(
        max_slide=272.0,
        image_box={"width": 320.0},
        track_box={"width": 320.0},
        button_box={"width": 48.0},
    )
    page = _patch_provider_loop(monkeypatch, geometry=AsyncMock(return_value=geo))
    replacement = _payload(140)
    payload_sink = None

    async def attach_payload(_page, sink):
        nonlocal payload_sink
        payload_sink = sink
        return lambda: None

    async def solve_and_replace(_image, _question):
        assert payload_sink is not None
        payload_sink.append(replacement)
        return 148.0

    monkeypatch.setattr(fruit_slider, "attach_payload_listener", attach_payload)
    drag = AsyncMock(return_value={})
    monkeypatch.setattr(fruit_slider, "drag_to_offset", drag)
    provider = SimpleNamespace(
        fruit_type=1358,
        DUAL_IMAGE_TYPES=frozenset({1358}),
        solve_fruit_offset=AsyncMock(side_effect=solve_and_replace),
    )

    solved = await fruit_slider.solve_by_provider_offset(
        page,
        provider,
        payload_hint=_payload(120),
        max_rounds=1,
        wait_timeout_s=0,
    )

    assert solved is False
    provider.solve_fruit_offset.assert_awaited_once()
    drag.assert_not_awaited()


@pytest.mark.asyncio
async def test_1358_uses_protocol_edge_and_accepts_correlated_validate(monkeypatch):
    geo = SimpleNamespace(
        max_slide=280.0,
        image_box={"width": 320.0},
        track_box={"width": 320.0},
        # A responsive DOM knob width must not change the 24px protocol edge.
        button_box={"width": 40.0},
    )
    page = _patch_provider_loop(monkeypatch, geometry=AsyncMock(return_value=geo))
    tracker = None

    async def attach_validation(_page, active_tracker):
        nonlocal tracker
        tracker = active_tracker
        return lambda: None

    async def drag(_page, _geo, offset, **kwargs):
        # raw=148 → ui = 148 - 24 + margin(8) = 132
        assert offset == pytest.approx(132.0)
        assert await kwargs["before_mouse_down"]()
        assert await kwargs["before_mouse_up"]()
        assert tracker is not None
        tracker.request_seq += 1
        tracker.events.append(
            ValidationEvent(
                tracker.request_seq,
                tracker.armed_puzzle_key,
                0,
                True,
                # Deliberately differs from local DOM-derived diagnostics.
                0.9,
                280.0,
                True,
            )
        )
        return {"mouse_dx": offset, "knob_dx": offset, "track_sum_dx": offset}

    monkeypatch.setattr(fruit_slider, "attach_validation_listener", attach_validation)
    monkeypatch.setattr(fruit_slider, "drag_to_offset", drag)
    provider = SimpleNamespace(
        fruit_type=1358,
        DUAL_IMAGE_TYPES=frozenset({1358}),
        solve_fruit_offset=AsyncMock(return_value=148.0),
    )

    solved = await fruit_slider.solve_by_provider_offset(
        page,
        provider,
        payload_hint=_payload(160),
        max_rounds=1,
        wait_timeout_s=0,
    )

    assert solved is True
    provider.solve_fruit_offset.assert_awaited_once()


def test_score_completeness_on_captured_image():
    img = Path("data/captcha_probe/deep2/img_5__data_imageData.jpg")
    if not img.exists():
        return
    score = score_completeness(img.read_bytes())
    assert score > 0
    assert score < 1e17


def test_find_best_offset():
    samples = [(0, 50), (10, 40), (20, 12), (30, 35), (40, 48)]
    best = find_best_offset_by_scores(samples)
    assert 15 <= best <= 25


def test_score_prefers_smooth_image():
    smooth = np.full((80, 160, 3), 220, dtype=np.uint8)
    smooth[:, 40:80] = [180, 100, 90]
    cut = smooth.copy()
    cut[:, 79:81] = 0

    s_smooth = score_completeness(_to_png(smooth))
    s_cut = score_completeness(_to_png(cut))
    assert s_cut > s_smooth


def test_score_finds_hcut_zero():
    """上下半幅水平错位：0 偏移应最低分。"""
    path = Path("data/captcha_probe/score_debug/0_imageData.jpg")
    if not path.exists():
        path = Path("data/captcha_probe/deep2/img_5__data_imageData.jpg")
    if not path.exists():
        return
    arr = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    h, w, _ = arr.shape
    mid = h // 2
    samples: list[tuple[float, float]] = []
    for off in range(-30, 31, 5):
        out = arr.copy()
        bot = np.roll(arr[mid:], int(off), axis=1)
        out[mid:] = bot
        samples.append((float(off), score_completeness(_to_png(out))))
    best = find_best_offset_by_scores(samples)
    assert abs(best) <= 5, f"hcut best={best} samples={samples}"


def test_score_focus_on_hat_region():
    path = Path("data/captcha_probe/score_debug/0_imageData.jpg")
    if not path.exists():
        return
    raw = path.read_bytes()
    boxes = build_focus_boxes(raw, "帽子", 1)
    assert boxes, "expected hat focus box"
    # 帽子 ROI 应落在图下半（样本布局）
    assert boxes[0][1] > 60

    arr = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    h, _w, _ = arr.shape
    mid = h // 2
    samples = []
    for off in range(-25, 26, 5):
        out = arr.copy()
        out[mid:] = np.roll(arr[mid:], int(off), axis=1)
        samples.append((float(off), score_completeness(_to_png(out), focus_boxes=boxes)))
    best = find_best_offset_by_scores(samples)
    assert abs(best) <= 7, f"focus hcut best={best}"


def test_parse_target_from_text():
    name, cnt = parse_target_from_text("拖动滑块出现完整的一个帽子后就松开")
    assert name == "帽子"
    assert cnt == 1
    name, cnt = parse_target_from_text("拖动滑块出现完整的两个松鼠后就松开")
    assert name == "松鼠"
    assert cnt == 2
    name, cnt = parse_target_from_text("拖动滑块出现完整的两个大象后就松开")
    assert name == "大象"
    assert cnt == 2
    name, cnt = parse_target_from_text("拖动滑块出现完整的一个凤梨后就松开")
    assert name == "凤梨"
    assert cnt == 1
    name, cnt = parse_target_from_text("拖动滑块出现完整的两个包后就松开")
    assert name == "包"
    assert cnt == 2
    name, cnt = parse_target_from_text("拖动滑块出现完整的一个冰激凌后就松开")
    assert name == "冰激凌"
    assert cnt == 1


def test_segment_objects_on_sample():
    path = Path("data/captcha_probe/score_debug/0_imageData.jpg")
    if not path.exists():
        return
    blobs = segment_objects(path.read_bytes())
    assert len(blobs) >= 4
    # 合理 bbox
    for b in blobs:
        assert b.x1 > b.x0
        assert b.y1 > b.y0
        assert b.area > 100


def test_score_finds_strip_and_interleave_zero():
    """条带 / 交错错位：0 偏移应接近最低分。"""
    path = Path("data/captcha_probe/score_debug/0_imageData.jpg")
    if not path.exists():
        return
    arr = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    h, _w, _ = arr.shape
    boxes = build_focus_boxes(path.read_bytes(), "帽子", 1)

    def strip(off: int, sh: int = 12) -> np.ndarray:
        out = arr.copy()
        for y0 in range(0, h, sh * 2):
            y1 = min(h, y0 + sh)
            out[y0:y1] = np.roll(arr[y0:y1], int(off), axis=1)
        return out

    def interleave(off: int, nband: int = 6) -> np.ndarray:
        out = arr.copy()
        bh = max(4, h // nband)
        for i, y0 in enumerate(range(0, h, bh)):
            y1 = min(h, y0 + bh)
            sign = 1 if i % 2 == 0 else -1
            out[y0:y1] = np.roll(arr[y0:y1], int(off) * sign, axis=1)
        return out

    for name, fn in (("strip", strip), ("interleave", interleave)):
        samples = []
        for off in range(-24, 25, 4):
            samples.append(
                (float(off), score_completeness(_to_png(fn(off)), focus_boxes=boxes))
            )
        best = find_best_offset_by_scores(samples)
        assert abs(best) <= 6, f"{name} best={best} samples={samples}"
