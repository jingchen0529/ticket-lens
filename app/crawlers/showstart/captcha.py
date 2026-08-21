"""秀动纯 HTTP 数据源的空验证码策略。"""

from __future__ import annotations

from playwright.async_api import Page

from app.browser.captcha.base import CaptchaChallenge, CaptchaSolveResult, CaptchaSolver


class ShowstartCaptchaSolver(CaptchaSolver):
    """秀动不使用浏览器或验证码。"""

    platform = "showstart"

    async def detect(self, page: Page) -> CaptchaChallenge | None:
        return None

    async def solve_auto(
        self,
        page: Page,
        challenge: CaptchaChallenge,
    ) -> CaptchaSolveResult:
        return CaptchaSolveResult(
            ok=True,
            method="skipped",
            message="no captcha (pure HTTP source)",
        )
