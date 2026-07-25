"""采集编排：按源启浏览器 → 平台策略采集 → 统一规范化 → 落盘。

每个源使用独立 BrowserSession，以便加载该平台 cookie / 验证码状态。
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.browser.session import browser_session
from app.core.config import AppConfig
from app.crawlers.registry import get_crawler
from app.models import CrawlJob, CrawlResult, RawShowItem, SourcePlatform
from app.pipeline.normalize import normalize_items
from app.repositories.storage.factory import create_storage

logger = logging.getLogger(__name__)


async def run_crawl(job: CrawlJob, config: AppConfig) -> CrawlResult:
    started = datetime.utcnow()
    result = CrawlResult(job=job, started_at=started)
    raw_all: list[RawShowItem] = []

    storage = create_storage(config.storage)
    result.output_path = str(storage.root)

    enabled_sources: list[SourcePlatform] = []
    for src in job.sources:
        if src == SourcePlatform.DAMAI and not config.sources.damai.enabled:
            logger.info("skip damai (disabled in config)")
            continue
        if src == SourcePlatform.MAOYAN and not config.sources.maoyan.enabled:
            logger.info("skip maoyan (disabled in config)")
            continue
        enabled_sources.append(src)

    for src in enabled_sources:
        # 平台专属 captcha 配置注入到 session
        platform_captcha = config.captcha_for(src.value)
        # 临时把合并后的 captcha 挂到 config 上，供 solver 读取
        run_config = config.model_copy(deep=True)
        run_config.captcha = platform_captcha

        try:
            async with browser_session(
                run_config.browser,
                run_config.captcha,
                platform=src.value,
            ) as session:
                crawler = get_crawler(src, session, run_config)
                # 任务级开关覆盖配置（桌面端可关详情加速）
                if hasattr(job, "enrich_detail"):
                    run_config.crawl.enrich_detail = bool(job.enrich_detail)
                items = await crawler.crawl(
                    cities=job.cities,
                    keywords=job.keywords,
                    max_pages=job.max_pages,
                )
                raw_all.extend(items)
                result.by_source[src.value] = len(items)
                await session.save_platform_cookies(src.value)
                logger.info("source %s raw=%s", src.value, len(items))
        except Exception as exc:  # noqa: BLE001
            msg = f"{src.value}: {exc}"
            logger.exception("crawler failed: %s", msg)
            result.errors.append(msg)

    shows = normalize_items(raw_all, config.pipeline)
    result.raw_count = len(raw_all)
    result.show_count = len(shows)
    result.finished_at = datetime.utcnow()

    storage.save_raw(raw_all)
    storage.save_shows(shows)
    storage.save_result(result)

    logger.info(
        "crawl finished raw=%s shows=%s out=%s errors=%s",
        result.raw_count,
        result.show_count,
        result.output_path,
        len(result.errors),
    )
    return result
