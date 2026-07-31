"""对照图 / A/B 网格离线渲染测试。"""

from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.crawlers.damai.fruit_probe import (
    default_ab_candidates,
    render_ab_grid,
    render_compare_image,
    write_probe_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]
LIVE_IMG = ROOT / "data/captcha_probe/bingtop_1358/live_imageData.jpg"
LIVE_QUES = ROOT / "data/captcha_probe/bingtop_1358/live_ques.png"


def _solid_png(w: int = 320, h: int = 180, color=(200, 180, 160)) -> bytes:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :] = color
    # 画一个“目标”块在 x=100..140
    arr[40:120, 100:140] = (40, 120, 200)
    buf = BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def _ques_png() -> bytes:
    arr = np.full((30, 288, 3), 240, dtype=np.uint8)
    buf = BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def test_default_ab_candidates_marks_right_edge_selected():
    from app.crawlers.damai.fruit_slider import FRUIT_REVEAL_MARGIN_PX

    cands = default_ab_candidates(148.0, max_slide=272.0)
    keys = [c.key for c in cands]
    assert "A_right_edge" in keys
    assert "B_raw" in keys
    a = next(c for c in cands if c.key == "A_right_edge")
    b = next(c for c in cands if c.key == "B_raw")
    assert a.selected is True
    assert b.selected is False
    # ui = raw - 24 + margin
    assert a.ui_x == pytest.approx(148.0 - 24.0 + FRUIT_REVEAL_MARGIN_PX)
    assert b.ui_x == pytest.approx(148.0)
    assert a.reveal_x == pytest.approx(a.ui_x + 24.0)


def test_render_compare_and_ab_grid_synthetic():
    img = _solid_png()
    ques = _ques_png()
    cmp = render_compare_image(
        img,
        raw_off=148.0,
        ui_x=124.0,
        ques=ques,
        validate_code=300,
        target_name="马",
    )
    assert cmp[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(cmp) > 500

    cands = default_ab_candidates(148.0, max_slide=272.0, offline_ui=110.0)
    grid = render_ab_grid(
        img,
        cands,
        ques=ques,
        validate_code=300,
        raw_off=148.0,
    )
    assert grid[:8] == b"\x89PNG\r\n\x1a\n"
    g = Image.open(BytesIO(grid))
    assert g.size[0] > 300
    assert g.size[1] > 200


def test_write_probe_artifacts_code0_indexes_success(tmp_path: Path):
    img = _solid_png()
    ques = _ques_png()
    meta = write_probe_artifacts(
        tmp_path,
        image_data=img,
        ques=ques,
        raw_off=100.0,
        ui_x=76.0,
        max_slide=272.0,
        validate_code=0,
        target_name="帽子",
        mouse_dx=76.0,
        knob_dx=76.0,
        img_key="abc123",
    )
    assert meta.validate_code == 0
    assert (tmp_path / "last_compare.png").exists()
    assert (tmp_path / "last_ab_grid.png").exists()
    assert (tmp_path / "last_drag_compare.json").exists()
    assert (tmp_path / "success_history.jsonl").exists()
    assert "compare" in meta.paths
    assert "ab_grid" in meta.paths


def test_write_probe_artifacts_nonzero_code_no_success_file(tmp_path: Path):
    img = _solid_png()
    write_probe_artifacts(
        tmp_path,
        image_data=img,
        ques=None,
        raw_off=171.0,
        ui_x=147.0,
        max_slide=272.0,
        validate_code=300,
    )
    assert (tmp_path / "last_compare.png").exists()
    assert not (tmp_path / "success_history.jsonl").exists()


@pytest.mark.skipif(not LIVE_IMG.exists(), reason="missing live sample")
def test_render_on_live_sample(tmp_path: Path):
    img = LIVE_IMG.read_bytes()
    ques = LIVE_QUES.read_bytes() if LIVE_QUES.exists() else None
    # live_result offset=191 for 马
    meta = write_probe_artifacts(
        tmp_path,
        image_data=img,
        ques=ques,
        raw_off=191.0,
        ui_x=167.0,
        max_slide=272.0,
        validate_code=None,
        target_name="马",
        round_i=0,
        img_key="live-sample",
    )
    assert (tmp_path / "last_compare.png").exists()
    assert (tmp_path / "last_ab_grid.png").exists()
    g = Image.open(tmp_path / "last_ab_grid.png")
    assert g.size[0] >= 320
    assert meta.candidates
    assert any(c["selected"] for c in meta.candidates)
