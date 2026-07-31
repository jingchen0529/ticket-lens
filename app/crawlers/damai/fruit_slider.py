"""阿里「水果滑块」captchacapslidev2 本地求解。

协议（scratch-captcha 0.0.55 + SecCaptcha WASM）：

出题 GET  …/_____tmd_____/newslidecaptcha
  → { code, success, data: { encryptToken, imageData, ques } }
  → SecCaptcha.updateInfo({ encryptToken, imageData, ques })

拖动渲染（不提交）：
  scale = options.width / 320  （通常 320 → scale=1）
  SecCaptcha.updatePos(24/(container.offsetWidth/320) - 24 + x/scale)
  ≈ document.__update_pos(x)   （容器宽≈320 时）

松手提交 GET …/_____tmd_____/newslidevalidate
  per   = round((x+24)/options.width, 3)
  width = maxSlideWidth
  + token / appKey / ua / umidToken / encryptToken / x5secdata / time

本求解器正确链路（不伪造 verify，不扫到头乱拖）：
  1. 拦截 newslidecaptcha，拿到 imageData + ques + encryptToken
  2. ques OCR/关键词 → 目标物体 ROI（相对 imageData 320×180）
  3. 页内循环 document.__update_pos(x) 离线渲染（不按鼠标、不触发 dragend）
  4. 每步截 canvas，与 imageData 模板打分，找最优逻辑 x
  5. 一次性拟人拖滑块到该 x，松手走官方 verify
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlsplit

import numpy as np
from PIL import Image
from playwright.async_api import Locator, Page

from app.browser.captcha.human_track import generate_slider_track

logger = logging.getLogger(__name__)

# scratch-captcha uses this fixed leading edge in both updatePos and validate per.
# It is a protocol coordinate, not half of the rendered DOM button width.
FRUIT_PROTOCOL_EDGE_PX = 24.0
# Bingtop 1358 reports the target's right edge x1.  Canvas after drag shows:
#   visible_right ≈ ui_x + 24
# so ui_x ≈ x1 - 24 puts the mask edge on x1.  Live probes (松鼠/树袋熊)
# still cut the target by a few px when margin=0 → code=300; overshoot a little.
FRUIT_REVEAL_MARGIN_PX = 8.0

FRUIT_CONTAINER_SELECTORS = [
    ".scratch-captcha-container",
    ".puzzle-captcha-container",
    ".baxia-dialog .scratch-captcha-container",
    "[class*='scratch-captcha-container']",
]

FRUIT_BUTTON_SELECTORS = [
    ".scratch-captcha-slider .button",
    ".puzzle-captcha-slider .button",
    ".scratch-captcha-slider .btn",
    ".scratch-captcha-slider [class*='button']",
    ".scratch-captcha-container .button",
]

FRUIT_TRACK_SELECTORS = [
    ".scratch-captcha-slider",
    ".puzzle-captcha-slider",
]

FRUIT_IMAGE_SELECTORS = [
    ".scratch-captcha-question-bg",
    ".puzzle-captcha-question-bg",
    "#captcha-answer",
    "canvas#captcha-answer",
    "canvas#captcha-question",
    ".scratch-captcha-question canvas",
    ".scratch-captcha-question img",
]

FRUIT_REFRESH_SELECTORS = [
    ".scratch-captcha-question-header .refresh",
    ".scratch-captcha-container .refresh",
    ".puzzle-captcha-container .refresh",
    "[class*='scratch-captcha'] [class*='refresh']",
]

# 题干常见目标物体（ques OCR / 关键词）
TARGET_KEYWORDS: tuple[str, ...] = (
    "帽子",
    "皇冠",
    "蛋糕",
    "天鹅",
    "瓢虫",
    "杯子",
    "菠萝",
    "松鼠",
    "熊猫",
    "大象",
    "热气球",
    "气球",
    "轮毂",
    "轮胎",
    "马头",
    "马",
    "汽车",
    "轿车",
    "车",  # 题干常写「完整的一个车」而非「汽车」
    "苹果",
    "香蕉",
    "草莓",
    "樱桃",
    "西瓜",
    "柠檬",
    "葡萄",
    "胡萝卜",
    "蘑菇",
    "蝴蝶",
    "蜜蜂",
    "蜗牛",
    "青蛙",
    "兔子",
    "小鱼",
    "雨伞",
    "吉他",
    "相机",
    "书本",
    "时钟",
    "爱心",
    "小狗",
    "小猫",
    "鸭子",
    "公鸡",
    "向日葵",
    "玫瑰",
    "冰激凌",
    "冰淇淋",
    "雪糕",
    "汉堡",
    "披萨",
    "足球",
    "南瓜",
    "篮子",
    "酒瓶",
    "瓶子",
    "背包",
    "书包",
    "手袋",
    "手提包",
    "钱包",
    "箱子",
    "礼盒",
    "礼物",
    "凤梨",
    "榴莲",
    "猕猴桃",
    "火龙果",
    "椅子",
    "沙发",
    "树叶",
    "枫叶",
    "蝴蝶结",
    "飞机",
    "轮船",
    "火车",
    "自行车",
    "耳机",
    "手机",
    "电脑",
    "钥匙",
    "蜡烛",
    "灯泡",
    "星星",
    "月亮",
    "太阳",
    "云朵",
    "雪花",
    "火烈鸟",
    "企鹅",
    "树袋熊",
    "考拉",
    "袋鼠",
    "老虎",
    "狮子",
    "猴子",
    "狐狸",
    "刺猬",
    "猫头鹰",
    "鹦鹉",
    "海豚",
    "鲸鱼",
    "螃蟹",
    "章鱼",
    "龙虾",
    "玉米",
    "辣椒",
    "茄子",
    "西红柿",
    "橙子",
    "桃子",
    "梨子",
    "梨",
    "芒果",
    "椰子",
    "面包",
    "甜甜圈",
    "曲奇",
    "奶茶",
    "咖啡",
    "锁头",
    "挂锁",
    "包包",
    "包",
)

# 粗颜色指纹：用于在 imageData 上把目标名对应到 blob（允许较大误差）
# (mean_rgb, tol) — 来自 score_debug / deep2 样本连通域实测，tol 偏松
TARGET_RGB: dict[str, tuple[tuple[float, float, float], float]] = {
    "帽子": ((134.0, 122.0, 93.0), 45.0),
    "皇冠": ((76.0, 68.0, 47.0), 50.0),
    "蛋糕": ((129.0, 147.0, 145.0), 55.0),
    "天鹅": ((118.0, 117.0, 118.0), 40.0),
    "瓢虫": ((129.0, 53.0, 64.0), 55.0),
    "杯子": ((166.0, 166.0, 166.0), 35.0),
    "菠萝": ((157.0, 143.0, 87.0), 50.0),
    "松鼠": ((140.0, 120.0, 110.0), 55.0),
    "熊猫": ((90.0, 90.0, 95.0), 55.0),
    "大象": ((93.0, 94.0, 96.0), 40.0),
    "热气球": ((200.0, 120.0, 120.0), 80.0),
    "气球": ((200.0, 120.0, 120.0), 80.0),
    "马": ((160.0, 150.0, 145.0), 50.0),
    "马头": ((160.0, 150.0, 145.0), 50.0),
    "汽车": ((55.0, 55.0, 60.0), 50.0),
    "轿车": ((55.0, 55.0, 60.0), 50.0),
    "车": ((55.0, 55.0, 60.0), 50.0),
    "轮毂": ((100.0, 100.0, 105.0), 55.0),
    "轮胎": ((100.0, 100.0, 105.0), 55.0),
    "足球": ((150.0, 150.0, 150.0), 55.0),
    "南瓜": ((160.0, 120.0, 80.0), 55.0),
    "苹果": ((180.0, 60.0, 50.0), 60.0),
    "篮子": ((160.0, 120.0, 70.0), 55.0),
    "酒瓶": ((90.0, 50.0, 40.0), 55.0),
    "瓶子": ((140.0, 140.0, 145.0), 55.0),
    "凤梨": ((157.0, 143.0, 87.0), 50.0),
    "包": ((140.0, 100.0, 70.0), 60.0),
    "背包": ((140.0, 100.0, 70.0), 60.0),
    "书包": ((140.0, 100.0, 70.0), 60.0),
    "包包": ((140.0, 100.0, 70.0), 60.0),
    "冰激凌": ((200.0, 160.0, 140.0), 70.0),
    "冰淇淋": ((200.0, 160.0, 140.0), 70.0),
    "雪糕": ((200.0, 160.0, 140.0), 70.0),
    "草莓": ((200.0, 60.0, 80.0), 60.0),
    "考拉": ((150.0, 150.0, 155.0), 55.0),
    "树袋熊": ((150.0, 150.0, 155.0), 55.0),
    "锁头": ((140.0, 140.0, 145.0), 55.0),
    "挂锁": ((140.0, 140.0, 145.0), 55.0),
}


@dataclass
class FruitSliderGeometry:
    button: Locator
    track: Locator
    image: Locator | None
    max_slide: float
    button_box: dict
    track_box: dict
    image_box: dict | None = None


@dataclass
class ObjectBlob:
    x0: int
    y0: int
    x1: int
    y1: int
    area: int
    mean_rgb: tuple[float, float, float]

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.x0, self.y0, self.x1, self.y1

    @property
    def cx(self) -> float:
        return 0.5 * (self.x0 + self.x1)


@dataclass
class CaptchaPayload:
    encrypt_token: str = ""
    image_data: bytes | None = None
    ques: bytes | None = None
    ques_text: str | None = None
    target_name: str | None = None
    target_count: int = 1
    focus_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)

    def content_key(self) -> str:
        """题面指纹：完整哈希避免等长、头尾相似的 JPEG 被误判为同一题。"""
        digest = hashlib.sha256()
        digest.update(self.encrypt_token.encode("utf-8", errors="ignore"))
        digest.update(b"\0")
        digest.update(self.image_data or b"")
        digest.update(b"\0")
        digest.update(self.ques or b"")
        return digest.hexdigest()


@dataclass
class ValidationEvent:
    request_seq: int
    puzzle_key: str
    code: int | None
    token_matches: bool | None
    per: float | None = None
    width: float | None = None
    has_token: bool = False


@dataclass
class ValidationTracker:
    request_seq: int = 0
    armed_puzzle_key: str = ""
    armed_token_hash: str = ""
    pending: dict[
        Any, tuple[int, str, bool | None, float | None, float | None, bool]
    ] = field(default_factory=dict)
    events: list[ValidationEvent] = field(default_factory=list)

    def arm(self, puzzle_key: str, encrypt_token: str = "") -> int:
        self.armed_puzzle_key = puzzle_key
        self.armed_token_hash = (
            hashlib.sha256(encrypt_token.encode("utf-8", errors="ignore")).hexdigest()
            if encrypt_token
            else ""
        )
        return self.request_seq

    def disarm(self) -> None:
        self.armed_puzzle_key = ""
        self.armed_token_hash = ""

    def find_event(
        self,
        *,
        after_seq: int,
        puzzle_key: str,
        expected_per: float | None = None,
        require_token: bool = False,
    ) -> ValidationEvent | None:
        for event in self.events:
            if event.request_seq <= after_seq or event.puzzle_key != puzzle_key:
                continue
            if event.token_matches is False or (require_token and not event.has_token):
                continue
            if (
                expected_per is not None
                and (event.per is None or abs(event.per - expected_per) > 0.002)
            ):
                continue
            return event
        return None


# ---------------------------------------------------------------------------
# 图像 / 题干解析
# ---------------------------------------------------------------------------


def _load_rgb(data: bytes) -> np.ndarray:
    im = Image.open(BytesIO(data)).convert("RGB")
    return np.asarray(im, dtype=np.float32)


def _bg_color(arr: np.ndarray) -> np.ndarray:
    h, w, _ = arr.shape
    samples = np.stack(
        [
            arr[0, 0],
            arr[0, w - 1],
            arr[h - 1, 0],
            arr[h - 1, w - 1],
            arr[0, w // 2],
            arr[h - 1, w // 2],
        ]
    )
    return np.median(samples, axis=0)


def segment_objects(image_bytes: bytes, *, min_area: int = 120) -> list[ObjectBlob]:
    """从 imageData 分割前景物体 blob（连通域）。"""
    arr = _load_rgb(image_bytes)
    h, w, _ = arr.shape
    bg = _bg_color(arr)
    mask = np.linalg.norm(arr - bg, axis=2) > 28.0

    # 4-连通 flood fill（无 scipy 依赖）
    visited = np.zeros((h, w), dtype=bool)
    blobs: list[ObjectBlob] = []
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or visited[y, x]:
                continue
            stack = [(y, x)]
            visited[y, x] = True
            cells_y: list[int] = []
            cells_x: list[int] = []
            while stack:
                cy, cx = stack.pop()
                cells_y.append(cy)
                cells_x.append(cx)
                for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            area = len(cells_x)
            if area < min_area:
                continue
            x0, x1 = min(cells_x), max(cells_x)
            y0, y1 = min(cells_y), max(cells_y)
            # 过宽的连通块（整行粘连）拆不开时仍保留，靠颜色匹配筛选
            if (x1 - x0) > w * 0.85 and (y1 - y0) > h * 0.85:
                continue
            crop = arr[y0 : y1 + 1, x0 : x1 + 1]
            m = mask[y0 : y1 + 1, x0 : x1 + 1]
            if m.any():
                mean = crop[m].mean(axis=0)
            else:
                mean = crop.mean(axis=(0, 1))
            blobs.append(
                ObjectBlob(
                    x0=int(x0),
                    y0=int(y0),
                    x1=int(x1),
                    y1=int(y1),
                    area=int(area),
                    mean_rgb=(float(mean[0]), float(mean[1]), float(mean[2])),
                )
            )
    blobs.sort(key=lambda b: b.area, reverse=True)
    return blobs


_OCR_SWIFT = """
import Vision
import AppKit
import Foundation
let path = CommandLine.arguments[1]
guard let img = NSImage(contentsOfFile: path),
      let tiff = img.tiffRepresentation,
      let rep = NSBitmapImageRep(data: tiff),
      let cg = rep.cgImage else { exit(1) }
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.recognitionLanguages = ["zh-Hans", "en-US"]
req.usesLanguageCorrection = false
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
try handler.perform([req])
let texts = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
print(texts.joined(separator: ""))
"""

_OCR_BIN_CACHED: Path | None = None


def _ocr_binary_path() -> Path:
    base = Path.home() / ".cache" / "daxicrawler"
    base.mkdir(parents=True, exist_ok=True)
    return base / "ocr_vision"


def _ensure_ocr_binary(*, compile_timeout: float = 60.0) -> Path | None:
    """编译并缓存 macOS Vision OCR 小工具（只编译一次）。"""
    global _OCR_BIN_CACHED
    if _OCR_BIN_CACHED and _OCR_BIN_CACHED.exists():
        return _OCR_BIN_CACHED
    bin_path = _ocr_binary_path()
    if bin_path.exists():
        _OCR_BIN_CACHED = bin_path
        return bin_path
    try:
        with tempfile.TemporaryDirectory(prefix="daxi_ocr_build_") as td:
            src = Path(td) / "ocr.swift"
            src.write_text(_OCR_SWIFT, encoding="utf-8")
            compile = subprocess.run(
                ["swiftc", "-O", str(src), "-o", str(bin_path)],
                capture_output=True,
                timeout=compile_timeout,
                check=False,
            )
            if compile.returncode != 0 or not bin_path.exists():
                logger.debug(
                    "ocr compile failed: %s",
                    (compile.stderr or b"")[:200],
                )
                return None
        _OCR_BIN_CACHED = bin_path
        return bin_path
    except Exception as exc:  # noqa: BLE001
        logger.debug("ocr compile skipped: %s", exc)
        return None


def ocr_ques_text(ques_png: bytes, *, allow_compile: bool = True) -> str | None:
    """macOS Vision OCR（可选）。失败返回 None，不影响主流程。

    allow_compile=False 时仅在已有缓存二进制时运行（避免求解热路径卡 60s 编译）。
    """
    try:
        bin_path = _ocr_binary_path() if _ocr_binary_path().exists() else None
        if bin_path is None:
            if not allow_compile:
                return None
            bin_path = _ensure_ocr_binary()
        if bin_path is None:
            return None

        with tempfile.TemporaryDirectory(prefix="daxi_ques_") as td:
            im = Image.open(BytesIO(ques_png)).convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            path = Path(td) / "ques.png"
            Image.alpha_composite(bg, im).convert("RGB").save(path)
            run = subprocess.run(
                [str(bin_path), str(path)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            text = (run.stdout or "").strip()
            return text or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("ques OCR skipped: %s", exc)
        return None


def parse_target_from_text(text: str | None) -> tuple[str | None, int]:
    """从题干文字提取 (目标名, 数量)。数量默认 1，「两个」→2。"""
    if not text:
        return None, 1
    count = 1
    if re.search(r"两[个隻只]|二[个隻只]|2[个隻只]", text):
        count = 2
    elif re.search(r"三[个隻只]|3[个隻只]", text):
        count = 3
    # 优先匹配「完整的一个XX」句式（OCR 常见）
    m = re.search(r"完整的?(?:一|两|二|三|1|2|3)?[个隻只]?([\u4e00-\u9fff]{1,6})后?就?松开?", text)
    if m:
        frag = m.group(1)
        for kw in sorted(TARGET_KEYWORDS, key=len, reverse=True):
            if kw in frag or frag in kw:
                return kw, count
        if frag:
            return frag, count
    # 长词优先
    for kw in sorted(TARGET_KEYWORDS, key=len, reverse=True):
        if kw in text:
            return kw, count
    return None, count


def match_target_blobs(
    blobs: list[ObjectBlob],
    target_name: str | None,
    *,
    count: int = 1,
) -> list[ObjectBlob]:
    """按颜色指纹给目标名选 blob；无匹配则退回面积最大的 count 个。"""
    if not blobs:
        return []
    if not target_name:
        return blobs[: max(1, count)]

    profile = TARGET_RGB.get(target_name)
    if profile is None:
        return blobs[: max(1, count)]

    center, tol = profile
    c = np.array(center, dtype=np.float32)
    scored: list[tuple[float, ObjectBlob]] = []
    for b in blobs:
        dist = float(np.linalg.norm(np.array(b.mean_rgb, dtype=np.float32) - c))
        scored.append((dist, b))
    scored.sort(key=lambda x: x[0])
    picked = [b for d, b in scored if d <= tol * 1.35][: max(1, count)]
    if len(picked) < count:
        # 不够则按距离补足
        picked = [b for _, b in scored[: max(1, count)]]
    return picked


def build_focus_boxes(
    image_bytes: bytes | None,
    target_name: str | None,
    target_count: int = 1,
    *,
    pad: int = 4,
) -> list[tuple[int, int, int, int]]:
    if not image_bytes:
        return []
    blobs = segment_objects(image_bytes)
    if not blobs:
        return []
    chosen = match_target_blobs(blobs, target_name, count=target_count)
    boxes: list[tuple[int, int, int, int]] = []
    arr = _load_rgb(image_bytes)
    h, w, _ = arr.shape
    for b in chosen:
        boxes.append(
            (
                max(0, b.x0 - pad),
                max(0, b.y0 - pad),
                min(w - 1, b.x1 + pad),
                min(h - 1, b.y1 + pad),
            )
        )
    return boxes


def parse_payload_images(image_data_b64_or_bytes: bytes | str, ques_b64_or_bytes: bytes | str | None) -> CaptchaPayload:
    """从 base64 data-url 或原始 bytes 构建 payload。"""

    def _decode(v: bytes | str | None) -> bytes | None:
        if v is None:
            return None
        if isinstance(v, bytes):
            if v[:1] == b"d" or v.startswith(b"data:"):
                s = v.decode("ascii", errors="ignore")
            else:
                return v
        else:
            s = v
        if s.startswith("data:"):
            s = s.split(",", 1)[1]
        import base64

        return base64.b64decode(s)

    img = _decode(image_data_b64_or_bytes)
    ques = _decode(ques_b64_or_bytes)
    payload = CaptchaPayload(image_data=img, ques=ques)
    if ques:
        text = ocr_ques_text(ques)
        payload.ques_text = text
        name, cnt = parse_target_from_text(text)
        payload.target_name = name
        payload.target_count = cnt
    if img:
        payload.focus_boxes = build_focus_boxes(img, payload.target_name, payload.target_count)
    return payload


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------


def _focus_mask(
    h: int,
    w: int,
    focus_boxes: list[tuple[int, int, int, int]] | None,
) -> np.ndarray | None:
    if not focus_boxes:
        return None
    fmask = np.zeros((h, w), dtype=bool)
    for x0, y0, x1, y1 in focus_boxes:
        sx, sy = w / 320.0, h / 180.0
        xa, xb = int(x0 * sx), int(x1 * sx)
        ya, yb = int(y0 * sy), int(y1 * sy)
        fmask[max(0, ya) : min(h, yb + 1), max(0, xa) : min(w, xb + 1)] = True
    return fmask


def _pink_veil_mask(arr: np.ndarray) -> np.ndarray:
    """识别 captchacapslidev2 渲染时的粉色/品红遮罩。"""
    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]
    return (r > 175) & (b > 150) & (g < r - 15) & (g < 220)


def _resize_rgb(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    if arr.shape[0] == height and arr.shape[1] == width:
        return arr
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).resize(
        (width, height), Image.Resampling.BILINEAR
    )
    return np.asarray(im, dtype=np.float32)


def score_completeness(
    png_bytes: bytes,
    *,
    focus_boxes: list[tuple[int, int, int, int]] | None = None,
    template_bytes: bytes | None = None,
) -> float:
    """物体完整度：越低越好。

    有 imageData 模板时（实机 WASM 粉罩混淆）：
      - 目标 ROI 上粉色遮罩覆盖率（越低越好，物体要露出来）
      - 非粉色区域与模板的色差（对齐时更低）
    无模板时回退结构信号（hcut / strip / interleave 合成标定）。
    """
    try:
        arr = _load_rgb(png_bytes)
    except Exception:  # noqa: BLE001
        return 1e18

    if arr.size == 0:
        return 1e18
    h, w, _ = arr.shape
    if h < 8 or w < 16:
        return 1e18

    # ---- 模板匹配路径（实机主路径）----
    if template_bytes:
        try:
            ref = _load_rgb(template_bytes)
            ref = _resize_rgb(ref, w, h)
            return _score_with_template(arr, ref, focus_boxes)
        except Exception as exc:  # noqa: BLE001
            logger.debug("template score fallback: %s", exc)

    # ---- 结构信号回退 ----
    return _score_structure(arr, focus_boxes)


def _score_with_template(
    arr: np.ndarray,
    ref: np.ndarray,
    focus_boxes: list[tuple[int, int, int, int]] | None,
) -> float:
    """模板匹配：目标 ROI 足够露出后，与 imageData 对齐时分数最低。

    关键：不用「粉色越少越好」做主信号（那会单调推到 max_slide）。
    可见度只做门槛；真正选 x 靠模板色差 / 结构差。
    """
    h, w, _ = arr.shape

    # 缩放 focus 到当前截图尺寸（imageData 逻辑 320x180）
    boxes: list[tuple[int, int, int, int]] = []
    if focus_boxes:
        sx, sy = w / 320.0, h / 180.0
        for x0, y0, x1, y1 in focus_boxes:
            boxes.append(
                (
                    max(0, min(w - 1, int(x0 * sx))),
                    max(0, min(h - 1, int(y0 * sy))),
                    max(0, min(w - 1, int(x1 * sx))),
                    max(0, min(h - 1, int(y1 * sy))),
                )
            )
    if not boxes:
        try:
            from io import BytesIO as _Bio

            buf = _Bio()
            Image.fromarray(np.clip(ref, 0, 255).astype(np.uint8)).save(buf, format="PNG")
            for b in segment_objects(buf.getvalue())[:4]:
                boxes.append((b.x0, b.y0, b.x1, b.y1))
        except Exception:  # noqa: BLE001
            boxes = [(int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85))]

    # 模板前景：用于全局对齐（排除背景）
    ref_bg = _bg_color(ref)
    ref_fg = np.linalg.norm(ref - ref_bg, axis=2) > 28.0

    roi_score = 0.0
    vis_pen = 0.0
    n_box = 0
    for x0, y0, x1, y1 in boxes:
        if x1 - x0 < 3 or y1 - y0 < 3:
            continue
        n_box += 1
        sub = arr[y0 : y1 + 1, x0 : x1 + 1]
        rsub = ref[y0 : y1 + 1, x0 : x1 + 1]
        sp = _pink_veil_mask(sub)
        vis = 1.0 - float(sp.mean()) if sp.size else 0.0
        # 可见度门槛：目标至少露出约一半，否则固定高分（不参与“越拖越好”）
        if vis < 0.50:
            vis_pen += 400.0 + 250.0 * (0.50 - vis)
            continue
        visible = ~sp
        # 在模板前景 ∩ 可见区对齐
        rfg = np.linalg.norm(rsub - ref_bg, axis=2) > 28.0
        use = visible & rfg
        if use.sum() < 20:
            use = visible
        if use.sum() < 12:
            vis_pen += 350.0
            continue
        diff = np.linalg.norm(sub - rsub, axis=2)
        match = float(diff[use].mean())
        # 归一化相关（越高越好 → 1-ncc 进分）
        a = sub[use].astype(np.float64).reshape(-1)
        b = rsub[use].astype(np.float64).reshape(-1)
        a = a - a.mean()
        b = b - b.mean()
        denom = float(np.linalg.norm(a) * np.linalg.norm(b)) + 1e-6
        ncc = float(np.dot(a, b) / denom)
        ncc_pen = max(0.0, 1.0 - ncc) * 80.0
        # 边缘结构差
        if sub.shape[0] > 2 and sub.shape[1] > 2:
            eg_a = float(np.abs(np.diff(sub.mean(2), axis=1)).mean())
            eg_b = float(np.abs(np.diff(rsub.mean(2), axis=1)).mean())
            edge_pen = abs(eg_a - eg_b) * 2.0
        else:
            edge_pen = 0.0
        roi_score += match + ncc_pen + edge_pen

    if n_box == 0:
        return 1e6

    # 全局：仅在「模板前景且非粉色」上比；不再加 pink_frac（那会单调推到 max）
    pink = _pink_veil_mask(arr)
    use_g = ref_fg & ~pink
    if use_g.sum() > 80:
        gdiff = float(np.linalg.norm(arr - ref, axis=2)[use_g].mean())
        ga = arr[use_g].astype(np.float64).reshape(-1)
        gb = ref[use_g].astype(np.float64).reshape(-1)
        ga = ga - ga.mean()
        gb = gb - gb.mean()
        denom = float(np.linalg.norm(ga) * np.linalg.norm(gb)) + 1e-6
        gncc = float(np.dot(ga, gb) / denom)
        g_ncc_pen = max(0.0, 1.0 - gncc) * 60.0
    else:
        # 前景几乎都还在粉罩下
        gdiff, g_ncc_pen = 180.0, 60.0

    # 结构辅信号（粉区用模板填平）
    struct = 0.0
    try:
        masked = arr.copy()
        masked[pink] = ref[pink]
        struct = 0.08 * _score_structure(masked, focus_boxes)
    except Exception:  # noqa: BLE001
        struct = 0.0

    # 可见目标数不足时，vis_pen 已很大；够了则纯靠对齐
    return float(roi_score + vis_pen + 0.55 * gdiff + g_ncc_pen + struct)


def _score_structure(
    arr: np.ndarray,
    focus_boxes: list[tuple[int, int, int, int]] | None = None,
) -> float:
    """无模板时的结构完整度（hcut / strip / interleave）。"""
    h, w, _ = arr.shape
    bg = _bg_color(arr)
    mask = np.linalg.norm(arr - bg, axis=2) > 28.0
    # 排除粉色遮罩，避免粉边被当作物体缝
    pink = _pink_veil_mask(arr)
    mask = mask & ~pink
    fmask = _focus_mask(h, w, focus_boxes)

    col_w = np.ones(w, dtype=np.float32)
    if fmask is not None and fmask.any():
        col_w[fmask.any(axis=0)] = 2.2

    # --- 1) 逐行边界能量（strip / interleave）---
    row_diff = np.linalg.norm(arr[1:] - arr[:-1], axis=2)  # (h-1, w)
    row_both = mask[1:] & mask[:-1]
    row_energies: list[float] = []
    for yi in range(h - 1):
        both_row = row_both[yi]
        if not both_row.any():
            continue
        d = row_diff[yi, both_row]
        ww = col_w[both_row]
        row_energies.append(float(np.average(d, weights=ww)))
    if row_energies:
        re = np.array(row_energies, dtype=np.float64)
        h_mean = float(re.mean())
        h_p90 = float(np.percentile(re, 90))
        med = float(np.median(re))
        excess = re - med
        strip_peak = float(np.mean(np.sort(excess)[-max(1, len(excess) // 5) :]))
        strip_peak = max(0.0, strip_peak)
    else:
        h_mean, h_p90, strip_peak = 0.0, 0.0, 0.0

    # --- 2) 中线 hcut ---
    mid = h // 2
    mid_diff = np.linalg.norm(arr[mid - 1] - arr[mid], axis=1)
    both = mask[mid - 1] & mask[mid]
    if both.any():
        vals = mid_diff[both]
        h_both = float(np.average(vals, weights=col_w[both]))
        h_both_p90 = float(np.percentile(vals, 90))
    else:
        either = mask[mid - 1] | mask[mid]
        h_both = float(mid_diff[either].mean()) if either.any() else h_mean
        h_both_p90 = h_p90

    # --- 3) 相邻行水平 NCC 失配 ---
    ncc_pen = 0.0
    ncc_n = 0
    step_y = max(1, h // 24)
    for yi in range(0, h - 1, step_y):
        both_row = row_both[yi]
        if both_row.sum() < 8:
            continue
        ra = arr[yi, both_row].astype(np.float64).reshape(-1)
        rb = arr[yi + 1, both_row].astype(np.float64).reshape(-1)
        ra = ra - ra.mean()
        rb = rb - rb.mean()
        denom = float(np.linalg.norm(ra) * np.linalg.norm(rb)) + 1e-6
        ncc = float(np.dot(ra, rb) / denom)
        ncc_pen += max(0.0, 1.0 - ncc)
        ncc_n += 1
    ncc_mis = ncc_pen / max(1, ncc_n)

    # --- 4) 竖直切缝 ---
    gray = arr.mean(axis=2)
    vdiff = np.abs(np.diff(gray, axis=1))
    mask_v = mask[:, : vdiff.shape[1]] & mask[:, 1 : vdiff.shape[1] + 1]
    if mask_v.any():
        vv = vdiff[mask_v]
        v_mean = float(vv.mean())
        v_p90 = float(np.percentile(vv, 90))
        if fmask is not None and fmask.any():
            fm_v = fmask[:, : vdiff.shape[1]] & fmask[:, 1 : vdiff.shape[1] + 1] & mask_v
            if fm_v.any():
                v_mean = 0.55 * v_mean + 0.45 * float(vdiff[fm_v].mean())
    else:
        v_mean, v_p90 = 0.0, 0.0

    # --- 5) ROI bonus ---
    focus_bonus = 0.0
    if focus_boxes and fmask is not None:
        for bx0, by0, bx1, by1 in focus_boxes:
            sx, sy = w / 320.0, h / 180.0
            xa, xb = int(bx0 * sx), int(bx1 * sx)
            ya, yb = int(by0 * sy), int(by1 * sy)
            xa, xb = max(0, min(w - 1, xa)), max(0, min(w - 1, xb))
            ya, yb = max(0, min(h - 1, ya)), max(0, min(h - 1, yb))
            if xb - xa < 4 or yb - ya < 4:
                continue
            sub_rd = np.linalg.norm(
                arr[ya + 1 : yb + 1, xa : xb + 1] - arr[ya:yb, xa : xb + 1], axis=2
            )
            sm = mask[ya + 1 : yb + 1, xa : xb + 1] & mask[ya:yb, xa : xb + 1]
            if sm.any():
                focus_bonus += float(sub_rd[sm].mean())
            if ya < mid < yb and both.any():
                hd = mid_diff[xa : xb + 1]
                bm = both[xa : xb + 1]
                if bm.any():
                    focus_bonus += float(hd[bm].mean()) * 0.8

    score = (
        1.25 * h_both
        + 0.40 * h_both_p90
        + 0.30 * h_mean
        + 0.15 * h_p90
        + 1.10 * strip_peak
        + 55.0 * ncc_mis
        + 0.22 * v_mean
        + 0.08 * v_p90
        + 0.40 * focus_bonus
    )
    return float(score)


def find_best_offset_by_scores(
    samples: list[tuple[float, float]],
    *,
    prefer_interior: bool = True,
    prior_x: float | None = None,
    prior_weight: float = 0.0,
) -> float:
    """取最低分；三点平滑后找谷，并对谷底做抛物线插值。

    prefer_interior: 曲线近似单调且谷在端点时，改在内部局部谷中选（避免粉罩单调把答案推到 max_slide）。
    prior_x: 可选先验（如目标物体中心映射的 UI x），用于打破平台/噪声。
    """
    if not samples:
        return 0.0
    xs = np.array([s[0] for s in samples], dtype=np.float64)
    ys = np.array([s[1] for s in samples], dtype=np.float64)
    if len(ys) >= 3:
        smooth = ys.copy()
        for i in range(1, len(ys) - 1):
            smooth[i] = float(np.median(ys[i - 1 : i + 2]))
        ys = smooth

    span = float(np.ptp(ys)) if np.ptp(ys) > 1e-6 else 1.0
    adj = ys.copy()
    # 边界罚：比原来更重，防止滑到底
    if len(adj) >= 4:
        adj[0] += 0.18 * span
        adj[-1] += 0.18 * span
        if len(adj) >= 6:
            adj[1] += 0.06 * span
            adj[-2] += 0.06 * span

    # 先验：靠近目标几何位置的样本略降分
    if prior_x is not None and prior_weight > 0 and len(xs) > 1:
        x_span = float(np.ptp(xs)) or 1.0
        adj = adj + prior_weight * span * ((xs - float(prior_x)) / x_span) ** 2

    i = int(np.argmin(adj))

    # 单调/端点伪谷：粉罩场景常见「分数一路降到 max」——绝不能选端点
    if prefer_interior and len(ys) >= 8:
        # 允许少量噪声的近似单调
        dec_n = sum(1 for j in range(len(ys) - 1) if ys[j] + 1e-6 >= ys[j + 1])
        inc_n = sum(1 for j in range(len(ys) - 1) if ys[j] <= ys[j + 1] + 1e-6)
        approx_mono_dec = dec_n >= 0.85 * (len(ys) - 1)
        approx_mono_inc = inc_n >= 0.85 * (len(ys) - 1)
        edge = i <= 1 or i >= len(ys) - 2
        x_max = float(xs[-1])
        near_max = float(xs[i]) >= 0.90 * x_max if x_max > 0 else edge
        if edge or near_max or approx_mono_dec or approx_mono_inc:
            # 1) 有先验：直接优先先验附近
            if prior_x is not None and 0 < float(prior_x) < 0.92 * x_max:
                # 在先验邻域内取 adj 最低
                band = 0.22 * x_max
                cand = [
                    (float(adj[j]), j)
                    for j in range(len(xs))
                    if abs(float(xs[j]) - float(prior_x)) <= band
                    and 0.08 * x_max <= float(xs[j]) <= 0.92 * x_max
                ]
                if cand:
                    i = min(cand, key=lambda t: t[0])[1]
                else:
                    i = int(np.argmin(np.abs(xs - float(prior_x))))
            else:
                lo = max(1, len(ys) // 8)
                hi = min(len(ys) - 2, len(ys) - 1 - len(ys) // 8)
                if hi > lo:
                    local: list[tuple[float, int]] = []
                    for j in range(lo, hi + 1):
                        if ys[j] <= ys[j - 1] and ys[j] <= ys[j + 1]:
                            local.append((float(adj[j]), j))
                    if local:
                        i = min(local, key=lambda t: t[0])[1]
                    else:
                        # 二阶差分最大处 ≈ 斜率变缓的拐点，比盲选中点强
                        d1 = np.diff(ys)
                        if len(d1) >= 3:
                            d2 = np.diff(d1)
                            # 下降变缓：d2 最大（负斜率绝对值变小）
                            j2 = int(np.argmax(d2)) + 1  # map to ys index roughly
                            i = int(np.clip(j2, lo, hi))
                        else:
                            i = lo + int(np.argmin(adj[lo : hi + 1]))

    if 0 < i < len(ys) - 1:
        y0, y1, y2 = float(ys[i - 1]), float(ys[i]), float(ys[i + 1])
        denom = y0 - 2 * y1 + y2
        if abs(denom) > 1e-9:
            delta = 0.5 * (y0 - y2) / denom
            delta = float(np.clip(delta, -0.5, 0.5))
            step = float(xs[i] - xs[i - 1]) if i > 0 else 1.0
            return float(xs[i] + delta * step)
    return float(xs[i])


def prior_ui_x_from_focus(
    focus_boxes: list[tuple[int, int, int, int]] | None,
    *,
    max_slide: float,
    image_logic_width: float = 320.0,
) -> float | None:
    """用目标 ROI 粗估 UI 位移。

    实机帧标定（粉罩从右侧退去，可见右缘随拖动增大）：
      visible_right ≈ ui_x + 24   （image 逻辑坐标，与滑块像素近似 1:1）
    要让最右目标完整露出：
      ui_x >= x1_max - 24
    注意：不要再乘 max_slide/320 —— 那会系统性偏小约 15%。
    """
    if not focus_boxes or max_slide <= 0:
        return None
    x1s = [float(b[2]) for b in focus_boxes]
    if not x1s:
        return None
    x1 = max(x1s)
    # 略加余量，避免贴边仍被粉罩切一刀
    ui = float(x1 - 24.0 + 4.0)
    # 若 image 实际宽不是 320，按比例（极少见）
    if image_logic_width > 1 and abs(image_logic_width - 320.0) > 1.0:
        ui = ui * (320.0 / image_logic_width)
    return float(max(0.0, min(max_slide, ui)))


def estimate_offset_from_payload(
    payload: CaptchaPayload | None,
    *,
    max_slide: float,
    image_logic_width: float = 320.0,
) -> float | None:
    """纯离线：只靠 newslidecaptcha 的 imageData/ques 估位移，不拖鼠标。"""
    if payload is None or max_slide <= 0:
        return None
    boxes = list(payload.focus_boxes or [])
    if not boxes and payload.image_data:
        boxes = build_focus_boxes(
            payload.image_data,
            payload.target_name,
            payload.target_count or 1,
        )
    return prior_ui_x_from_focus(
        boxes, max_slide=max_slide, image_logic_width=image_logic_width
    )


# ---------------------------------------------------------------------------
# DOM / 几何
# ---------------------------------------------------------------------------


async def _first_visible(page: Page, selectors: list[str], *, timeout_ms: int = 80) -> Locator | None:
    """快速查找可见节点。timeout 宜短，避免 detect 轮询被 is_visible 拖死。"""
    t = max(0, min(int(timeout_ms), 200))

    async def _check(root) -> Locator | None:  # Page | Frame
        for sel in selectors:
            try:
                loc = root.locator(sel).first
                if await loc.count() == 0:
                    continue
                # timeout=0：立即返回当前可见性，不空等
                if t <= 0:
                    if await loc.is_visible():
                        return loc
                elif await loc.is_visible(timeout=t):
                    return loc
            except Exception:  # noqa: BLE001
                continue
        return None

    found = await _check(page)
    if found is not None:
        return found
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        found = await _check(frame)
        if found is not None:
            return found
    return None


async def detect_fruit_slider(page: Page) -> bool:
    if await _first_visible(page, FRUIT_BUTTON_SELECTORS, timeout_ms=0) is not None:
        return True
    if await _first_visible(page, FRUIT_CONTAINER_SELECTORS, timeout_ms=0) is not None:
        return True
    for frame in page.frames:
        furl = (frame.url or "").lower()
        if "capslide" in furl or "captcha" in furl or "punish" in furl:
            try:
                for sel in FRUIT_BUTTON_SELECTORS[:3]:
                    loc = frame.locator(sel).first
                    if await loc.count() and await loc.is_visible():
                        return True
            except Exception:  # noqa: BLE001
                pass
    # 文案检测放最后且短超时（punish 页 body 很大时 inner_text 很慢）
    try:
        html = await asyncio.wait_for(page.content(), timeout=0.6)
        if "拖动滑块出现完整" in html or "后就松开" in html or "scratch-captcha" in html:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


async def wait_fruit_slider(page: Page, *, timeout_s: float = 12.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await detect_fruit_slider(page):
            btn = await _first_visible(page, FRUIT_BUTTON_SELECTORS, timeout_ms=50)
            if btn is not None:
                return True
        await page.wait_for_timeout(250)
    return await detect_fruit_slider(page)


async def measure_geometry(page: Page) -> FruitSliderGeometry | None:
    button = await _first_visible(page, FRUIT_BUTTON_SELECTORS, timeout_ms=80)
    if button is None:
        return None
    track = await _first_visible(page, FRUIT_TRACK_SELECTORS, timeout_ms=50)
    if track is None:
        track = button.locator("xpath=..")

    bbox = await button.bounding_box()
    tbox = await track.bounding_box()
    if not bbox or not tbox:
        return None

    max_slide = max(10.0, float(tbox["width"] - bbox["width"]))
    image = await _first_visible(page, FRUIT_IMAGE_SELECTORS, timeout_ms=50)
    ibox = None
    if image is not None:
        try:
            ibox = await image.bounding_box()
        except Exception:  # noqa: BLE001
            ibox = None
    return FruitSliderGeometry(
        button=button,
        track=track,
        image=image,
        max_slide=max_slide,
        button_box=bbox,
        track_box=tbox,
        image_box=ibox,
    )


async def _canvas_png_bytes(page: Page) -> bytes | None:
    """直接从 captcha canvas 读像素（比外层截图更贴近 WASM 渲染结果）。"""
    try:
        import base64

        data_url = await page.evaluate(
            """() => {
              const sels = [
                'canvas#captcha-answer',
                'canvas#captcha-question',
                '.scratch-captcha-question canvas',
                '.scratch-captcha-question-bg canvas',
                '.scratch-captcha-container canvas',
                'canvas'
              ];
              for (const s of sels) {
                const c = document.querySelector(s);
                if (!c) continue;
                const w = c.width || 0, h = c.height || 0;
                if (w < 40 || h < 40) continue;
                try { return c.toDataURL('image/png'); } catch (e) {}
              }
              // iframe 内
              for (const f of document.querySelectorAll('iframe')) {
                try {
                  const doc = f.contentDocument || f.contentWindow.document;
                  if (!doc) continue;
                  for (const s of sels) {
                    const c = doc.querySelector(s);
                    if (!c) continue;
                    const w = c.width || 0, h = c.height || 0;
                    if (w < 40 || h < 40) continue;
                    try { return c.toDataURL('image/png'); } catch (e) {}
                  }
                } catch (e) {}
              }
              return null;
            }"""
        )
        if not data_url or not isinstance(data_url, str) or "," not in data_url:
            return None
        return base64.b64decode(data_url.split(",", 1)[1])
    except Exception:  # noqa: BLE001
        return None


async def _screenshot_target(geo: FruitSliderGeometry, page: Page) -> bytes | None:
    # 1) canvas 像素（最准）
    png = await _canvas_png_bytes(page)
    if png:
        return png

    # 2) clip 截图（比 element screenshot 更稳）
    box = geo.image_box
    if box and box.get("width", 0) > 8 and box.get("height", 0) > 8:
        try:
            return await page.screenshot(
                type="png",
                clip={
                    "x": max(0, box["x"]),
                    "y": max(0, box["y"]),
                    "width": box["width"],
                    "height": box["height"],
                },
                timeout=1500,
            )
        except Exception:  # noqa: BLE001
            pass
    try:
        if geo.image is not None and await geo.image.count():
            return await geo.image.screenshot(type="png", timeout=1500)
    except Exception:  # noqa: BLE001
        pass
    for sel in FRUIT_CONTAINER_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible(timeout=150):
                return await loc.screenshot(type="png", timeout=1500)
        except Exception:  # noqa: BLE001
            continue
    return None


_FIND_SECCAPTCHA_JS = """() => {
  // 0) init_script 捕获的钩子
  if (typeof window.__daxiUpdatePos === 'function') {
    return {ok: true, via: 'window.__daxiUpdatePos'};
  }
  // 1) document 级 WASM 钩子
  if (typeof document.__update_pos === 'function') {
    return {ok: true, via: 'document.__update_pos'};
  }
  // 2) 常见全局
  const direct = [
    window.SecCaptcha,
    window.secCaptcha,
    window._SecCaptcha,
    window._config_ && window._config_.SecCaptcha,
  ];
  for (const sc of direct) {
    if (sc && typeof sc.updatePos === 'function') {
      window.__daxiSecCaptcha = sc;
      return {ok: true, via: 'global'};
    }
  }
  // 3) 从 captcha 容器/滑块实例上抠 options.SecCaptcha
  const roots = [
    ...document.querySelectorAll('.scratch-captcha-container, .scratch-captcha-slider, [class*="scratch-captcha"]'),
  ];
  const seen = new Set();
  const walk = (obj, depth) => {
    if (!obj || depth > 4 || typeof obj !== 'object') return null;
    if (seen.has(obj)) return null;
    try { seen.add(obj); } catch (e) { return null; }
    try {
      if (typeof obj.updatePos === 'function' && (typeof obj.updateInfo === 'function' || obj.init)) {
        return obj;
      }
      if (obj.SecCaptcha && typeof obj.SecCaptcha.updatePos === 'function') {
        return obj.SecCaptcha;
      }
      if (obj.options && obj.options.SecCaptcha && typeof obj.options.SecCaptcha.updatePos === 'function') {
        return obj.options.SecCaptcha;
      }
    } catch (e) {}
    // 浅扫自有属性
    let keys = [];
    try { keys = Object.getOwnPropertyNames(obj); } catch (e) {
      try { keys = Object.keys(obj); } catch (e2) { return null; }
    }
    for (const k of keys) {
      if (k === 'parent' || k === 'parentNode' || k === 'childNodes' || k === 'document') continue;
      let v;
      try { v = obj[k]; } catch (e) { continue; }
      if (!v || typeof v !== 'object') continue;
      const hit = walk(v, depth + 1);
      if (hit) return hit;
    }
    return null;
  };
  for (const el of roots) {
    // DOM 扩展字段 / 框架挂载
    for (const k of Object.getOwnPropertyNames(el)) {
      try {
        const hit = walk(el[k], 0);
        if (hit) {
          window.__daxiSecCaptcha = hit;
          return {ok: true, via: 'dom:' + k};
        }
      } catch (e) {}
    }
    try {
      for (const k of Object.keys(el)) {
        const hit = walk(el[k], 0);
        if (hit) {
          window.__daxiSecCaptcha = hit;
          return {ok: true, via: 'dom-keys:' + k};
        }
      }
    } catch (e) {}
  }
  // 4) 扫 window 上带 captcha 名字的对象
  for (const k of Object.keys(window)) {
    if (!/captcha|scratch|sec|punish|nocaptcha/i.test(k)) continue;
    try {
      const hit = walk(window[k], 0);
      if (hit) {
        window.__daxiSecCaptcha = hit;
        return {ok: true, via: 'window.' + k};
      }
    } catch (e) {}
  }
  return {ok: false, via: null};
}"""


async def _resolve_update_pos(page: Page) -> dict:
    """探测/缓存页内 SecCaptcha.updatePos 或 document.__update_pos。"""
    try:
        return await page.evaluate(_FIND_SECCAPTCHA_JS) or {"ok": False}
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve updatePos: %s", exc)
        return {"ok": False, "via": None}


async def _has_update_pos(page: Page) -> bool:
    info = await _resolve_update_pos(page)
    return bool(info.get("ok"))


async def _call_update_pos(page: Page, pos: float) -> bool:
    """调用官方渲染钩子，不触发 dragend/verify。"""
    try:
        return bool(
            await page.evaluate(
                """(pos) => {
                  try {
                    if (typeof window.__daxiUpdatePos === 'function') {
                      window.__daxiUpdatePos(pos);
                      return true;
                    }
                    if (typeof document.__update_pos === 'function') {
                      document.__update_pos(pos);
                      return true;
                    }
                    const sc = window.__daxiSecCaptcha
                      || window.SecCaptcha
                      || (window._config_ && window._config_.SecCaptcha);
                    if (sc && typeof sc.updatePos === 'function') {
                      sc.updatePos(pos);
                      return true;
                    }
                    return false;
                  } catch (e) {
                    return false;
                  }
                }""",
                float(pos),
            )
        )
    except Exception:  # noqa: BLE001
        return False


def _ui_x_to_update_pos(
    ui_x: float,
    *,
    options_width: float = 320.0,
    container_width: float | None = None,
) -> float:
    """UI 滑块位移 → SecCaptcha.updatePos 参数。

    官方：updatePos(24/(container.offsetWidth/320) - 24 + x / (options.width/320))
    容器≈320、options.width=320 时 ≈ ui_x。
    """
    ow = options_width if options_width > 1 else 320.0
    cw = container_width if container_width and container_width > 1 else ow
    scale = ow / 320.0
    base = 24.0 / (cw / 320.0) - 24.0
    return float(base + ui_x / scale)


async def _read_container_width(page: Page) -> float | None:
    try:
        w = await page.evaluate(
            """() => {
              const el = document.querySelector('.scratch-captcha-container')
                || document.querySelector('.puzzle-captcha-container')
                || document.querySelector('[class*="scratch-captcha"]');
              if (!el) return null;
              return el.offsetWidth || el.clientWidth || null;
            }"""
        )
        return float(w) if w else None
    except Exception:  # noqa: BLE001
        return None


async def estimate_offset_via_update_pos(
    page: Page,
    geo: FruitSliderGeometry,
    *,
    template_bytes: bytes | None,
    focus_boxes: list[tuple[int, int, int, int]] | None = None,
    step: float = 4.0,
    settle_ms: int = 35,
) -> tuple[float | None, list[tuple[float, float]]]:
    """不拖鼠标：循环 __update_pos 渲染 + 截 canvas 打分，返回最优 UI x。

    返回 (best_ui_x, samples)。无法调用 __update_pos 时 best=None。
    """
    if not await _has_update_pos(page):
        logger.warning("document.__update_pos unavailable, cannot offline-scan")
        return None, []

    container_w = await _read_container_width(page)
    options_w = 320.0
    # image box 宽接近 320 时 options.width 多为 320
    if geo.image_box and geo.image_box.get("width"):
        iw = float(geo.image_box["width"])
        if 200 <= iw <= 400:
            options_w = 320.0

    samples: list[tuple[float, float]] = []
    max_slide = float(geo.max_slide)
    step = max(2.0, float(step))
    x = 0.0
    points = 0
    max_points = 90

    # 重置到 0
    await _call_update_pos(page, _ui_x_to_update_pos(0.0, options_width=options_w, container_width=container_w))
    await page.wait_for_timeout(40)

    while x <= max_slide + 0.05 and points < max_points:
        pos = _ui_x_to_update_pos(x, options_width=options_w, container_width=container_w)
        ok = await _call_update_pos(page, pos)
        if not ok:
            logger.warning("updatePos failed at ui_x=%.1f", x)
            break
        await page.wait_for_timeout(settle_ms)
        png = await _screenshot_target(geo, page)
        if png:
            sc = score_completeness(
                png,
                focus_boxes=focus_boxes,
                template_bytes=template_bytes,
            )
            samples.append((x, sc))
        x += step
        points += 1

    if not samples:
        return None, []

    prior = prior_ui_x_from_focus(focus_boxes, max_slide=max_slide)
    best = find_best_offset_by_scores(
        samples, prefer_interior=True, prior_x=prior, prior_weight=0.15
    )
    # 精扫：best 附近更小步长
    lo = max(0.0, best - step * 2.0)
    hi = min(max_slide, best + step * 2.0)
    fine_step = max(1.0, step / 2.5)
    fine: list[tuple[float, float]] = []
    fx = lo
    while fx <= hi + 0.05:
        pos = _ui_x_to_update_pos(fx, options_width=options_w, container_width=container_w)
        if await _call_update_pos(page, pos):
            await page.wait_for_timeout(max(28, settle_ms - 5))
            png = await _screenshot_target(geo, page)
            if png:
                fine.append(
                    (
                        fx,
                        score_completeness(
                            png,
                            focus_boxes=focus_boxes,
                            template_bytes=template_bytes,
                        ),
                    )
                )
        fx += fine_step

    if fine:
        best = find_best_offset_by_scores(
            fine, prefer_interior=True, prior_x=prior, prior_weight=0.12
        )
        samples = fine
        logger.info(
            "updatePos fine best_x=%.1f score=%.3f samples=%s prior=%s",
            best,
            min(s for _, s in fine),
            len(fine),
            None if prior is None else round(prior, 1),
        )
    else:
        logger.info(
            "updatePos coarse best_x=%.1f score=%.3f samples=%s ends=(%.1f,%.1f) prior=%s",
            best,
            min(s for _, s in samples),
            len(samples),
            samples[0][1],
            samples[-1][1],
            None if prior is None else round(prior, 1),
        )

    # 复位到 0，避免残留渲染影响后续真实拖动
    await _call_update_pos(
        page, _ui_x_to_update_pos(0.0, options_width=options_w, container_width=container_w)
    )
    return float(best), samples


async def _scan_range(
    page: Page,
    geo: FruitSliderGeometry,
    *,
    start_x: float,
    start_y: float,
    lo: float,
    hi: float,
    step: float,
    settle_ms: int,
    focus_boxes: list[tuple[int, int, int, int]] | None = None,
    template_bytes: bytes | None = None,
    already_down: bool = False,
) -> list[tuple[float, float]]:
    """兜底：真实按住滑块在 [lo, hi] 采样（不 mouse.up，避免中途 verify）。"""
    samples: list[tuple[float, float]] = []
    if not already_down:
        await page.mouse.move(start_x, start_y)
        await page.wait_for_timeout(40)
        await page.mouse.down()
        await page.wait_for_timeout(50)

    x = lo
    max_points = 80
    points = 0
    await page.mouse.move(start_x + lo, start_y + float(np.random.uniform(-0.4, 0.4)))
    await page.wait_for_timeout(max(30, settle_ms // 2))

    while x <= hi + 0.05 and points < max_points:
        await page.mouse.move(start_x + x, start_y + float(np.random.uniform(-0.5, 0.5)))
        await page.wait_for_timeout(settle_ms)
        png = await _screenshot_target(geo, page)
        if png:
            samples.append(
                (
                    x,
                    score_completeness(
                        png,
                        focus_boxes=focus_boxes,
                        template_bytes=template_bytes,
                    ),
                )
            )
        x += step
        points += 1
    return samples


async def drag_to_offset(
    page: Page,
    geo: FruitSliderGeometry,
    target_x: float,
    *,
    release: bool = True,
    before_mouse_down: Callable[[], Awaitable[bool]] | None = None,
    before_mouse_up: Callable[[], Awaitable[bool]] | None = None,
) -> dict[str, float]:
    """拟人拖到 target_x（UI px），返回实测位移便于对照打码值。

    返回字段：
      target_x / dist      请求目标与 clamp 后距离
      mouse_dx             鼠标最终相对起点的横向位移（命令路径）
      knob_dx              松手前滑块中心相对起点的横向位移（DOM 实测）
      max_slide
    """
    dist = max(0.0, min(float(target_x), float(geo.max_slide)))

    try:
        await page.mouse.up()
    except Exception:  # noqa: BLE001
        pass

    box = None
    try:
        await geo.button.scroll_into_view_if_needed(timeout=1500)
    except Exception:  # noqa: BLE001
        pass
    try:
        box = await geo.button.bounding_box()
    except Exception:  # noqa: BLE001
        box = None
    if not box:
        box = geo.button_box
    if not box:
        return {
            "target_x": float(target_x),
            "dist": dist,
            "mouse_dx": 0.0,
            "knob_dx": -1.0,
            "track_sum_dx": 0.0,
            "max_slide": float(geo.max_slide),
        }

    # 若 knob 不在起点（上一题失败后残留），先点轨道左侧复位
    track_left = float(geo.track_box.get("x", box["x"]))
    if box["x"] > track_left + 8:
        try:
            await page.mouse.click(track_left + 4, box["y"] + box["height"] / 2)
            await page.wait_for_timeout(200)
            box = await geo.button.bounding_box() or box
        except Exception:  # noqa: BLE001
            pass

    sx = box["x"] + box["width"] * 0.5
    sy = box["y"] + box["height"] * 0.5
    start_knob_x = sx

    # 先 hover 控件再按下，减少「鼠标走了、滑块不动」
    try:
        await geo.button.hover(timeout=800)
        await page.wait_for_timeout(80)
        box = await geo.button.bounding_box() or box
        sx = box["x"] + box["width"] * 0.5
        sy = box["y"] + box["height"] * 0.5
        start_knob_x = sx
    except Exception:  # noqa: BLE001
        pass

    await page.mouse.move(sx - 6, sy)
    await page.wait_for_timeout(50)
    await page.mouse.move(sx, sy)
    await page.wait_for_timeout(100)
    if before_mouse_down is not None and not await before_mouse_down():
        logger.info("drag_to_offset aborted before mouse.down because puzzle changed")
        return {
            "target_x": float(target_x),
            "dist": dist,
            "mouse_dx": 0.0,
            "knob_dx": 0.0,
            "track_sum_dx": 0.0,
            "max_slide": float(geo.max_slide),
            "aborted": 1.0,
        }
    await page.mouse.down()
    drag_started = time.monotonic()
    await page.wait_for_timeout(150)

    # 按下后立刻确认 knob 是否跟手；不跟手则取消，避免提交 per≈0 → code=306
    try:
        box_grab = await geo.button.bounding_box()
        if box_grab is not None:
            grab_dx = abs((box_grab["x"] + box_grab["width"] / 2) - start_knob_x)
            # 按下瞬间几乎不应大位移；这里只探测是否还能读到按钮
            _ = grab_dx
    except Exception:  # noqa: BLE001
        pass

    x, y = sx, sy
    track_sum_dx = 0.0
    # 稍慢的拟人轨迹，降低 300/306 风控
    for dx, dy, delay in generate_slider_track(dist):
        x += dx
        y += dy
        track_sum_dx += dx
        if x - sx > dist + 2:
            x = sx + dist
        # One timed event per sample.  Playwright's `steps` events are emitted in
        # a tight burst before the explicit delay, producing an avoidable
        # three-events-then-pause fingerprint.
        await page.mouse.move(x, y)
        await page.wait_for_timeout(min(max(delay, 14), 48))

    final_x = sx + dist
    final_y = sy + float(np.random.uniform(-0.4, 0.4))
    await page.mouse.move(final_x, final_y)
    await page.wait_for_timeout(220)
    drag_duration_ms = (time.monotonic() - drag_started) * 1000.0

    knob_dx = float("nan")
    try:
        box_end = await geo.button.bounding_box()
        if box_end:
            knob_dx = (box_end["x"] + box_end["width"] / 2) - start_knob_x
    except Exception:  # noqa: BLE001
        pass

    stuck = bool(
        release
        and (knob_dx != knob_dx or abs(float(knob_dx)) < max(3.0, dist * 0.15))
    )
    if stuck:
        logger.warning(
            "drag_to_offset knob stuck knob_dx=%s target=%.1f; release at start, no answer",
            knob_dx,
            dist,
        )
        # 滑块没动就松手提交会变成 per≈0 / code=306；拖回起点再 up
        try:
            await page.mouse.move(sx, sy)
            await page.wait_for_timeout(40)
            await page.mouse.up()
            await page.wait_for_timeout(200)
        except Exception:  # noqa: BLE001
            try:
                await page.mouse.up()
            except Exception:  # noqa: BLE001
                pass
        return {
            "target_x": float(target_x),
            "dist": dist,
            "mouse_dx": final_x - sx,
            "knob_dx": float(knob_dx) if knob_dx == knob_dx else 0.0,
            "track_sum_dx": track_sum_dx,
            "max_slide": float(geo.max_slide),
            "drag_duration_ms": drag_duration_ms,
            "stuck": 1.0,
        }

    mouse_dx = final_x - sx
    logger.info(
        "drag_to_offset target=%.2f dist=%.2f mouse_dx=%.2f knob_dx=%.2f "
        "track_sum_dx=%.2f max_slide=%.1f start=(%.1f,%.1f)",
        float(target_x),
        dist,
        mouse_dx,
        knob_dx,
        track_sum_dx,
        float(geo.max_slide),
        sx,
        sy,
    )

    if release:
        release_is_current = True
        if before_mouse_up is not None:
            release_is_current = await before_mouse_up()
        await page.mouse.up()
        await page.wait_for_timeout(900)
        if not release_is_current:
            logger.info("drag_to_offset puzzle changed before mouse.up; ignore validation")
            return {
                "target_x": float(target_x),
                "dist": dist,
                "mouse_dx": mouse_dx,
                "knob_dx": float(knob_dx) if knob_dx == knob_dx else -1.0,
                "track_sum_dx": track_sum_dx,
                "max_slide": float(geo.max_slide),
                "aborted": 1.0,
            }

    return {
        "target_x": float(target_x),
        "dist": dist,
        "mouse_dx": mouse_dx,
        "knob_dx": float(knob_dx) if knob_dx == knob_dx else -1.0,
        "track_sum_dx": track_sum_dx,
        "max_slide": float(geo.max_slide),
        "drag_duration_ms": drag_duration_ms,
    }


async def _click_refresh(page: Page) -> None:
    for sel in FRUIT_REFRESH_SELECTORS + ["text=刷新"]:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible(timeout=200):
                await loc.click(timeout=1500)
                return
        except Exception:  # noqa: BLE001
            continue


def decode_newslidecaptcha_json(text: str) -> CaptchaPayload | None:
    """解析 newslidecaptcha 响应 JSON → CaptchaPayload（仅解码，不做 OCR）。"""
    import base64

    if not text or "imageData" not in text:
        return None
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return None
    d = data.get("data") if isinstance(data, dict) else None
    if not isinstance(d, dict):
        return None
    img = d.get("imageData")
    ques = d.get("ques")
    if not img or not isinstance(img, str):
        return None

    def dec(v: str | None) -> bytes | None:
        if not v or not isinstance(v, str):
            return None
        s = v.split(",", 1)[1] if v.startswith("data:") else v
        try:
            return base64.b64decode(s)
        except Exception:  # noqa: BLE001
            return None

    image_data = dec(img)
    ques_data = dec(ques if isinstance(ques, str) else None)
    if not image_data:
        return None
    return CaptchaPayload(
        encrypt_token=str(d.get("encryptToken") or ""),
        image_data=image_data,
        ques=ques_data,
    )


def decode_newslidevalidate_code(text: str) -> int | None:
    """解析官方 validate 结果；外层 success=true 仅表示请求成功，code=0 才是过码。"""
    if not text:
        return None
    try:
        body = json.loads(text)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(body, dict):
        return None
    result = body.get("result")
    values = [result.get("code") if isinstance(result, dict) else None, body.get("code")]
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


async def attach_payload_listener(page: Page, sink: list[CaptchaPayload]) -> Callable[[], None]:
    """监听 newslidecaptcha，解析 imageData/ques → CaptchaPayload。

    只认带 imageData+encryptToken 的 JSON；优先 URL 含 newslidecaptcha。
    解码后校验 JPEG/PNG 魔数，垃圾响应不入 sink，避免后续把坏图送给打码。
    """
    from app.browser.captcha.providers import is_valid_image_bytes

    async def on_resp(response) -> None:  # type: ignore[no-untyped-def]
        try:
            url = response.url
            low = url.lower()
            interesting = (
                "newslidecaptcha" in low
                or ("_____tmd_____" in low and "slide" in low)
                or ("_____tmd_____" in low and "captcha" in low)
            )
            if not interesting:
                return
            if response.status != 200:
                return
            ct = (response.headers or {}).get("content-type", "")
            if "json" not in ct and "text" not in ct and "javascript" not in ct:
                return
            text = await response.text()
            if "imageData" not in text or "encryptToken" not in text:
                return
            payload = decode_newslidecaptcha_json(text)
            if payload is None or not payload.image_data:
                return
            if not is_valid_image_bytes(payload.image_data):
                logger.warning(
                    "newslidecaptcha imageData not a real image magic=%s len=%s",
                    payload.image_data[:8].hex(),
                    len(payload.image_data),
                )
                return
            if payload.ques is not None and not is_valid_image_bytes(payload.ques, min_size=80):
                logger.warning(
                    "newslidecaptcha ques not a real image magic=%s len=%s",
                    payload.ques[:8].hex() if payload.ques else "",
                    len(payload.ques or b""),
                )
                # ques 坏了仍记下主图，但双图打码会拒绝
            sink.append(payload)
            logger.info(
                "fruit payload captured via %s (image=%sB ques=%sB has_token=%s)",
                "newslidecaptcha" if "newslidecaptcha" in low else "captcha-json",
                len(payload.image_data or b""),
                len(payload.ques or b""),
                bool(payload.encrypt_token),
            )
        except Exception:  # noqa: BLE001
            return

    page.on("response", on_resp)

    def detach() -> None:
        try:
            page.remove_listener("response", on_resp)
        except Exception:  # noqa: BLE001
            pass

    return detach


async def attach_validation_listener(
    page: Page,
    tracker: ValidationTracker,
) -> Callable[[], None]:
    """按请求起始顺序记录 validate，仅保留脱敏关联字段。"""

    def on_request(request) -> None:  # type: ignore[no-untyped-def]
        try:
            low = (request.url or "").lower()
            if "newslidevalidate" not in low and "slidevalidate" not in low:
                return
            tracker.request_seq += 1
            query = parse_qs(urlsplit(request.url).query)
            params = {str(k).lower(): list(v) for k, v in query.items()}
            post_data = request.post_data or ""
            if post_data:
                try:
                    body = json.loads(post_data)
                except (TypeError, ValueError):
                    body = parse_qs(post_data)
                if isinstance(body, dict):
                    for key, value in body.items():
                        if isinstance(value, list):
                            params[str(key).lower()] = [str(v) for v in value]
                        elif value is not None:
                            params[str(key).lower()] = [str(value)]

            def number(name: str) -> float | None:
                values = params.get(name.lower()) or []
                try:
                    return float(values[0]) if values else None
                except (TypeError, ValueError):
                    return None

            token_values = params.get("encrypttoken") or []
            token_matches: bool | None = None
            if tracker.armed_token_hash and token_values:
                token_hash = hashlib.sha256(
                    str(token_values[0]).encode("utf-8", errors="ignore")
                ).hexdigest()
                token_matches = token_hash == tracker.armed_token_hash
            tracker.pending[request] = (
                tracker.request_seq,
                tracker.armed_puzzle_key,
                token_matches,
                number("per"),
                number("width"),
                bool(token_values),
            )
        except Exception:  # noqa: BLE001
            return

    async def on_resp(response) -> None:  # type: ignore[no-untyped-def]
        try:
            low = (response.url or "").lower()
            if "newslidevalidate" not in low and "slidevalidate" not in low:
                return
            pending = tracker.pending.pop(response.request, None)
            if pending is None:
                return
            request_seq, puzzle_key, token_matches, per, width, has_token = pending
            text = await response.text()
            code = decode_newslidevalidate_code(text)
            tracker.events.append(
                ValidationEvent(
                    request_seq=request_seq,
                    puzzle_key=puzzle_key,
                    code=code,
                    token_matches=token_matches,
                    per=per,
                    width=width,
                    has_token=has_token,
                )
            )
            logger.info(
                "fruit validate seq=%s http=%s code=%s token_match=%s per=%s width=%s",
                request_seq,
                response.status,
                code,
                token_matches,
                per,
                width,
            )
        except Exception:  # noqa: BLE001
            return

    page.on("request", on_request)
    page.on("response", on_resp)

    def detach() -> None:
        try:
            page.remove_listener("request", on_request)
            page.remove_listener("response", on_resp)
        except Exception:  # noqa: BLE001
            pass

    return detach


def enrich_payload(
    payload: CaptchaPayload,
    *,
    allow_ocr_compile: bool = False,
) -> CaptchaPayload:
    """解析题干目标 + ROI。默认不触发 OCR 首次编译（避免拖垮求解热路径）。"""
    if payload.ques and not payload.ques_text:
        payload.ques_text = ocr_ques_text(payload.ques, allow_compile=allow_ocr_compile)
        name, cnt = parse_target_from_text(payload.ques_text)
        payload.target_name = name
        payload.target_count = cnt
    if payload.image_data and not payload.focus_boxes:
        # 有目标名 → 颜色匹配 ROI；否则对全部较大 blob 做弱聚焦
        payload.focus_boxes = build_focus_boxes(
            payload.image_data,
            payload.target_name,
            payload.target_count or 1,
        )
        if not payload.focus_boxes and not payload.target_name:
            # 退回：所有较大物体
            blobs = segment_objects(payload.image_data)
            arr = _load_rgb(payload.image_data)
            h, w, _ = arr.shape
            for b in blobs[:6]:
                payload.focus_boxes.append(
                    (
                        max(0, b.x0 - 2),
                        max(0, b.y0 - 2),
                        min(w - 1, b.x1 + 2),
                        min(h - 1, b.y1 + 2),
                    )
                )
    if payload.target_name or payload.focus_boxes:
        logger.info(
            "fruit target=%s count=%s boxes=%s text=%s",
            payload.target_name,
            payload.target_count,
            len(payload.focus_boxes),
            (payload.ques_text or "")[:40],
        )
    return payload


async def _resolve_active_payload(
    payloads: list[CaptchaPayload],
    payload_hint: CaptchaPayload | None,
    *,
    round_i: int,
    allow_hint: bool = True,
) -> CaptchaPayload | None:
    """取当前题的 payload。

    优先用监听器 sink 里最新的 newslidecaptcha；
    payload_hint 仅在第 1 轮且 sink 仍空时可用（外层已截到、response 不能重放）。
    刷新后 allow_hint=False，禁止复用旧 token/双图（否则冰拓一直答旧题）。
    """
    active: CaptchaPayload | None = None
    if payloads:
        active = payloads[-1]
    elif allow_hint and round_i == 1 and payload_hint is not None:
        active = payload_hint
    if active is None:
        return None
    if round_i == 1 or not active.focus_boxes:
        try:
            active = enrich_payload(active)
        except Exception as exc:  # noqa: BLE001
            logger.debug("enrich payload: %s", exc)
    return active


async def solve_by_provider_offset(
    page: Page,
    provider: Any,
    *,
    success_check: Callable[[], Awaitable[bool]] | None = None,
    payload_hint: CaptchaPayload | None = None,
    image_logic_width: float = 320.0,
    max_rounds: int = 3,
    wait_timeout_s: float = 10.0,
) -> bool:
    """用国内/第三方打码拿到位移后，拟人拖动官方滑块。

    provider 需实现 solve_fruit_offset(image_b64, ques_b64) -> float|None
    返回值按 imageData 逻辑宽（默认 320）线性映射到 UI max_slide。

    双图类型（冰拓 1358/1357）**只**使用 newslidecaptcha 的 imageData+ques，
    绝不把 DOM 截图当 captchaData，避免烧点。
    """
    from app.browser.captcha.providers import (
        is_valid_image_bytes,
        map_bingtop_fruit_offset_to_ui,
        map_image_offset_to_ui,
        to_b64,
    )

    if provider is None:
        return False

    fruit_type = int(getattr(provider, "fruit_type", 0) or 0)
    dual_required = fruit_type in (1357, 1358) or fruit_type in getattr(
        provider, "DUAL_IMAGE_TYPES", frozenset()
    )
    # 冰拓 1358/1357 返回目标右缘距离，需减去滑块可见前缘；1359/其它用 auto
    map_mode = "fruit_right_edge" if fruit_type in (1357, 1358) else "auto"

    payloads: list[CaptchaPayload] = []
    validation_tracker = ValidationTracker()
    # 外层 hint 不预塞 sink：避免 round 失败 clear 后又被「假最新」污染
    used_hint_key: str | None = None
    if payload_hint is not None:
        used_hint_key = payload_hint.content_key()
    detach = await attach_payload_listener(page, payloads)
    detach_validation = await attach_validation_listener(page, validation_tracker)
    try:
        if not await wait_fruit_slider(page, timeout_s=wait_timeout_s):
            if success_check and await success_check():
                return True
            if not await detect_fruit_slider(page):
                return False

        allow_hint = True
        last_used_key = ""
        paid_attempts = 0
        preparation_attempts = 0
        max_preparation_attempts = max(3, max_rounds + 2)
        while paid_attempts < max_rounds and preparation_attempts < max_preparation_attempts:
            preparation_attempts += 1
            round_i = paid_attempts + 1
            if success_check and await success_check():
                return True
            if not await detect_fruit_slider(page):
                return True

            # 等 newslidecaptcha（出题可能比 UI 晚几百 ms～数秒）
            # 刷新后 encryptToken 常不变，用 image 内容指纹识别新题
            n_before_wait = len(payloads)
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                active_try = (
                    payloads[-1]
                    if payloads
                    else (payload_hint if allow_hint and round_i == 1 else None)
                )
                if (
                    active_try
                    and active_try.image_data
                    and is_valid_image_bytes(active_try.image_data)
                    and (
                        not dual_required
                        or (
                            active_try.ques
                            and is_valid_image_bytes(active_try.ques, min_size=80)
                        )
                    )
                ):
                    key = active_try.content_key()
                    if last_used_key and key == last_used_key:
                        # 仍是刚答过的题：等 listener 收到新图
                        if len(payloads) > n_before_wait:
                            # 有新包但仍同 key → 异常，继续等
                            pass
                        await page.wait_for_timeout(200)
                        continue
                    break
                await page.wait_for_timeout(200)

            active = await _resolve_active_payload(
                payloads, payload_hint, round_i=round_i, allow_hint=allow_hint
            )
            if active and last_used_key and active.content_key() == last_used_key:
                logger.warning(
                    "provider path: stale payload key=%s round=%s, refresh",
                    last_used_key[:40],
                    round_i,
                )
                payloads.clear()
                allow_hint = False
                await _click_refresh(page)
                await page.wait_for_timeout(1500)
                continue

            geo = await measure_geometry(page)
            if geo is None:
                logger.warning("provider path: geometry missing (round=%s)", round_i)
                await page.wait_for_timeout(600)
                continue

            img_b64 = ""
            ques_b64 = ""
            if active and active.image_data and is_valid_image_bytes(active.image_data):
                img_b64 = to_b64(active.image_data)
            if active and active.ques and is_valid_image_bytes(active.ques, min_size=80):
                ques_b64 = to_b64(active.ques)

            # 双图打码：没有完整 newslidecaptcha 就刷新等下一轮，禁止截图兜底
            if dual_required and (not img_b64 or not ques_b64):
                logger.warning(
                    "provider path: wait newslidecaptcha dual images (round=%s img=%s ques=%s)",
                    round_i,
                    bool(img_b64),
                    bool(ques_b64),
                )
                n_before = len(payloads)
                allow_hint = False
                await _click_refresh(page)
                deadline2 = time.monotonic() + 6.0
                while time.monotonic() < deadline2 and len(payloads) <= n_before:
                    await page.wait_for_timeout(200)
                continue

            # 单图类型才允许截图兜底
            if not img_b64 and not dual_required:
                png = await _screenshot_target(geo, page)
                if png:
                    img_b64 = to_b64(png)
                    image_logic_width = float(
                        (geo.image_box or {}).get("width") or geo.max_slide or 320.0
                    )

            if not img_b64:
                logger.warning("provider path: no image for round=%s", round_i)
                allow_hint = False
                await _click_refresh(page)
                await page.wait_for_timeout(1000)
                continue

            logger.info(
                "provider upload prep type=%s img_b64=%s ques_b64=%s has_token=%s key=%s map=%s",
                fruit_type,
                len(img_b64),
                len(ques_b64),
                bool(active and active.encrypt_token),
                (active.content_key()[:48] if active else ""),
                map_mode,
            )
            paid_attempts += 1
            round_i = paid_attempts
            try:
                raw_off = await provider.solve_fruit_offset(img_b64, ques_b64)
            except Exception as exc:  # noqa: BLE001
                logger.warning("provider solve_fruit_offset error: %s", exc)
                raw_off = None

            if raw_off is None:
                logger.warning(
                    "provider returned no offset (round=%s/%s)",
                    paid_attempts,
                    max_rounds,
                )
                if paid_attempts < max_rounds:
                    logger.warning(
                        "provider returned no offset; refreshing captcha to retry (%s/%s)",
                        paid_attempts,
                        max_rounds,
                    )
                    payloads.clear()
                    allow_hint = False
                    await _click_refresh(page)
                    await page.wait_for_timeout(1500)
                    continue
                logger.warning(
                    "provider (bingtop) failed %s times consecutively without offset; stopping provider attempts",
                    max_rounds,
                )
                return False

            if active is not None and payloads:
                newest_key = payloads[-1].content_key()
                if newest_key != active.content_key():
                    logger.info(
                        "provider result discarded because puzzle changed old=%s new=%s",
                        active.content_key()[:16],
                        newest_key[:16],
                    )
                    allow_hint = False
                    continue

            if active is not None:
                last_used_key = active.content_key()
            # hint 用过一次即失效
            if active and used_hint_key and active.content_key() == used_hint_key:
                allow_hint = False

            # 逻辑宽：有 payload 用真实图宽，否则默认 320
            logic_w = image_logic_width
            if active and active.image_data:
                try:
                    arr_w = _load_rgb(active.image_data).shape[1]
                    if arr_w > 0:
                        logic_w = float(arr_w)
                except Exception:  # noqa: BLE001
                    logic_w = 320.0

            # provider 可能等待较久，重新读取响应式布局后再换算坐标。
            geo = await measure_geometry(page) or geo
            if active is not None and payloads:
                newest_key = payloads[-1].content_key()
                if newest_key != active.content_key():
                    logger.info(
                        "provider result discarded before mapping because puzzle changed old=%s new=%s",
                        active.content_key()[:16],
                        newest_key[:16],
                    )
                    allow_hint = False
                    continue
            ui_width = float(
                (geo.image_box or {}).get("width")
                or geo.track_box.get("width")
                or 320.0
            )
            # 一题只拖一次：失败后阿里会自动换图，多候选会拖到新题上白烧。
            if map_mode == "fruit_right_edge":
                ui_x = map_bingtop_fruit_offset_to_ui(
                    float(raw_off),
                    max_slide=geo.max_slide,
                    image_width=logic_w,
                    ui_width=ui_width,
                    edge_pad=FRUIT_PROTOCOL_EDGE_PX,
                    margin=FRUIT_REVEAL_MARGIN_PX,
                    style="right_edge",
                )
                ui_raw = map_bingtop_fruit_offset_to_ui(
                    float(raw_off),
                    max_slide=geo.max_slide,
                    image_width=logic_w,
                    ui_width=ui_width,
                    edge_pad=FRUIT_PROTOCOL_EDGE_PX,
                    style="raw",
                )
                logger.info(
                    "provider map styles edge_ui=%.1f raw_ui=%.1f (drag edge_ui)",
                    ui_x,
                    ui_raw,
                )
            else:
                ui_x = map_image_offset_to_ui(
                    float(raw_off),
                    max_slide=geo.max_slide,
                    image_width=logic_w,
                    mode=map_mode,
                )

            logger.info(
                "provider fruit offset raw=%.2f logic_w=%.1f ui_x=%.1f max_slide=%.1f map=%s",
                float(raw_off),
                logic_w,
                ui_x,
                geo.max_slide,
                map_mode,
            )

            n_payloads_before_drag = len(payloads)
            active_key = active.content_key() if active is not None else ""
            validation_after_seq = validation_tracker.request_seq

            async def arm_if_current() -> bool:
                if active is not None and payloads:
                    if payloads[-1].content_key() != active_key:
                        return False
                validation_tracker.arm(
                    active_key,
                    active.encrypt_token if active is not None else "",
                )
                return True

            async def mark_validation_window() -> bool:
                nonlocal validation_after_seq
                if active is not None and payloads:
                    if payloads[-1].content_key() != active_key:
                        validation_tracker.disarm()
                        return False
                validation_after_seq = validation_tracker.request_seq
                return True

            drag_meta = await drag_to_offset(
                page,
                geo,
                ui_x,
                release=True,
                before_mouse_down=arm_if_current,
                before_mouse_up=mark_validation_window,
            )
            if drag_meta.get("aborted"):
                validation_tracker.disarm()
                allow_hint = False
                continue
            if drag_meta.get("stuck"):
                validation_tracker.disarm()
                logger.warning(
                    "provider path: knob stuck at ui_x=%.1f; refresh and retry",
                    ui_x,
                )
                allow_hint = False
                # 不跟手的拖动未形成有效答案；退回付费计数，避免白烧题额
                paid_attempts = max(0, paid_attempts - 1)
                if payloads and active:
                    payloads[:] = [
                        p for p in payloads if p.content_key() != active.content_key()
                    ]
                await _click_refresh(page)
                await page.wait_for_timeout(1200)
                continue

            # `per` is useful evidence but not a safe hard correlation key. The page
            # derives it from its own logical options.width, which can differ from
            # the measured responsive DOM width. Sequence + puzzle key + token bind
            # the response to this drag without discarding a valid result.
            protocol_per = round(
                (ui_x + FRUIT_PROTOCOL_EDGE_PX) / max(ui_width, 1.0), 3
            )
            validate_deadline = time.monotonic() + 1.5
            validate_event = validation_tracker.find_event(
                after_seq=validation_after_seq,
                puzzle_key=active_key,
                require_token=bool(active and active.encrypt_token),
            )
            while validate_event is None and time.monotonic() < validate_deadline:
                await page.wait_for_timeout(50)
                validate_event = validation_tracker.find_event(
                    after_seq=validation_after_seq,
                    puzzle_key=active_key,
                    require_token=bool(active and active.encrypt_token),
                )
            validation_tracker.disarm()
            validate_code = validate_event.code if validate_event is not None else None
            if validate_event is not None and validate_event.per is not None:
                logger.info(
                    "provider validate correlation seq=%s protocol_per=%.3f actual_per=%.3f",
                    validate_event.request_seq,
                    protocol_per,
                    validate_event.per,
                )
            delta_mouse = drag_meta.get("mouse_dx", 0) - ui_x
            delta_knob = (
                (drag_meta.get("knob_dx", 0) - ui_x)
                if drag_meta.get("knob_dx", -1) >= 0
                else float("nan")
            )
            logger.info(
                "provider drag vs bingtop: raw=%.2f ui_x=%.1f mouse_dx=%.2f knob_dx=%.2f "
                "delta_mouse=%.2f delta_knob=%.2f",
                float(raw_off),
                ui_x,
                drag_meta.get("mouse_dx", -1),
                drag_meta.get("knob_dx", -1),
                delta_mouse,
                delta_knob,
            )
            if os.environ.get("DAXI_CAPTCHA_PROBE") == "1":
                try:
                    from app.crawlers.damai.fruit_probe import write_probe_artifacts

                    out_dir = Path("data/captcha_probe/bingtop_live")
                    canvas_after: bytes | None = None
                    try:
                        canvas_after = await _canvas_png_bytes(page)
                    except Exception:  # noqa: BLE001
                        canvas_after = None
                    offline_ui = None
                    try:
                        offline_ui = estimate_offset_from_payload(
                            active,
                            max_slide=float(geo.max_slide),
                            image_logic_width=logic_w,
                        )
                    except Exception:  # noqa: BLE001
                        offline_ui = None
                    write_probe_artifacts(
                        out_dir,
                        image_data=active.image_data if active else None,
                        ques=active.ques if active else None,
                        raw_off=float(raw_off),
                        ui_x=float(ui_x),
                        max_slide=float(geo.max_slide),
                        logic_w=float(logic_w),
                        ui_width=float(ui_width),
                        edge_pad=FRUIT_PROTOCOL_EDGE_PX,
                        map_mode=map_mode,
                        round_i=round_i,
                        validate_code=validate_code,
                        target_name=(active.target_name if active else "") or "",
                        mouse_dx=drag_meta.get("mouse_dx"),
                        knob_dx=drag_meta.get("knob_dx"),
                        track_sum_dx=drag_meta.get("track_sum_dx"),
                        delta_mouse=delta_mouse,
                        delta_knob=delta_knob if delta_knob == delta_knob else None,
                        protocol_per=protocol_per,
                        actual_per=(
                            validate_event.per if validate_event is not None else None
                        ),
                        validate_width=(
                            validate_event.width if validate_event is not None else None
                        ),
                        token_matches=(
                            validate_event.token_matches
                            if validate_event is not None
                            else None
                        ),
                        drag_duration_ms=drag_meta.get("drag_duration_ms"),
                        has_token=bool(active and active.encrypt_token),
                        img_key=active.content_key() if active else "",
                        offline_ui=offline_ui,
                        canvas_after=canvas_after,
                        selected_key="A_right_edge"
                        if map_mode == "fruit_right_edge"
                        else "B_raw",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("write probe artifacts failed: %s", exc)

            if validate_code == 0:
                logger.info("fruit slider accepted by validate at ui_x=%.1f", ui_x)
                return True
            if validate_code is not None:
                logger.info(
                    "fruit slider rejected by validate code=%s at ui_x=%.1f",
                    validate_code,
                    ui_x,
                )

            # 没拿到明确失败响应时，再用 UI 状态作兜底。
            await page.wait_for_timeout(300)
            if validate_code is None and success_check:
                if await success_check():
                    logger.info("fruit slider cleared via provider at ui_x=%.1f", ui_x)
                    return True
            elif validate_code is None and not await detect_fruit_slider(page):
                logger.info("fruit slider UI gone via provider at ui_x=%.1f", ui_x)
                return True

            allow_hint = False
            # 失败后阿里常自动发新 newslidecaptcha：保留 sink 里新图，禁止 clear
            if len(payloads) > n_payloads_before_drag and active:
                newest = payloads[-1]
                if newest.content_key() != active.content_key():
                    logger.info(
                        "provider path: auto new puzzle after fail key=%s → next round",
                        newest.content_key()[:40],
                    )
                    continue

            # 等一会儿自动换题
            wait_new = time.monotonic() + 3.0
            got_new = False
            while time.monotonic() < wait_new:
                if not await detect_fruit_slider(page):
                    if validate_code is None:
                        return True
                    await page.wait_for_timeout(100)
                    continue
                if (
                    payloads
                    and active
                    and payloads[-1].content_key() != active.content_key()
                ):
                    got_new = True
                    break
                await page.wait_for_timeout(200)
            if got_new:
                logger.info("provider path: new puzzle arrived, next round without refresh")
                continue

            if validate_code is not None:
                logger.warning(
                    "validate rejected code=%s but no replacement puzzle arrived",
                    validate_code,
                )
                return False

            logger.info("provider fruit round %s not cleared, refresh", round_i)
            # 只丢弃当前已用题，保留之后到达的；若没有新的再 refresh
            if payloads and active:
                payloads[:] = [
                    p for p in payloads if p.content_key() != active.content_key()
                ]
            if not payloads:
                await _click_refresh(page)
                await page.wait_for_timeout(1500)

        return success_check is not None and await success_check()
    finally:
        detach_validation()
        detach()


async def solve_fruit_slider(
    page: Page,
    *,
    step: float = 5.0,
    success_check: Callable[[], Awaitable[bool]] | None = None,
    max_rounds: int = 3,
    wait_timeout_s: float = 10.0,
    payload_hint: CaptchaPayload | None = None,
    provider: Any = None,
    strategy: str = "provider_first",
) -> bool:
    """求解水果滑块。

    strategy:
      - local_first: 本地打分优先，失败再打码（默认，省钱）
      - provider_first: 打码优先，失败回退本地
      - local_only / provider_only
    """
    strategy = (strategy or "provider_first").lower().strip()
    use_local = strategy in ("local_first", "provider_first", "local_only", "")
    use_provider = provider is not None and strategy in (
        "local_first",
        "provider_first",
        "provider_only",
    )

    async def _local() -> bool:
        return await _solve_fruit_slider_local(
            page,
            step=step,
            success_check=success_check,
            max_rounds=max_rounds,
            wait_timeout_s=wait_timeout_s,
            payload_hint=payload_hint,
        )

    async def _provider() -> bool:
        return await solve_by_provider_offset(
            page,
            provider,
            success_check=success_check,
            payload_hint=payload_hint,
            max_rounds=max_rounds,
            wait_timeout_s=wait_timeout_s,
        )

    if strategy == "provider_only":
        return await _provider() if use_provider else False
    if strategy == "local_only" or not use_provider:
        return await _local() if use_local else False

    if strategy == "provider_first":
        if await _provider():
            return True
        logger.info("provider fruit failed, fallback local scan")
        # 不再用外层 early hint：可能已是答失败的旧题
        return await _solve_fruit_slider_local(
            page,
            step=step,
            success_check=success_check,
            max_rounds=max_rounds,
            wait_timeout_s=wait_timeout_s,
            payload_hint=None,
        )

    # local_first
    if await _local():
        return True
    if use_provider:
        logger.info("local fruit failed, fallback provider")
        # 本地若因无图/无 update_pos 失败且尚未答废该题，把外层 early hint
        # 交给冰拓；provider 内部 listener 仍会接刷新后的新题。
        return await solve_by_provider_offset(
            page,
            provider,
            success_check=success_check,
            payload_hint=payload_hint,
            max_rounds=max_rounds,
            wait_timeout_s=wait_timeout_s,
        )
    return False


async def _solve_fruit_slider_local(
    page: Page,
    *,
    step: float = 5.0,
    success_check: Callable[[], Awaitable[bool]] | None = None,
    max_rounds: int = 2,
    wait_timeout_s: float = 10.0,
    payload_hint: CaptchaPayload | None = None,
) -> bool:
    """本地求解水果滑块。

    正确链路：
      1) 等/拦截 newslidecaptcha → imageData + ques + encryptToken
      2) 页内 document.__update_pos(x) 离线估最优位移（不拖鼠标、不触发 verify）
      3) 一次性拟人 drag 到该位移并松手，走官方 newslidevalidate
      4) 无 __update_pos 时才回退「按住滑块扫描」兜底
    """
    payloads: list[CaptchaPayload] = []
    detach = await attach_payload_listener(page, payloads)
    allow_hint = True

    try:
        if not await wait_fruit_slider(page, timeout_s=wait_timeout_s):
            if success_check and await success_check():
                return True
            if not await detect_fruit_slider(page):
                return False

        for round_i in range(1, max_rounds + 1):
            if success_check and await success_check():
                return True
            if not await detect_fruit_slider(page):
                return True

            # 等出题接口（刷新后会再来）；无图则主动 refresh 一次
            if not payloads and not (allow_hint and payload_hint is not None):
                deadline = time.monotonic() + 2.5
                while time.monotonic() < deadline and not payloads:
                    await page.wait_for_timeout(150)
                if not payloads and round_i == 1:
                    await _click_refresh(page)
                    deadline2 = time.monotonic() + 5.0
                    while time.monotonic() < deadline2 and not payloads:
                        await page.wait_for_timeout(150)

            focus_boxes: list[tuple[int, int, int, int]] = []
            template_bytes: bytes | None = None
            active = await _resolve_active_payload(
                payloads, payload_hint, round_i=round_i, allow_hint=allow_hint
            )
            if active is not None and allow_hint and payload_hint is not None:
                # hint 只用一轮
                if not payloads or active is payload_hint:
                    allow_hint = False
            if active is not None:
                focus_boxes = list(active.focus_boxes or [])
                template_bytes = active.image_data
                logger.info(
                    "fruit payload has_token=%s target=%s count=%s boxes=%s text=%s",
                    bool(active.encrypt_token),
                    active.target_name,
                    active.target_count,
                    len(focus_boxes),
                    (active.ques_text or "")[:40],
                )
            else:
                logger.warning("fruit: no newslidecaptcha payload yet (round=%s)", round_i)

            geo = await measure_geometry(page)
            if geo is None:
                logger.warning("fruit UI present but geometry missing (round=%s)", round_i)
                await page.wait_for_timeout(800)
                continue

            logger.info(
                "fruit slider round=%s/%s max_slide=%.1f step=%.1f focus=%s "
                "template=%s update_pos=%s",
                round_i,
                max_rounds,
                geo.max_slide,
                step,
                len(focus_boxes),
                bool(template_bytes),
                await _has_update_pos(page),
            )

            # 0) 纯离线：imageData 目标右缘 → UI x（visible_right ≈ x+24）
            offline = estimate_offset_from_payload(active, max_slide=geo.max_slide)
            logic_w = 320.0
            if active and active.image_data:
                try:
                    logic_w = float(_load_rgb(active.image_data).shape[1]) or 320.0
                except Exception:  # noqa: BLE001
                    logic_w = 320.0
            if offline is not None:
                logger.info(
                    "offline prior target=%s boxes=%s ui_x=%.1f max_slide=%.1f logic_w=%.0f",
                    None if active is None else active.target_name,
                    len(focus_boxes),
                    offline,
                    geo.max_slide,
                    logic_w,
                )

            # 1) 若 WASM 钩子可用，用 updatePos 在 offline 附近精修（不拖鼠标）
            up_info = await _resolve_update_pos(page)
            logger.info("secCaptcha resolve: %s", up_info)
            best: float | None = offline
            method = "offline" if offline is not None else "none"
            samples: list[tuple[float, float]] = []

            if up_info.get("ok") and offline is not None:
                # 只在先验邻域用 updatePos 采样，找「目标刚好完整露出」的最小 x
                best_up, samples = await estimate_offset_via_update_pos(
                    page,
                    geo,
                    template_bytes=template_bytes,
                    focus_boxes=focus_boxes or None,
                    step=max(2.0, step / 1.5),
                    settle_ms=30,
                )
                if best_up is not None:
                    # 与 offline 差太大 → 信 offline（粉罩全轨分仍可能漂）
                    if abs(best_up - offline) <= max(28.0, geo.max_slide * 0.2):
                        best = best_up
                        method = "update_pos+offline"
                    else:
                        logger.warning(
                            "updatePos=%.1f far from offline=%.1f, keep offline",
                            best_up,
                            offline,
                        )
                        method = "offline_prefer"

            if best is None:
                logger.warning("fruit: no offline offset (need imageData+ROI), refresh")
                await _click_refresh(page)
                await page.wait_for_timeout(1200)
                payload_hint = None
                allow_hint = False
                payloads.clear()
                continue

            best = max(0.0, min(geo.max_slide, float(best)))
            logger.info(
                "fruit estimate method=%s best_x=%.1f offline=%s samples=%s",
                method,
                best,
                None if offline is None else round(offline, 1),
                len(samples),
            )
            # 调试落盘：只在 DAXI_CAPTCHA_PROBE=1 时写。交付版默认关闭，
            # 否则每碰到一次水果验证码就往用户数据目录默写图片/JSON，永不清理。
            if os.environ.get("DAXI_CAPTCHA_PROBE") == "1":
                try:
                    dbg = Path("data/captcha_probe/fruit_live")
                    dbg.mkdir(parents=True, exist_ok=True)
                    (dbg / f"curve_round{round_i}.json").write_text(
                        json.dumps(
                            {
                                "best": best,
                                "offline": offline,
                                "method": method,
                                "target": None if active is None else active.target_name,
                                "boxes": focus_boxes,
                                "samples": [{"x": x, "s": round(s, 3)} for x, s in samples],
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    if template_bytes:
                        (dbg / f"template_round{round_i}.jpg").write_bytes(template_bytes)
                except Exception:  # noqa: BLE001
                    pass

            # 2) 一次性拟人拖动提交。失败会生成新题，旧坐标绝不复用。
            candidates: list[float] = [best]

            cleared = False
            for ci, trial in enumerate(candidates):
                if not await detect_fruit_slider(page):
                    cleared = True
                    break
                geo = await measure_geometry(page)
                if geo is None:
                    break
                trial = max(0.0, min(geo.max_slide, trial))
                logger.info(
                    "fruit drag candidate %s/%s x=%.1f",
                    ci + 1,
                    len(candidates),
                    trial,
                )
                active_key = active.content_key() if active is not None else ""

                async def puzzle_is_current() -> bool:
                    return not (
                        active is not None
                        and payloads
                        and payloads[-1].content_key() != active_key
                    )

                drag_meta = await drag_to_offset(
                    page,
                    geo,
                    trial,
                    release=True,
                    before_mouse_down=puzzle_is_current,
                )
                if drag_meta.get("aborted"):
                    logger.info("fruit local result discarded because puzzle changed")
                    break
                await page.wait_for_timeout(1100)
                if success_check:
                    if await success_check():
                        logger.info("fruit slider cleared at x=%.1f", trial)
                        return True
                elif not await detect_fruit_slider(page):
                    logger.info("fruit slider UI gone at x=%.1f", trial)
                    return True
                # verify 失败会出新题：payload 监听会追加，下一候选前若题已变则跳出重来
                if payloads and active is not None:
                    latest = payloads[-1]
                    if latest.content_key() != active.content_key():
                        logger.info("captcha puzzle changed after fail")
                        break

            if cleared or (success_check and await success_check()):
                return True
            if not await detect_fruit_slider(page):
                return True

            logger.info("fruit slider round %s not cleared, refresh", round_i)
            await _click_refresh(page)
            await page.wait_for_timeout(1500)
            payload_hint = None
            allow_hint = False
            payloads.clear()

        return success_check is not None and await success_check()
    finally:
        detach()
