#!/usr/bin/env python3
"""补跑详情富化：为已入库但未富化的演出补全场次/票档/地址信息。"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
from pathlib import Path

import orjson

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.browser.session import browser_session
from app.core import paths
from app.core.config import load_config
from app.crawlers.damai.detail import enrich_items_detail
from app.models import RawShowItem
from app.pipeline.normalize import normalize_items
from app.repositories.storage.sqlite_store import SqliteStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _item_key(item: RawShowItem) -> str:
    return str(item.source_id or item.url or "")


def _load_checkpoint_items(checkpoint_path: Path) -> list[RawShowItem]:
    if not checkpoint_path.exists():
        return []
    try:
        payload = orjson.loads(checkpoint_path.read_bytes())
        pending = payload.get("pending_items") if isinstance(payload, dict) else []
        if not isinstance(pending, list):
            return []
        return [RawShowItem.model_validate(item) for item in pending]
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取详情断点失败 path=%s reason=%s", checkpoint_path, exc)
        return []


def _load_incomplete_raw_items(db_path: Path, *, limit: int = 1000) -> list[RawShowItem]:
    """读取 raw_items；移动区间价和仅列表项目都重新尝试 PC 详情。"""
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            """
            SELECT payload
            FROM raw_items
            WHERE source = 'damai'
              AND (
                    json_extract(payload, '$.raw_payload.detail.detail_complete') IS NOT 1
                 OR json_extract(payload, '$.raw_payload.detail.detail_source')
                    IS NOT 'damai_pc_subpage'
              )
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    out: list[RawShowItem] = []
    for (payload_json,) in rows:
        try:
            out.append(RawShowItem.model_validate(orjson.loads(payload_json)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("反序列化 raw_items 失败: %s", exc)
    return out


def load_pending_items(
    db_path: Path,
    checkpoint_path: Path,
    *,
    limit: int = 1000,
) -> tuple[list[RawShowItem], set[str]]:
    """断点项目优先，然后补充数据库内所有非 PC 完整详情项目。"""
    checkpoint_items = _load_checkpoint_items(checkpoint_path)
    checkpoint_ids = {_item_key(item) for item in checkpoint_items if _item_key(item)}
    merged: dict[str, RawShowItem] = {}
    unkeyed: list[RawShowItem] = []
    for item in checkpoint_items + _load_incomplete_raw_items(db_path, limit=limit):
        key = _item_key(item)
        if key:
            merged.setdefault(key, item)
        else:
            unkeyed.append(item)
    return list(merged.values())[:limit] + unkeyed[: max(0, limit - len(merged))], checkpoint_ids


async def backfill_detail() -> None:
    """从持久化断点/raw_items 加载待处理项目，逐项补跑并即时入库。"""
    config = load_config()
    db_path = Path(config.storage.db_path)
    if not db_path.is_absolute():
        db_path = project_root / db_path
    checkpoint_path = paths.data_dir() / "damai_detail_checkpoint.json"

    logger.info("数据库路径: %s", db_path)
    raw_items, checkpoint_ids = load_pending_items(db_path, checkpoint_path)
    logger.info(
        "成功加载 %s 个待处理项目（断点项目 %s 个）",
        len(raw_items),
        len(checkpoint_ids),
    )
    if not raw_items:
        logger.info("没有需要补跑的数据")
        return

    storage = SqliteStorage(root=db_path.parent / "backfill_run", db_path=db_path)

    async def persist_item(item: RawShowItem) -> None:
        shows = normalize_items([item], config=config.pipeline)
        storage.save_raw([item])
        storage.save_shows(shows)
        logger.info(
            "补跑项目已即时入库 item=%s sessions=%s rows=%s",
            item.source_id,
            len(item.sessions_raw),
            len(shows),
        )

    logger.info("启动浏览器进行详情补跑...")
    async with browser_session(config.browser, config.captcha, platform="damai") as session:
        async with session.page() as page:
            enriched = await enrich_items_detail(
                page,
                raw_items,
                delay_s=float(config.crawl.detail_delay_seconds or 1.5),
                fetch_all_dates=True,
                date_limit=int(config.crawl.detail_date_limit),
                request_attempts=int(config.crawl.detail_retry_attempts),
                retry_delay_s=float(config.crawl.detail_retry_delay_seconds),
                max_retry_delay_s=float(config.crawl.detail_retry_max_backoff_seconds),
                project_attempts=int(config.crawl.detail_project_attempts),
                project_cooldown_s=float(config.crawl.detail_project_cooldown_seconds),
                punish_cooldown_min_s=float(
                    config.crawl.detail_punish_cooldown_min_seconds
                ),
                punish_cooldown_max_s=float(
                    config.crawl.detail_punish_cooldown_max_seconds
                ),
                punish_retry_cooldown_min_s=float(
                    config.crawl.detail_punish_retry_cooldown_min_seconds
                ),
                punish_retry_cooldown_max_s=float(
                    config.crawl.detail_punish_retry_cooldown_max_seconds
                ),
                punish_max_cooldowns=int(config.crawl.detail_punish_max_cooldowns),
                checkpoint_path=checkpoint_path,
                on_item=persist_item,
            )

    successful_ids = {_item_key(item) for item in enriched if _item_key(item)}
    if checkpoint_ids and checkpoint_ids.issubset(successful_ids):
        checkpoint_path.unlink(missing_ok=True)
    logger.info("补跑完成：项目 %s 个；每个完成项目均已即时入库", len(enriched))


if __name__ == "__main__":
    asyncio.run(backfill_detail())
