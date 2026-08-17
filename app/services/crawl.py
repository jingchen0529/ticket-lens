"""采集编排：按源启浏览器 → 平台策略采集 → 统一规范化 → 落盘。

每个源使用独立 BrowserSession，以便加载该平台 cookie / 验证码状态。
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime

from app.browser.session import browser_session
from app.core.config import AppConfig
from app.crawlers.registry import get_crawler
from app.models import CrawlJob, CrawlResult, RawShowItem, SourcePlatform
from app.pipeline.normalize import normalize_items
from app.repositories.storage.factory import create_storage
from app.utils.show_visibility import summarize_ledger_visibility

logger = logging.getLogger(__name__)


async def run_crawl(job: CrawlJob, config: AppConfig) -> CrawlResult:
    started = datetime.utcnow()
    result = CrawlResult(job=job, started_at=started)
    raw_all: list[RawShowItem] = []
    # 详情开始前保存的列表快照。最终 raw 快照也保留这些项目；已经完成的
    # 详情会按同键覆盖列表版本，但未完成项目不会因任务中断而消失。
    raw_checkpoint: dict[tuple[str, str], RawShowItem] = {}
    completed_checkpoint: dict[tuple[str, str], RawShowItem] = {}

    def raw_key(item: RawShowItem) -> tuple[str, str]:
        identity = item.source_id or item.url or f"__unkeyed__:{id(item)}"
        return (item.source.value, identity)

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
                try:
                    crawler = get_crawler(src, session, run_config)
                    # 任务级开关覆盖配置（桌面端可关详情加速）
                    if hasattr(job, "enrich_detail"):
                        run_config.crawl.enrich_detail = bool(job.enrich_detail)

                    async def persist_discovered(items: list[RawShowItem]) -> None:
                        """详情开始前持久化列表；异常退出后可从 base 整项补跑。"""
                        for discovered in items:
                            raw_checkpoint[raw_key(discovered)] = discovered
                        storage.save_raw(list(raw_checkpoint.values()))
                        logger.info(
                            "source %s list checkpoint persisted projects=%s",
                            src.value,
                            len(items),
                        )

                    async def persist_item(item: RawShowItem) -> None:
                        # 详情一返回就按场次规范化并替换该项目的库内记录。前端轮询
                        # 数据库时能立即看到拆分结果，不必等整个城市/全国任务结束。
                        item_shows = normalize_items([item], config.pipeline)
                        item_key = raw_key(item)
                        raw_checkpoint[item_key] = item
                        completed_checkpoint[item_key] = item
                        # JSON 后端是整文件快照，必须把待处理列表一起保留；SQLite
                        # 是逐项目 upsert，单项覆盖即可，避免每场 O(n²) 写盘。
                        raw_snapshot = (
                            list(raw_checkpoint.values())
                            if (config.storage.backend or "").lower() == "json"
                            and raw_checkpoint
                            else [item]
                        )
                        storage.save_raw(raw_snapshot)
                        show_snapshot = (
                            normalize_items(
                                list(completed_checkpoint.values()),
                                config.pipeline,
                            )
                            if (config.storage.backend or "").lower() == "json"
                            else item_shows
                        )
                        storage.save_shows(show_snapshot)
                        logger.info(
                            "source %s item=%s persisted sessions=%s rows=%s",
                            src.value,
                            item.source_id,
                            len(item.sessions_raw),
                            len(item_shows),
                        )

                    crawl_kwargs = {
                        "cities": job.cities,
                        "keywords": job.keywords,
                        "max_pages": job.max_pages,
                        "category": job.category,
                        "on_item": persist_item,
                    }
                    crawl_params = inspect.signature(crawler.crawl).parameters.values()
                    if any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        or parameter.name == "on_items_discovered"
                        for parameter in crawl_params
                    ):
                        crawl_kwargs["on_items_discovered"] = persist_discovered
                    items = await crawler.crawl(**crawl_kwargs)
                    raw_all.extend(items)
                    result.by_source[src.value] = len(items)
                    await session.save_platform_cookies(src.value)
                    logger.info("source %s raw=%s", src.value, len(items))
                except Exception as exc:  # noqa: BLE001
                    # Log while the browser is still alive. The following context cleanup
                    # is then clearly an effect of the failure, not its apparent cause.
                    msg = f"{src.value}: {exc}"
                    logger.exception("crawler failed: %s", msg)
                    result.errors.append(msg)
        except Exception as exc:  # noqa: BLE001
            # 走到这里 = 浏览器会话建立失败（采集环境起不来）：把真实异常
            # 摘要写进任务日志，完整堆栈经 logger.exception 落盘 server.log。
            brief = (str(exc).strip().splitlines() or [""])[0] or type(exc).__name__
            logger.error("browser session startup failed: %s", brief)
            msg = f"{src.value}: {exc}"
            logger.exception("crawler failed: %s", msg)
            result.errors.append(msg)

    # crawler 在某个后续项目触发熔断时不会正常 return；此前通过 on_item
    # 流式落库的完整项目仍应进入本次结果和最终 JSON 快照。
    merged_completed = dict(completed_checkpoint)
    for item in raw_all:
        merged_completed[raw_key(item)] = item
    raw_all = list(merged_completed.values())

    for src in enabled_sources:
        if src.value not in result.by_source:
            completed_count = sum(
                1 for item in raw_all if item.source == src
            )
            if completed_count:
                result.by_source[src.value] = completed_count

    shows = normalize_items(raw_all, config.pipeline)
    result.raw_count = len(raw_all)
    result.show_count = len(shows)
    (
        result.ledger_visible_count,
        result.ledger_hidden_count,
        result.ledger_hidden_by_category,
    ) = summarize_ledger_visibility(show.category for show in shows)
    result.finished_at = datetime.utcnow()

    final_raw = dict(raw_checkpoint)
    for item in raw_all:
        final_raw[raw_key(item)] = item
    storage.save_raw(list(final_raw.values()) if final_raw else raw_all)
    storage.save_shows(shows)
    storage.save_result(result)

    logger.info(
        "crawl finished raw=%s shows=%s ledger_visible=%s ledger_hidden=%s "
        "out=%s errors=%s",
        result.raw_count,
        result.show_count,
        result.ledger_visible_count,
        result.ledger_hidden_count,
        result.output_path,
        len(result.errors),
    )
    return result
