"""模拟真人滑动轨迹。"""

from __future__ import annotations

import math
import random


def generate_slider_track(distance: float, *, steps: int | None = None) -> list[tuple[float, float, int]]:
    """生成 (dx, dy, delay_ms) 序列，合计横向约等于 distance。

    采用缓入缓出 + 轻微抖动，降低被识别为机器的概率。
    """
    if distance <= 0:
        return []

    n = steps or max(25, min(55, int(distance / 4)))
    track: list[tuple[float, float, int]] = []
    moved = 0.0

    for i in range(n):
        t = (i + 1) / n
        # easeInOutCubic
        if t < 0.5:
            ease = 4 * t * t * t
        else:
            ease = 1 - pow(-2 * t + 2, 3) / 2

        target = distance * ease
        dx = target - moved
        # 前段加速、末段减速时纵向微抖
        dy = random.uniform(-1.2, 1.2) * (1.0 - abs(0.5 - t) * 1.5)
        if i < 3:
            delay = random.randint(12, 28)
        elif i > n - 5:
            delay = random.randint(18, 45)
        else:
            delay = random.randint(8, 22)
        track.append((dx, dy, delay))
        moved = target

    # 末尾回拉一点再补上，模拟人手校准
    overshoot = random.uniform(1.5, 4.0)
    track.append((overshoot, random.uniform(-0.5, 0.5), random.randint(20, 40)))
    track.append((-overshoot, random.uniform(-0.3, 0.3), random.randint(30, 60)))

    return track


def distance_candidates(base: float) -> list[float]:
    """多次尝试时使用的距离候选（全长附近微扰）。"""
    base = max(base, 10.0)
    return [
        base * 0.92,
        base * 0.96,
        base,
        min(base * 1.02, base + 6),
        base * 0.88 + random.uniform(0, 4),
    ]


def estimate_gap_by_contrast(bg_bytes: bytes, slice_bytes: bytes) -> float | None:
    """可选：用简单像素对比估计缺口（无 OpenCV 时的轻量方案）。

    需要 pillow；未安装则返回 None。
    """
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        return None

    try:
        bg = Image.open(BytesIO(bg_bytes)).convert("RGB")
        piece = Image.open(BytesIO(slice_bytes)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None

    bw, bh = bg.size
    pw, ph = piece.size
    if bw < 20 or pw < 5:
        return None

    # 简化：在背景上水平扫描，找与滑块边缘差异最大的列
    # 实际拼图算法因平台而异，这里只做粗估
    bg_l = bg.convert("L")
    best_x = 0
    best_score = -1.0
    step = max(1, bw // 80)
    for x in range(0, bw - pw, step):
        # 取竖条边缘梯度
        score = 0.0
        for y in range(0, min(bh, ph), max(1, ph // 20)):
            p1 = bg_l.getpixel((x, y))
            p2 = bg_l.getpixel((min(x + 2, bw - 1), y))
            score += abs(p1 - p2)
        # 加一点正弦扰动避免总贴边
        score += math.sin(x / 17.0) * 0.01
        if score > best_score:
            best_score = score
            best_x = x

    return float(best_x)
