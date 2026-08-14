"""Playwright 浏览器会话封装。

启动 / 反检测 / cookie 复用；验证码交给各平台 CaptchaSolver 自动处理。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.browser.captcha.base import CaptchaSolver
from app.browser.captcha.cookies import cookie_path, load_storage_state, save_storage_state
from app.core.config import BrowserConfig, CaptchaConfig

logger = logging.getLogger(__name__)


def _storage_allowed_domains(platform: str | None) -> tuple[str, ...] | None:
    if str(platform or "").strip().lower() == "damai":
        return ("damai.cn",)
    return None


class BrowserSession:
    """管理 Playwright 生命周期。"""

    def __init__(
        self,
        config: BrowserConfig,
        captcha_config: CaptchaConfig | None = None,
    ) -> None:
        self.config = config
        self.captcha_config = captcha_config or CaptchaConfig()
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._storage_loaded_for: set[str] = set()

    async def start(self, *, platform: str | None = None) -> None:
        # 打包后把 PLAYWRIGHT_BROWSERS_PATH 指向随包 Chromium（源码运行无副作用）
        from app.core.paths import setup_browser_env

        setup_browser_env()
        self._pw = await async_playwright().start()
        launch_kwargs: dict = {
            "headless": self.config.headless,
            "slow_mo": self.config.slow_mo_ms,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        }
        if self.config.proxy:
            launch_kwargs["proxy"] = {"server": self.config.proxy}

        self._browser = await self._pw.chromium.launch(**launch_kwargs)

        context_kwargs: dict = {
            "viewport": {"width": 1440, "height": 900},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
        }
        if self.config.user_agent:
            context_kwargs["user_agent"] = self.config.user_agent

        # 按平台加载已通过验证的 cookie
        if platform and self.captcha_config.persist_cookies:
            path = cookie_path(self.captcha_config.cookie_dir, platform)
            state = await load_storage_state(
                path,
                allowed_domains=_storage_allowed_domains(platform),
            )
            if state:
                context_kwargs["storage_state"] = state
                self._storage_loaded_for.add(platform)
                logger.info("loaded cookies for %s from %s", platform, path)

        self._context = await self._browser.new_context(**context_kwargs)
        self._context.set_default_timeout(self.config.timeout_ms)
        self._context.set_default_navigation_timeout(self.config.navigation_timeout_ms)

        # Provider-only solving does not need the SecCaptcha updatePos hook.
        # Avoid mutating page globals before the official fingerprint is built.
        fruit_strategy = str(
            getattr(self.captcha_config, "fruit_strategy", "provider_first") or "provider_first"
        ).lower()
        if fruit_strategy != "provider_only":
            await self._context.add_init_script(
                """
            // 挂钩阿里 SecCaptcha WASM：仅供本地 updatePos 估距
            (function () {
              try {
                let _pos = null, _info = null;
                const descPos = Object.getOwnPropertyDescriptor(Document.prototype, '__update_pos')
                  || Object.getOwnPropertyDescriptor(document, '__update_pos');
                Object.defineProperty(document, '__update_pos', {
                  configurable: true,
                  enumerable: true,
                  get() { return _pos; },
                  set(v) {
                    _pos = v;
                    try { window.__daxiUpdatePos = v; } catch (e) {}
                  }
                });
                Object.defineProperty(document, '__update_info', {
                  configurable: true,
                  enumerable: true,
                  get() { return _info; },
                  set(v) {
                    _info = v;
                    try { window.__daxiUpdateInfo = v; } catch (e) {}
                  }
                });
                // 若页面已用 defineProperty 写过，上面 set 仍可接到后续赋值
                if (descPos && typeof descPos.value === 'function') {
                  _pos = descPos.value;
                  window.__daxiUpdatePos = descPos.value;
                }
              } catch (e) {}
            })();
            """
            )
        logger.info(
            "browser started headless=%s proxy=%s",
            self.config.headless,
            bool(self.config.proxy),
        )

    async def stop(self) -> None:
        if self._context:
            try:
                await self._context.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser context cleanup failed: %s", exc)
            self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser cleanup failed: %s", exc)
            self._browser = None
        if self._pw:
            try:
                await self._pw.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("playwright cleanup failed: %s", exc)
            self._pw = None
        logger.info("browser cleanup complete")

    async def new_page(self) -> Page:
        if not self._context:
            raise RuntimeError("BrowserSession not started")
        return await self._context.new_page()

    async def goto(
        self,
        page: Page,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        captcha: CaptchaSolver | None = None,
    ) -> None:
        logger.debug("goto %s", url)
        await page.goto(url, wait_until=wait_until)
        if captcha is not None:
            result = await captcha.ensure_cleared(page)
            if not result.ok:
                raise RuntimeError(
                    f"[{captcha.platform}] captcha not cleared via {result.method}: {result.message}"
                )
            # 通过后持久化 cookie，减少下次验证
            if (
                result.method not in ("skipped",)
                and self.captcha_config.persist_cookies
                and self._context is not None
            ):
                path = cookie_path(self.captcha_config.cookie_dir, captcha.platform)
                await save_storage_state(
                    self._context,
                    path,
                    allowed_domains=_storage_allowed_domains(captcha.platform),
                )

    async def save_platform_cookies(self, platform: str) -> None:
        if self._context is None:
            return
        if not self.captcha_config.persist_cookies:
            return
        path = cookie_path(self.captcha_config.cookie_dir, platform)
        await save_storage_state(
            self._context,
            path,
            allowed_domains=_storage_allowed_domains(platform),
        )

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        p = await self.new_page()
        try:
            yield p
        finally:
            try:
                await p.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("page cleanup failed: %s", exc)


@asynccontextmanager
async def browser_session(
    config: BrowserConfig,
    captcha_config: CaptchaConfig | None = None,
    *,
    platform: str | None = None,
) -> AsyncIterator[BrowserSession]:
    session = BrowserSession(config, captcha_config)
    await session.start(platform=platform)
    try:
        yield session
    finally:
        await session.stop()
