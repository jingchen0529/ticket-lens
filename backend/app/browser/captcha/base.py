"""验证码策略抽象。

每个平台（大麦 / 猫眼）实现自己的 CaptchaSolver：
检测 → 自动求解（滑块 / 打码平台）→ 人工兜底。
"""

from __future__ import annotations

import abc
import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)


class CaptchaKind(str, Enum):
    NONE = "none"
    SLIDER = "slider"  # 滑动拼图
    CLICK = "click"  # 点选
    IMAGE = "image"  # 图文/算式
    IFRAME = "iframe"  # 嵌套风控页
    PUNISH = "punish"  # 惩罚页（阿里 x5 等）
    UNKNOWN = "unknown"


@dataclass
class CaptchaChallenge:
    kind: CaptchaKind
    reason: str = ""
    selectors: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaptchaSolveResult:
    ok: bool
    method: str = ""  # local_slider | provider | manual | skipped
    message: str = ""
    attempts: int = 0


class CaptchaSolver(abc.ABC):
    """平台级验证码策略。"""

    platform: str
    max_auto_attempts: int = 3

    def __init__(self, config: Any) -> None:
        """config: AppConfig 或 CaptchaConfig。"""
        self.config = config
        self.log = logging.getLogger(f"captcha.{self.platform}")

    @abc.abstractmethod
    async def detect(self, page: Page) -> CaptchaChallenge | None:
        """页面上是否存在本平台验证码/风控。"""

    @abc.abstractmethod
    async def solve_auto(self, page: Page, challenge: CaptchaChallenge) -> CaptchaSolveResult:
        """自动过验证（滑块轨迹 / 打码 API 等）。"""

    async def solve_manual(self, page: Page, challenge: CaptchaChallenge) -> CaptchaSolveResult:
        """有头模式下等待人工完成。"""
        captcha_cfg = self._captcha_cfg()
        wait_s = getattr(captcha_cfg, "manual_wait_seconds", 120)
        if getattr(self._browser_cfg(), "headless", True):
            return CaptchaSolveResult(
                ok=False,
                method="manual",
                message="需要人工验证但当前为 headless，请使用 --headed",
            )

        self.log.warning(
            "[%s] 请在浏览器中手动完成验证（%s），最多等待 %ss …",
            self.platform,
            challenge.kind.value,
            wait_s,
        )
        deadline = asyncio.get_event_loop().time() + wait_s
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1.5)
            if await self.detect(page) is None:
                return CaptchaSolveResult(ok=True, method="manual", message="manual cleared")
        return CaptchaSolveResult(ok=False, method="manual", message="manual wait timeout")

    async def _confirm_cleared(self, page: Page, result: CaptchaSolveResult) -> bool:
        """二次确认自动求解结果；平台可按自己的可见 UI 语义覆盖。"""
        return await self.detect(page) is None

    async def ensure_cleared(
        self,
        page: Page,
        *,
        payload_hint: Any = None,
    ) -> CaptchaSolveResult:
        """检测并自动过验证；失败时按配置人工兜底。

        payload_hint: 可选，外层已截获的 newslidecaptcha 双图（CaptchaPayload）。
        出题响应只会出现一次，solver 内再挂 listener 会 miss，必须把 early payload 传进来。
        """
        captcha_cfg = self._captcha_cfg()
        # 供 DamaiCaptchaSolver.solve_auto 读取；显式传 None 时清掉旧 hint，避免答上一题
        if payload_hint is not None:
            self._payload_hint = payload_hint
        else:
            self._payload_hint = None
        challenge = await self.detect(page)
        if challenge is None:
            return CaptchaSolveResult(ok=True, method="skipped", message="no captcha")

        self.log.warning(
            "[%s] captcha detected kind=%s reason=%s url=%s",
            self.platform,
            challenge.kind.value,
            challenge.reason,
            page.url,
        )

        if not getattr(captcha_cfg, "auto", True):
            if getattr(captcha_cfg, "allow_manual", True):
                return await self.solve_manual(page, challenge)
            return CaptchaSolveResult(ok=False, method="disabled", message="auto captcha disabled")

        last = CaptchaSolveResult(ok=False, method="auto", message="no attempt")
        # 仅第 1 次尝试用外层 early payload；后续必须等新 newslidecaptcha
        attempt_hint = payload_hint
        for attempt in range(1, self.max_auto_attempts + 1):
            self.log.info("[%s] auto solve attempt %s/%s", self.platform, attempt, self.max_auto_attempts)
            # 只有大麦需要 early payload；不要捕获执行体 TypeError 后重复整套求解。
            if self.platform == "damai":
                last = await self.solve_auto(  # type: ignore[call-arg]
                    page, challenge, payload_hint=attempt_hint
                )
            else:
                last = await self.solve_auto(page, challenge)
            last.attempts = attempt
            attempt_hint = None  # 用过即丢
            self._payload_hint = None
            if last.ok:
                # 再确认一次
                await page.wait_for_timeout(800)
                if await self._confirm_cleared(page, last):
                    self.log.info("[%s] captcha cleared via %s", self.platform, last.method)
                    return last
                last = CaptchaSolveResult(
                    ok=False,
                    method=last.method,
                    message="solver reported ok but captcha still present",
                    attempts=attempt,
                )
            await page.wait_for_timeout(500)
            challenge = await self.detect(page) or challenge

        if getattr(captcha_cfg, "allow_manual", True):
            self.log.warning("[%s] auto failed, fallback manual: %s", self.platform, last.message)
            return await self.solve_manual(page, challenge)

        return last

    def _captcha_cfg(self) -> Any:
        # AppConfig.captcha 或 platform 覆盖
        if hasattr(self.config, "captcha"):
            return self.config.captcha
        return self.config

    def _browser_cfg(self) -> Any:
        if hasattr(self.config, "browser"):
            return self.config.browser
        return self.config
