"""通用滑块拖动（各平台 captcha 策略复用）。"""

from __future__ import annotations

import logging

from playwright.async_api import Page, Locator

from app.browser.captcha.human_track import distance_candidates, generate_slider_track

logger = logging.getLogger(__name__)


async def find_first_visible(page: Page, selectors: list[str]) -> Locator | None:
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if await loc.count() == 0:
                continue
            if await loc.is_visible(timeout=500):
                return loc
        except Exception:  # noqa: BLE001
            continue
    return None


async def measure_track_width(page: Page, track_selectors: list[str], knob_selectors: list[str]) -> float:
    """估算可滑动距离 = 轨道宽 - 滑块宽。"""
    track = await find_first_visible(page, track_selectors)
    knob = await find_first_visible(page, knob_selectors)
    if track is None:
        # 默认值：多数阿里/美团滑块轨道约 260~300
        return 260.0
    box = await track.bounding_box()
    if not box:
        return 260.0
    width = box["width"]
    if knob is not None:
        kbox = await knob.bounding_box()
        if kbox:
            width = max(40.0, width - kbox["width"])
    return float(width)


async def drag_slider(
    page: Page,
    *,
    knob: Locator,
    distance: float,
) -> None:
    box = await knob.bounding_box()
    if not box:
        raise RuntimeError("slider knob not visible")

    start_x = box["x"] + box["width"] / 2
    start_y = box["y"] + box["height"] / 2

    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    await page.wait_for_timeout(80)

    x, y = start_x, start_y
    for dx, dy, delay in generate_slider_track(distance):
        x += dx
        y += dy
        await page.mouse.move(x, y, steps=1)
        await page.wait_for_timeout(delay)

    await page.wait_for_timeout(120)
    await page.mouse.up()
    await page.wait_for_timeout(400)


async def try_slider_solve(
    page: Page,
    *,
    knob_selectors: list[str],
    track_selectors: list[str],
    success_check,
    max_attempts: int = 3,
) -> bool:
    """按候选距离多次尝试拖动滑块。success_check: async () -> bool"""
    knob = await find_first_visible(page, knob_selectors)
    if knob is None:
        logger.debug("no slider knob found")
        return False

    base = await measure_track_width(page, track_selectors, knob_selectors)
    for i, dist in enumerate(distance_candidates(base)[:max_attempts]):
        logger.info("slider attempt %s distance=%.1f", i + 1, dist)
        knob = await find_first_visible(page, knob_selectors)
        if knob is None:
            return await success_check()
        try:
            await drag_slider(page, knob=knob, distance=dist)
        except Exception as exc:  # noqa: BLE001
            logger.warning("slider drag failed: %s", exc)
            continue
        if await success_check():
            return True
        await page.wait_for_timeout(600)
    return False
