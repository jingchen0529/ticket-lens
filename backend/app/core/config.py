"""配置加载。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrowserConfig(BaseModel):
    headless: bool = True
    slow_mo_ms: int = 0
    timeout_ms: int = 30_000
    navigation_timeout_ms: int = 45_000
    user_agent: str = ""
    proxy: str = ""


class CaptchaConfig(BaseModel):
    """全局验证码配置；各平台可在 sources.*.captcha 覆盖。"""

    # 是否自动过验证（本地水果滑块 / NC 滑块）
    auto: bool = True
    # 自动失败后是否允许有头人工兜底
    allow_manual: bool = True
    manual_wait_seconds: int = 120
    # local_slider（默认，纯本地）|
    # bingtop（冰拓，国内推荐）| chaojiying（超级鹰）| yunma（云码）|
    # capsolver / twocaptcha（海外）| none
    provider: str = "local_slider"
    # 通用 token/key；冰拓可填用户名，超级鹰可填 softid，云码填 token
    api_key: str = ""
    # 国内平台账号（冰拓 / 超级鹰）
    username: str = ""
    password: str = ""
    # 超级鹰 softid（也可写在 api_key）
    soft_id: str = ""
    # 打码类型覆盖（冰拓水果默认 1358 主图+标题；可改 1357/1359）
    fruit_captcha_type: int | None = None
    # 策略：local_first | provider_first | local_only | provider_only
    # local_first：先本地打分，失败再打码（默认，省钱）
    # provider_first：先打码，失败回退本地
    fruit_strategy: str = "local_first"
    # 水果滑块扫描步长（像素），越小越准越慢
    fruit_scan_step: float = 4.0
    # 单次自动求解最多提交多少道新题，限制付费识别预算
    fruit_max_rounds: int = Field(default=1, ge=1, le=5)
    # 通过验证后保存 cookie，下次少弹验证码
    persist_cookies: bool = True
    cookie_dir: str = "data/cookies"


class PlatformCaptchaOverride(BaseModel):
    """单平台覆盖全局 captcha 配置。"""

    auto: bool | None = None
    allow_manual: bool | None = None
    provider: str | None = None
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    soft_id: str | None = None
    fruit_captcha_type: int | None = None
    fruit_strategy: str | None = None
    fruit_max_rounds: int | None = Field(default=None, ge=1, le=5)


class CrawlConfig(BaseModel):
    cities: list[str] = Field(default_factory=lambda: ["北京", "上海"])
    keywords: list[str] = Field(default_factory=list)
    max_pages: int = 3
    request_delay_seconds: float = 1.5
    scroll_pause_ms: int = 800
    # 列表后是否补全详情（场次/票档/场馆）
    enrich_detail: bool = True
    # 每条详情请求间隔（秒），略大更稳
    detail_delay_seconds: float = 0.35
    # 每个项目最多按日历拉多少个日期（防止极端长档期）
    detail_date_limit: int = 40


class SourceEndpointConfig(BaseModel):
    enabled: bool = True
    base_url: str = ""
    search_url: str = ""
    list_url: str = ""
    captcha: PlatformCaptchaOverride = Field(default_factory=PlatformCaptchaOverride)


class SourcesConfig(BaseModel):
    damai: SourceEndpointConfig = Field(
        default_factory=lambda: SourceEndpointConfig(
            base_url="https://www.damai.cn",
            search_url="https://search.damai.cn/search.htm",
        )
    )
    maoyan: SourceEndpointConfig = Field(
        default_factory=lambda: SourceEndpointConfig(
            base_url="https://show.maoyan.com",
            list_url="https://show.maoyan.com/qqw#/list",
        )
    )


class StorageConfig(BaseModel):
    backend: str = "json"  # json | sqlite
    output_dir: str = "data"
    run_subdir: bool = True
    # 本地固定 SQLite 库路径（供前端/API 持久查询）。
    # backend=sqlite 且 run_subdir=false 时，直接写到这个库并 upsert 累积。
    db_path: str = "data/daxi.sqlite3"


class PipelineConfig(BaseModel):
    drop_invalid: bool = True
    dedupe: bool = True


class AppConfig(BaseModel):
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    captcha: CaptchaConfig = Field(default_factory=CaptchaConfig)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)

    def captcha_for(self, platform: str) -> CaptchaConfig:
        """合并全局 captcha + 平台覆盖。"""
        base = self.captcha.model_copy()
        src = getattr(self.sources, platform, None)
        if src is None or not getattr(src, "captcha", None):
            return base
        ov: PlatformCaptchaOverride = src.captcha
        data = base.model_dump()
        for key in (
            "auto",
            "allow_manual",
            "provider",
            "api_key",
            "username",
            "password",
            "soft_id",
            "fruit_captcha_type",
            "fruit_strategy",
            "fruit_max_rounds",
        ):
            val = getattr(ov, key, None)
            if val is not None and val != "":
                data[key] = val
        return CaptchaConfig.model_validate(data)


class EnvSettings(BaseSettings):
    """环境变量覆盖（可选）。"""

    model_config = SettingsConfigDict(env_prefix="DAXI_", env_nested_delimiter="__")

    headless: bool | None = None
    proxy: str | None = None
    output_dir: str | None = None
    captcha_api_key: str | None = None
    captcha_provider: str | None = None
    captcha_auto: bool | None = None
    captcha_username: str | None = None
    captcha_password: str | None = None
    captcha_soft_id: str | None = None
    captcha_fruit_strategy: str | None = None
    captcha_fruit_max_rounds: int | None = None


def load_config(path: str | Path | None = None) -> AppConfig:
    from app.core import paths

    cfg_path = Path(path) if path else paths.config_path()
    data: dict[str, Any] = {}
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    app = AppConfig.model_validate(data)

    # 打包后 CWD 不可控：把相对的 DB / cookie 路径落到统一用户数据目录。
    # 绝对路径（客户显式配置）保持不动。
    db_p = Path(app.storage.db_path)
    if not db_p.is_absolute():
        app.storage.db_path = str(paths.db_path())
    cookie_p = Path(app.captcha.cookie_dir)
    if not cookie_p.is_absolute():
        app.captcha.cookie_dir = str(paths.cookie_dir())

    env = EnvSettings()
    if env.headless is not None:
        app.browser.headless = env.headless
    if env.proxy:
        app.browser.proxy = env.proxy
    if env.output_dir:
        app.storage.output_dir = env.output_dir
    if env.captcha_api_key:
        app.captcha.api_key = env.captcha_api_key
    if env.captcha_provider:
        app.captcha.provider = env.captcha_provider
    if env.captcha_auto is not None:
        app.captcha.auto = env.captcha_auto
    if env.captcha_username:
        app.captcha.username = env.captcha_username
    if env.captcha_password:
        app.captcha.password = env.captcha_password
    if env.captcha_soft_id:
        app.captcha.soft_id = env.captcha_soft_id
    if env.captcha_fruit_strategy:
        app.captcha.fruit_strategy = env.captcha_fruit_strategy
    if env.captcha_fruit_max_rounds is not None:
        app.captcha.fruit_max_rounds = env.captcha_fruit_max_rounds

    return app
