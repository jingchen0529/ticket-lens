"""水果滑块人工对照产物：对照图 + A/B 网格。

在 DAXI_CAPTCHA_PROBE=1 时落盘，帮助判断：
  - 冰拓 recognition 是否落在目标物体右缘
  - right_edge (raw-24) vs raw 等映射谁更合理
  - 官方 validate code 是否终于到 0

不参与打码计费；纯本地 PIL 渲染。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# 对照色：raw / 实际拖动 ui / 协议露出右缘
COLOR_RAW = (255, 64, 64)  # 红：冰拓 recognition（目标右缘语义）
COLOR_UI = (32, 180, 72)  # 绿：实际计划拖动 ui_x
COLOR_REVEAL = (40, 120, 255)  # 蓝：ui_x + 24 露出右缘
COLOR_ALT = (255, 170, 0)  # 橙：A/B 候选
COLOR_LABEL_BG = (0, 0, 0, 170)


@dataclass
class ProbeCandidate:
    """A/B 网格中的一个映射候选。"""

    key: str
    label: str
    ui_x: float
    reveal_x: float
    note: str = ""
    selected: bool = False


@dataclass
class ProbeMeta:
    """一次拖动对照的元数据（与 JSON 同步）。"""

    ts: float = field(default_factory=time.time)
    round: int = 0
    raw_bingtop: float | None = None
    logic_w: float = 320.0
    ui_width: float = 320.0
    ui_x: float = 0.0
    reveal_x: float = 0.0
    map_mode: str = "fruit_right_edge"
    max_slide: float = 272.0
    mouse_dx: float | None = None
    knob_dx: float | None = None
    track_sum_dx: float | None = None
    delta_mouse: float | None = None
    delta_knob: float | None = None
    validate_code: int | None = None
    protocol_per: float | None = None
    actual_per: float | None = None
    validate_width: float | None = None
    token_matches: bool | None = None
    drag_duration_ms: float | None = None
    has_token: bool = False
    img_key: str = ""
    target_name: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _font(size: int = 14) -> ImageFont.ImageFont:
    # 优先系统中文字体，失败退回默认位图字体
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _load_rgb(data: bytes) -> Image.Image:
    im = Image.open(BytesIO(data))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")
    return im


def _png_bytes(im: Image.Image) -> bytes:
    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_v_line(
    draw: ImageDraw.ImageDraw,
    x: float,
    h: int,
    color: tuple[int, int, int],
    *,
    width: int = 2,
    dashed: bool = False,
) -> None:
    xi = int(round(x))
    if dashed:
        y = 0
        while y < h:
            draw.line([(xi, y), (xi, min(h - 1, y + 6))], fill=color, width=width)
            y += 12
    else:
        draw.line([(xi, 0), (xi, h - 1)], fill=color, width=width)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return int(box[2] - box[0]), int(box[3] - box[1])


def _label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fg: tuple[int, int, int] = (255, 255, 255),
    bg: tuple[int, int, int, int] = COLOR_LABEL_BG,
) -> None:
    tw, th = _text_size(draw, text, font)
    x, y = xy
    pad = 3
    draw.rectangle([x, y, x + tw + pad * 2, y + th + pad * 2], fill=bg)
    draw.text((x + pad, y + pad), text, fill=fg, font=font)


def default_ab_candidates(
    raw_off: float,
    *,
    max_slide: float,
    image_width: float = 320.0,
    ui_width: float = 320.0,
    edge_pad: float = 24.0,
    selected_key: str = "A_right_edge",
    offline_ui: float | None = None,
) -> list[ProbeCandidate]:
    """生成标准 A/B 候选集合。

    A 当前默认：right_edge = raw*scale - 24
    B 诊断 raw：recognition 直接当 UI
    C 本地 prior 余量：right_edge + 4
    D 半前缘：raw*scale - 12
    E 更深前缘：raw*scale - 36
    F 可选 offline prior（本地 ROI）
    """
    from app.browser.captcha.providers import map_bingtop_fruit_offset_to_ui

    def edge(margin: float = 0.0) -> float:
        return map_bingtop_fruit_offset_to_ui(
            float(raw_off),
            max_slide=max_slide,
            image_width=image_width,
            ui_width=ui_width,
            edge_pad=edge_pad,
            margin=margin,
            style="right_edge",
        )

    def raw_style() -> float:
        return map_bingtop_fruit_offset_to_ui(
            float(raw_off),
            max_slide=max_slide,
            image_width=image_width,
            ui_width=ui_width,
            edge_pad=edge_pad,
            style="raw",
        )

    scale = (ui_width / image_width) if image_width > 1 else 1.0
    display_raw = float(raw_off) * scale

    # A 与线上一致：raw-24+margin（默认 margin 见 FRUIT_REVEAL_MARGIN_PX）
    from app.crawlers.damai.fruit_slider import FRUIT_REVEAL_MARGIN_PX

    margin = float(FRUIT_REVEAL_MARGIN_PX)
    specs: list[tuple[str, str, float, str]] = [
        (
            "A_right_edge",
            f"A right_edge (raw-24+{margin:.0f})",
            edge(margin),
            f"当前默认，协议前缘24+余量{margin:.0f}",
        ),
        ("B_raw", "B raw (no-24)", raw_style(), "诊断：recognition 直接拖"),
        ("C_edge_0", "C edge+0", edge(0.0), "无余量贴右缘"),
        ("D_edge_plus12", "D edge+12", edge(12.0), "更大露出余量"),
        ("E_half_edge", "E raw-12", max(0.0, min(max_slide, display_raw - 12.0)), "半前缘试探"),
    ]
    if offline_ui is not None:
        specs.append(
            (
                "F_offline",
                "F offline prior",
                float(max(0.0, min(max_slide, offline_ui))),
                "本地 ROI 先验",
            )
        )

    out: list[ProbeCandidate] = []
    for key, label, ui, note in specs:
        out.append(
            ProbeCandidate(
                key=key,
                label=label,
                ui_x=float(ui),
                reveal_x=float(ui) + float(edge_pad),
                note=note,
                selected=(key == selected_key),
            )
        )
    return out


def render_compare_image(
    image_data: bytes,
    *,
    raw_off: float,
    ui_x: float,
    edge_pad: float = 24.0,
    ques: bytes | None = None,
    validate_code: int | None = None,
    target_name: str = "",
    mouse_dx: float | None = None,
    knob_dx: float | None = None,
    title: str = "",
) -> bytes:
    """人工对照图：题干 + 主图 + raw/ui/reveal 三条竖线 + 图例。"""
    main = _load_rgb(image_data).convert("RGBA")
    w, h = main.size
    font = _font(13)
    font_sm = _font(11)

    ques_h = 0
    ques_im: Image.Image | None = None
    if ques:
        try:
            q = _load_rgb(ques).convert("RGBA")
            # 题干拉到主图宽
            if q.width != w:
                nh = max(18, int(round(q.height * w / max(q.width, 1))))
                q = q.resize((w, nh), Image.Resampling.BILINEAR)
            ques_im = q
            ques_h = q.height + 4
        except Exception:  # noqa: BLE001
            ques_im = None
            ques_h = 0

    legend_h = 54
    canvas = Image.new("RGBA", (w, ques_h + h + legend_h), (245, 245, 248, 255))
    if ques_im is not None:
        canvas.paste(ques_im, (0, 0), ques_im if ques_im.mode == "RGBA" else None)

    canvas.paste(main, (0, ques_h), main if main.mode == "RGBA" else None)
    draw = ImageDraw.Draw(canvas)

    reveal_x = float(ui_x) + float(edge_pad)
    # raw_off 约定：已换算到当前图显示像素（与 ui_x 同一坐标系）
    raw_x = max(0.0, min(float(w - 1), float(raw_off)))
    ui_line = max(0.0, min(float(w - 1), float(ui_x)))
    rev_line = max(0.0, min(float(w - 1), float(reveal_x)))

    y0 = ques_h
    _draw_v_line(draw, raw_x, y0 + h, COLOR_RAW, width=2)
    _draw_v_line(draw, ui_line, y0 + h, COLOR_UI, width=2, dashed=True)
    _draw_v_line(draw, rev_line, y0 + h, COLOR_REVEAL, width=2)

    # 在线上标注
    _label(draw, (int(raw_x) + 3, y0 + 4), f"raw={raw_off:.0f}", font=font_sm, fg=COLOR_RAW)
    _label(draw, (int(ui_line) + 3, y0 + 22), f"ui={ui_x:.0f}", font=font_sm, fg=COLOR_UI)
    _label(
        draw,
        (int(rev_line) + 3, y0 + 40),
        f"reveal={reveal_x:.0f}",
        font=font_sm,
        fg=COLOR_REVEAL,
    )

    # 图例
    ly = ques_h + h + 6
    code_txt = "code=?" if validate_code is None else f"code={validate_code}"
    if validate_code == 0:
        code_txt += " OK"
    head = title or "对照图"
    if target_name:
        head = f"{head} | 目标:{target_name}"
    _label(draw, (6, ly), f"{head} | {code_txt}", font=font)

    bits = [
        f"红 raw={raw_off:.1f} 目标右缘",
        f"绿虚线 ui={ui_x:.1f} 拖动",
        f"蓝 reveal={reveal_x:.1f}=ui+{edge_pad:.0f}",
    ]
    if mouse_dx is not None:
        bits.append(f"mouse={mouse_dx:.1f}")
    if knob_dx is not None:
        bits.append(f"knob={knob_dx:.1f}")
    _label(draw, (6, ly + 24), "  ".join(bits), font=font_sm, fg=(230, 230, 230))

    return _png_bytes(canvas.convert("RGB"))


def render_ab_grid(
    image_data: bytes,
    candidates: Sequence[ProbeCandidate],
    *,
    ques: bytes | None = None,
    cols: int = 3,
    cell_scale: float = 1.0,
    validate_code: int | None = None,
    raw_off: float | None = None,
    title: str = "A/B 网格",
) -> bytes:
    """A/B 网格：每个候选一格，竖线标 reveal 右缘（实线）与 ui（虚线）。"""
    if not candidates:
        raise ValueError("candidates required")

    main = _load_rgb(image_data).convert("RGB")
    mw, mh = main.size
    cw = max(80, int(round(mw * cell_scale)))
    ch = max(45, int(round(mh * cell_scale)))
    font = _font(12)
    font_sm = _font(10)

    n = len(candidates)
    cols = max(1, min(cols, n))
    rows = (n + cols - 1) // cols

    header_h = 28
    label_h = 36
    gap = 6
    grid_w = cols * cw + (cols + 1) * gap
    grid_h = rows * (ch + label_h) + (rows + 1) * gap

    ques_band_h = 0
    ques_im: Image.Image | None = None
    if ques:
        try:
            q = _load_rgb(ques).convert("RGB")
            if q.width != grid_w:
                nh = max(18, int(round(q.height * grid_w / max(q.width, 1))))
                q = q.resize((grid_w, nh), Image.Resampling.BILINEAR)
            ques_im = q
            ques_band_h = q.height + 4
        except Exception:  # noqa: BLE001
            ques_im = None

    canvas = Image.new("RGB", (grid_w, header_h + ques_band_h + grid_h), (32, 34, 40))
    draw = ImageDraw.Draw(canvas)

    code_txt = "code=?" if validate_code is None else f"code={validate_code}"
    head = f"{title} | {code_txt}"
    if raw_off is not None:
        head += f" | raw={raw_off:.1f}"
    _label(draw, (8, 6), head, font=font, fg=(255, 255, 255), bg=(0, 0, 0, 200))

    if ques_im is not None:
        canvas.paste(ques_im, (0, header_h))

    origin_y = header_h + ques_band_h
    for i, cand in enumerate(candidates):
        r, c = divmod(i, cols)
        x0 = gap + c * (cw + gap)
        y0 = origin_y + gap + r * (ch + label_h + gap)

        cell = main.resize((cw, ch), Image.Resampling.BILINEAR).convert("RGBA")
        cd = ImageDraw.Draw(cell)
        sx = cw / max(mw, 1)
        ui_line = max(0.0, min(float(cw - 1), float(cand.ui_x) * sx))
        rev_line = max(0.0, min(float(cw - 1), float(cand.reveal_x) * sx))
        color = COLOR_UI if cand.selected else COLOR_ALT
        _draw_v_line(cd, ui_line, ch, color, width=2, dashed=True)
        _draw_v_line(cd, rev_line, ch, COLOR_REVEAL if cand.selected else COLOR_RAW, width=2)
        canvas.paste(cell.convert("RGB"), (x0, y0))

        # 选中框
        border = COLOR_UI if cand.selected else (90, 90, 100)
        draw.rectangle([x0 - 1, y0 - 1, x0 + cw, y0 + ch], outline=border, width=2 if cand.selected else 1)

        tag = "★ " if cand.selected else ""
        text = f"{tag}{cand.label}\nui={cand.ui_x:.0f} rev={cand.reveal_x:.0f}"
        if cand.note:
            text += f"\n{cand.note}"
        _label(
            draw,
            (x0, y0 + ch + 2),
            text,
            font=font_sm,
            fg=(255, 255, 255) if cand.selected else (210, 210, 210),
            bg=(20, 90, 40, 210) if cand.selected else (0, 0, 0, 180),
        )

    return _png_bytes(canvas)


def write_probe_artifacts(
    out_dir: Path | str,
    *,
    image_data: bytes | None,
    ques: bytes | None,
    raw_off: float,
    ui_x: float,
    max_slide: float,
    logic_w: float = 320.0,
    ui_width: float = 320.0,
    edge_pad: float = 24.0,
    map_mode: str = "fruit_right_edge",
    round_i: int = 1,
    validate_code: int | None = None,
    target_name: str = "",
    mouse_dx: float | None = None,
    knob_dx: float | None = None,
    track_sum_dx: float | None = None,
    delta_mouse: float | None = None,
    delta_knob: float | None = None,
    protocol_per: float | None = None,
    actual_per: float | None = None,
    validate_width: float | None = None,
    token_matches: bool | None = None,
    drag_duration_ms: float | None = None,
    has_token: bool = False,
    img_key: str = "",
    offline_ui: float | None = None,
    canvas_after: bytes | None = None,
    selected_key: str = "A_right_edge",
) -> ProbeMeta:
    """落盘对照图 / A/B 网格 / 原图 / JSON / history。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    prefix = f"r{round_i}_{stamp}"

    meta = ProbeMeta(
        round=round_i,
        raw_bingtop=float(raw_off),
        logic_w=float(logic_w),
        ui_width=float(ui_width),
        ui_x=float(ui_x),
        reveal_x=float(ui_x) + float(edge_pad),
        map_mode=map_mode,
        max_slide=float(max_slide),
        mouse_dx=mouse_dx,
        knob_dx=knob_dx,
        track_sum_dx=track_sum_dx,
        delta_mouse=delta_mouse,
        delta_knob=delta_knob if delta_knob == delta_knob else None,  # NaN guard
        validate_code=validate_code,
        protocol_per=protocol_per,
        actual_per=actual_per,
        validate_width=validate_width,
        token_matches=token_matches,
        drag_duration_ms=drag_duration_ms,
        has_token=has_token,
        img_key=img_key[:64] if img_key else "",
        target_name=target_name or "",
    )

    paths: dict[str, str] = {}
    if image_data:
        img_path = out / f"{prefix}_imageData.jpg"
        # 保留原始字节（可能是 jpeg）
        img_path.write_bytes(image_data)
        paths["imageData"] = str(img_path.name)
        # 同步 last_ 便于人工直接打开
        (out / "last_imageData.bin").write_bytes(image_data)

    if ques:
        q_path = out / f"{prefix}_ques.png"
        q_path.write_bytes(ques)
        paths["ques"] = str(q_path.name)
        (out / "last_ques.bin").write_bytes(ques)

    if canvas_after:
        ca = out / f"{prefix}_canvas_after.png"
        ca.write_bytes(canvas_after)
        paths["canvas_after"] = str(ca.name)
        (out / "last_canvas_after.png").write_bytes(canvas_after)

    candidates = default_ab_candidates(
        float(raw_off),
        max_slide=float(max_slide),
        image_width=float(logic_w),
        ui_width=float(ui_width),
        edge_pad=float(edge_pad),
        selected_key=selected_key,
        offline_ui=offline_ui,
    )
    meta.candidates = [
        {
            "key": c.key,
            "label": c.label,
            "ui_x": c.ui_x,
            "reveal_x": c.reveal_x,
            "note": c.note,
            "selected": c.selected,
        }
        for c in candidates
    ]

    if image_data:
        try:
            compare_png = render_compare_image(
                image_data,
                raw_off=float(raw_off) * (float(ui_width) / max(float(logic_w), 1.0)),
                ui_x=float(ui_x),
                edge_pad=float(edge_pad),
                ques=ques,
                validate_code=validate_code,
                target_name=target_name,
                mouse_dx=mouse_dx,
                knob_dx=knob_dx,
                title=f"round={round_i}",
            )
            cmp_path = out / f"{prefix}_compare.png"
            cmp_path.write_bytes(compare_png)
            (out / "last_compare.png").write_bytes(compare_png)
            paths["compare"] = str(cmp_path.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("render compare image failed: %s", exc)

        try:
            grid_png = render_ab_grid(
                image_data,
                candidates,
                ques=ques,
                validate_code=validate_code,
                raw_off=float(raw_off),
                title=f"A/B 网格 round={round_i}",
            )
            grid_path = out / f"{prefix}_ab_grid.png"
            grid_path.write_bytes(grid_png)
            (out / "last_ab_grid.png").write_bytes(grid_png)
            paths["ab_grid"] = str(grid_path.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("render ab grid failed: %s", exc)

    meta.paths = paths
    payload = meta.to_dict()

    (out / "last_drag_compare.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    hist = out / "drag_compare_history.jsonl"
    with hist.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    # 成功单独索引，便于事后筛 code=0
    if validate_code == 0:
        ok_path = out / "success_history.jsonl"
        with ok_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        logger.info(
            "probe code=0 saved compare=%s ab_grid=%s",
            paths.get("compare"),
            paths.get("ab_grid"),
        )
    else:
        logger.info(
            "probe artifacts saved code=%s compare=%s ab_grid=%s",
            validate_code,
            paths.get("compare"),
            paths.get("ab_grid"),
        )

    return meta


def iter_probe_history(path: Path | str) -> Iterable[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
