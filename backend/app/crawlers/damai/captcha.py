"""大麦验证码策略（阿里 x5 / 水果滑块 captchacapslidev2）。

自动过验证链路：
1. 水果滑块 → 本地打分 / 国内打码（冰拓/超级鹰/云码）+ 拟人拖动
2. 传统 NC 滑块 → 本地轨迹
3. 失败 → 有头人工兜底

国内打码配置示例（configs/default.yaml 或环境变量）：
  captcha:
    provider: bingtop
    username: your_user
    password: your_pass
    fruit_strategy: provider_first  # local_first | provider_first | local_only | provider_only
    fruit_captcha_type: 1359      # 冰拓：1359 上下完整 / 1357 主图+题干
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from app.browser.captcha.base import (
    CaptchaChallenge,
    CaptchaKind,
    CaptchaSolveResult,
    CaptchaSolver,
)
from app.browser.captcha.providers import CaptchaProvider, create_provider
from app.browser.captcha.slider import find_first_visible, try_slider_solve
from app.crawlers.damai.fruit_slider import (
    detect_fruit_slider,
    solve_fruit_slider,
    wait_fruit_slider,
)

DAMAI_URL_MARKERS = (
    "_____tmd_____",
    "/punish",
    "x5secdata",
    "captcha.damai",
    "baxia.damai",
    "captchacapslide",
    "capslide",
)

DAMAI_TEXT_MARKERS = (
    "punish",
    "验证码",
    "滑动验证",
    "安全验证",
    "请按住滑块",
    "拖动滑块",
    "拖动滑块出现完整",
    "后就松开",
    "亲，请拖动下方滑块",
    "unusual traffic",
    "access denied",
)

DAMAI_KNOB_SELECTORS = [
    "#nc_1_n1z",
    ".nc_iconfont.btn_slide",
    ".btn_slide",
    ".slidetounlock",
    ".nc_scale span",
    ".baxia-dialog-content .btn_slide",
    "[class*='slide-btn']",
    ".slide-btn",
    ".handler",
    ".slider-btn",
]

DAMAI_TRACK_SELECTORS = [
    "#nc_1_n1t",
    ".nc_scale",
    ".slidetounlock",
    ".baxia-dialog-content .nc_scale",
    "[class*='slider-track']",
    ".slider-track",
]


class DamaiCaptchaSolver(CaptchaSolver):
    platform = "damai"
    # 水果滑块内部已有带预算的 round，外层不重复整套付费流程。
    max_auto_attempts = 1

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        captcha_cfg = self._captcha_cfg()
        # 优先用平台合并后的 captcha_for("damai")
        if hasattr(config, "captcha_for"):
            try:
                captcha_cfg = config.captcha_for("damai")
            except Exception:  # noqa: BLE001
                pass
        self.scan_step = float(getattr(captcha_cfg, "fruit_scan_step", 5) or 5)
        self.fruit_max_rounds = max(
            1,
            min(5, int(getattr(captcha_cfg, "fruit_max_rounds", 3) or 3)),
        )
        self.fruit_strategy = str(
            getattr(captcha_cfg, "fruit_strategy", "provider_first") or "provider_first"
        )
        self.provider: CaptchaProvider | None = create_provider(
            getattr(captcha_cfg, "provider", "local_slider") or "local_slider",
            getattr(captcha_cfg, "api_key", "") or "",
            username=getattr(captcha_cfg, "username", "") or "",
            password=getattr(captcha_cfg, "password", "") or "",
            soft_id=getattr(captcha_cfg, "soft_id", "") or "",
            fruit_type=getattr(captcha_cfg, "fruit_captcha_type", None),
        )
        if self.provider:
            self.log.info(
                "damai captcha provider=%s strategy=%s",
                self.provider.name,
                self.fruit_strategy,
            )

    async def detect(self, page: Page) -> CaptchaChallenge | None:
        url = page.url.lower()
        # fruit 标志看完整 URL（x5secdata 里常带 capslidev2），不要只看命中的 marker 子串
        url_fruit = any(k in url for k in ("capslide", "captchacapslide", "scratch-captcha"))
        for m in DAMAI_URL_MARKERS:
            if m in url:
                fruit = url_fruit or ("capslide" in m or "captchacapslide" in m)
                kind = (
                    CaptchaKind.SLIDER
                    if fruit or "captcha" in m or "capslide" in url
                    else CaptchaKind.PUNISH
                )
                return CaptchaChallenge(
                    kind=kind,
                    reason=f"url:{m}",
                    meta={"fruit": fruit},
                )

        if await detect_fruit_slider(page):
            return CaptchaChallenge(
                kind=CaptchaKind.SLIDER,
                reason="fruit_slider_ui",
                meta={"fruit": True},
            )

        for frame in page.frames:
            if frame == page.main_frame:
                continue
            furl = (frame.url or "").lower()
            if any(m in furl for m in ("punish", "captcha", "baxia", "x5sec", "tmd", "capslide")):
                return CaptchaChallenge(
                    kind=CaptchaKind.IFRAME,
                    reason=f"frame:{furl[:80]}",
                    meta={"frame_url": frame.url, "fruit": "capslide" in furl},
                )

        knob = await find_first_visible(page, DAMAI_KNOB_SELECTORS)
        if knob is not None:
            return CaptchaChallenge(kind=CaptchaKind.SLIDER, reason="nc_knob_visible")

        try:
            content = (await page.content()).lower()
        except Exception:  # noqa: BLE001
            content = ""

        for m in DAMAI_TEXT_MARKERS:
            if m.lower() in content:
                fruit = "拖动滑块出现完整" in content or "后就松开" in content
                return CaptchaChallenge(
                    kind=CaptchaKind.SLIDER if ("滑" in m or fruit) else CaptchaKind.UNKNOWN,
                    reason=f"text:{m}",
                    meta={"fruit": fruit},
                )

        if "bxuuid" in content and "captcha" in content:
            return CaptchaChallenge(kind=CaptchaKind.PUNISH, reason="bx_captcha_config")

        return None

    async def solve_auto(
        self,
        page: Page,
        challenge: CaptchaChallenge,
        *,
        payload_hint: Any = None,
    ) -> CaptchaSolveResult:
        async def cleared() -> bool:
            return await self.detect(page) is None

        # 等 UI 就绪（punish 页异步加载 scratch-captcha）
        fruitish = bool(challenge.meta.get("fruit")) or challenge.kind in (
            CaptchaKind.PUNISH,
            CaptchaKind.IFRAME,
            CaptchaKind.SLIDER,
        )
        if fruitish:
            await wait_fruit_slider(page, timeout_s=8.0)

        # 1) 水果滑块（本地打分 + 可选国内打码）
        # payload_hint：外层提前截到的 newslidecaptcha 双图；不传会 miss 已消费的 response
        hint = payload_hint if payload_hint is not None else getattr(self, "_payload_hint", None)
        if await detect_fruit_slider(page) or bool(challenge.meta.get("fruit")):
            method_hint = (
                f"fruit_slider:{self.fruit_strategy}"
                + (f"+{self.provider.name}" if self.provider else "+local")
            )
            self.log.info(
                "damai: fruit slider captchacapslidev2 via %s payload_hint=%s",
                method_hint,
                bool(hint and getattr(hint, "image_data", None)),
            )
            try:
                ok = await solve_fruit_slider(
                    page,
                    step=self.scan_step,
                    success_check=cleared,
                    max_rounds=self.fruit_max_rounds,
                    wait_timeout_s=6.0,
                    provider=self.provider,
                    strategy=self.fruit_strategy,
                    payload_hint=hint,
                )
                # 用过即丢，防止 ensure_cleared 第二轮答旧题
                self._payload_hint = None
                if ok:
                    return CaptchaSolveResult(
                        ok=True,
                        method=method_hint,
                        message="capslidev2 solved",
                    )
            except Exception as exc:  # noqa: BLE001
                self._payload_hint = None
                self.log.warning("fruit slider error: %s", exc)
            return CaptchaSolveResult(
                ok=False,
                method=method_hint,
                message="fruit slider rejected or not cleared",
            )

        # 2) 仅非水果题走传统 NC，避免水果失败后再次乱拖。
        ok = await try_slider_solve(
            page,
            knob_selectors=DAMAI_KNOB_SELECTORS,
            track_selectors=DAMAI_TRACK_SELECTORS,
            success_check=cleared,
            max_attempts=3,
        )
        if not ok:
            ok = await self._drag_in_frames(page, cleared)
        if ok:
            return CaptchaSolveResult(ok=True, method="local_slider", message="nc slider ok")

        return CaptchaSolveResult(
            ok=False,
            method="fruit_slider_local",
            message="damai local captcha solve failed",
        )

    async def _confirm_cleared(self, page: Page, result: CaptchaSolveResult) -> bool:
        if result.method.startswith("fruit_slider"):
            return not await detect_fruit_slider(page)
        return await super()._confirm_cleared(page, result)

    async def _drag_in_frames(self, page: Page, cleared) -> bool:
        from app.browser.captcha.human_track import distance_candidates, generate_slider_track

        for frame in page.frames:
            for sel in DAMAI_KNOB_SELECTORS:
                try:
                    loc = frame.locator(sel).first
                    if await loc.count() == 0 or not await loc.is_visible(timeout=300):
                        continue
                    box = await loc.bounding_box()
                    if not box:
                        continue
                    for dist in distance_candidates(260.0)[:3]:
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
                        await page.wait_for_timeout(600)
                        if await cleared():
                            return True
                        box = await loc.bounding_box() or box
                except Exception:  # noqa: BLE001
                    continue
        return False
