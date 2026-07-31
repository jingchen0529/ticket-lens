"""猫眼验证码策略（美团 Yoda / 滑块 / 风控页）。

与大麦分离：选择器、URL 特征、重试逻辑均不同。
"""

from __future__ import annotations

import base64
from typing import Any

from playwright.async_api import Frame, Page

from app.browser.captcha.base import (
    CaptchaChallenge,
    CaptchaKind,
    CaptchaSolveResult,
    CaptchaSolver,
)
from app.browser.captcha.providers import CaptchaProvider, create_provider
from app.browser.captcha.slider import find_first_visible, try_slider_solve

MAOYAN_URL_MARKERS = (
    "yoda",
    "verify.meituan",
    "passport.meituan",
    "captcha",
    "/risk/",
    "block",
)

MAOYAN_TEXT_MARKERS = (
    "请完成安全验证",
    "滑动验证",
    "拖动滑块",
    "请向右拖动滑块",
    "人机验证",
    "访问行为异常",
    "验证失败",
    "网络异常，请刷新",
)

MAOYAN_KNOB_SELECTORS = [
    ".yoda-slider-btn",
    ".yoda-slider-handle",
    ".slider-btn",
    ".move-btn",
    ".handler",
    ".slide-btn",
    "[class*='yoda'] [class*='slider']",
    "[class*='slider-btn']",
    "[class*='slideBtn']",
    ".box-btn",
    "#slider-button",
]

MAOYAN_TRACK_SELECTORS = [
    ".yoda-slider-wrapper",
    ".yoda-slider-bg",
    ".slider-track",
    "[class*='slider-bar']",
    "[class*='slide-track']",
    ".box-slider",
]


class MaoyanCaptchaSolver(CaptchaSolver):
    platform = "maoyan"
    max_auto_attempts = 4

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        captcha_cfg = self._captcha_cfg()
        # 允许平台级覆盖 provider / api_key
        provider = getattr(captcha_cfg, "provider", "local_slider")
        api_key = getattr(captcha_cfg, "api_key", "") or ""
        # sources.maoyan.captcha 覆盖
        src = getattr(getattr(config, "sources", None), "maoyan", None)
        if src is not None and getattr(src, "captcha", None):
            pc = src.captcha
            provider = getattr(pc, "provider", None) or provider
            api_key = getattr(pc, "api_key", None) or api_key
        self.provider: CaptchaProvider | None = create_provider(provider, api_key)

    async def detect(self, page: Page) -> CaptchaChallenge | None:
        url = page.url.lower()
        for m in MAOYAN_URL_MARKERS:
            if m in url and m != "captcha":  # captcha 太泛，需结合其它
                return CaptchaChallenge(kind=CaptchaKind.PUNISH, reason=f"url:{m}")
        if "captcha" in url and any(x in url for x in ("maoyan", "meituan", "yoda")):
            return CaptchaChallenge(kind=CaptchaKind.PUNISH, reason="url:captcha")

        for frame in page.frames:
            if frame == page.main_frame:
                continue
            furl = (frame.url or "").lower()
            if any(m in furl for m in ("yoda", "verify", "captcha", "meituan")):
                return CaptchaChallenge(
                    kind=CaptchaKind.IFRAME,
                    reason=f"frame:{furl[:80]}",
                    meta={"frame_url": frame.url},
                )

        knob = await find_first_visible(page, MAOYAN_KNOB_SELECTORS)
        if knob is not None:
            return CaptchaChallenge(kind=CaptchaKind.SLIDER, reason="knob_visible")

        try:
            content = (await page.content()).lower()
        except Exception:  # noqa: BLE001
            content = ""

        for m in MAOYAN_TEXT_MARKERS:
            if m.lower() in content:
                return CaptchaChallenge(
                    kind=CaptchaKind.SLIDER if "滑" in m else CaptchaKind.UNKNOWN,
                    reason=f"text:{m}",
                )

        # 美团 yoda 容器
        for sel in (".yoda-slider", "#yoda-slider", "[class*='yoda-']", ".verify-wrap"):
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=200):
                    return CaptchaChallenge(kind=CaptchaKind.SLIDER, reason=f"dom:{sel}")
            except Exception:  # noqa: BLE001
                continue

        return None

    async def solve_auto(self, page: Page, challenge: CaptchaChallenge) -> CaptchaSolveResult:
        async def cleared() -> bool:
            return await self.detect(page) is None

        ok = await try_slider_solve(
            page,
            knob_selectors=MAOYAN_KNOB_SELECTORS,
            track_selectors=MAOYAN_TRACK_SELECTORS,
            success_check=cleared,
            max_attempts=3,
        )
        if not ok:
            ok = await self._drag_in_frames(page, cleared)

        if ok:
            return CaptchaSolveResult(ok=True, method="local_slider", message="maoyan slider ok")

        if self.provider:
            if await self._try_provider_image(page):
                return CaptchaSolveResult(
                    ok=True,
                    method=f"provider:{self.provider.name}",
                    message="image ok",
                )

        # 点「刷新」后再滑一次
        for sel in ("text=刷新", "text=换一张", ".refresh", "[class*='refresh']"):
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=200):
                    await loc.click()
                    await page.wait_for_timeout(1000)
                    break
            except Exception:  # noqa: BLE001
                continue

        ok = await try_slider_solve(
            page,
            knob_selectors=MAOYAN_KNOB_SELECTORS,
            track_selectors=MAOYAN_TRACK_SELECTORS,
            success_check=cleared,
            max_attempts=2,
        )
        if ok:
            return CaptchaSolveResult(ok=True, method="local_slider_retry", message="after refresh")

        return CaptchaSolveResult(ok=False, method="local_slider", message="maoyan auto solve failed")

    async def _drag_in_frames(self, page: Page, cleared) -> bool:
        from app.browser.captcha.human_track import distance_candidates, generate_slider_track

        for frame in page.frames:
            for sel in MAOYAN_KNOB_SELECTORS:
                try:
                    loc = frame.locator(sel).first
                    if await loc.count() == 0 or not await loc.is_visible(timeout=300):
                        continue
                    box = await loc.bounding_box()
                    if not box:
                        continue
                    for dist in distance_candidates(240.0)[:3]:
                        x = box["x"] + box["width"] / 2
                        y = box["y"] + box["height"] / 2
                        await page.mouse.move(x, y)
                        await page.mouse.down()
                        cx, cy = x, y
                        for dx, dy, delay in generate_slider_track(dist):
                            cx += dx
                            cy += dy
                            await page.mouse.move(cx, cy)
                            await page.wait_for_timeout(delay)
                        await page.mouse.up()
                        await page.wait_for_timeout(700)
                        if await cleared():
                            return True
                        box = await loc.bounding_box() or box
                except Exception:  # noqa: BLE001
                    continue
        return False

    async def _try_provider_image(self, page: Page) -> bool:
        if not self.provider:
            return False
        for sel in ("img.yoda-captcha", ".captcha-img img", "img[src*='captcha']"):
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0 or not await loc.is_visible(timeout=300):
                    continue
                png = await loc.screenshot()
                answer = await self.provider.solve_image(base64.b64encode(png).decode())
                if not answer:
                    continue
                inp = page.locator("input[type='text'], input.captcha-input").first
                if await inp.count():
                    await inp.fill(answer)
                    btn = page.locator("button:has-text('确定'), button:has-text('提交')").first
                    if await btn.count():
                        await btn.click()
                    await page.wait_for_timeout(1000)
                    if await self.detect(page) is None:
                        return True
            except Exception as exc:  # noqa: BLE001
                self.log.debug("maoyan provider image: %s", exc)
        return False
