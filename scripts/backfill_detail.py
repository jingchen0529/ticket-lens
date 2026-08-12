#!/usr/bin/env python3
"""补跑详情富化：为已入库但未富化的演出补全场次/票档/地址信息。"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.browser.session import browser_session
from app.core.config import load_config
from app.crawlers.damai.detail import enrich_items_detail
from app.models import RawShowItem
from app.pipeline.normalize import normalize_items

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def backfill_detail():
    """从数据库加载未富化的演出，补跑详情，重新规范化入库。"""
    config = load_config()

    # 1. 从数据库读取未富化的原始数据
    logger.info("加载未富化的演出数据...")
    import sqlite3
    import orjson
    from app.repositories.storage.sqlite_store import SqliteStorage

    db_path = Path(config.storage.db_path)
    if not db_path.is_absolute():
        db_path = project_root / db_path

    logger.info(f"数据库路径: {db_path}")
    db = sqlite3.connect(db_path)
    cursor = db.execute("""
        SELECT payload FROM shows
        WHERE json_extract(payload, '$.extras.detail_enriched') IS NULL
           OR json_extract(payload, '$.extras.detail_enriched') = 0
        LIMIT 1000
    """)

    rows = cursor.fetchall()
    db.close()

    logger.info(f"找到 {len(rows)} 条未富化演出")

    if not rows:
        logger.info("没有需要补跑的数据")
        return

    # 2. 反序列化为 RawShowItem（从 Show 的 payload 提取原始字段）
    raw_items: list[RawShowItem] = []
    for (payload_json,) in rows:
        try:
            show_data = orjson.loads(payload_json)
            # 从 Show 重建 RawShowItem
            raw = RawShowItem(
                source=show_data["source"],
                source_id=show_data["source_id"],
                url=show_data.get("url", ""),
                title=show_data["title"],
                city=show_data.get("venue", {}).get("city", ""),
                venue_name=show_data.get("venue", {}).get("name", ""),
                venue_address=show_data.get("venue", {}).get("address", ""),
                category=show_data.get("category", ""),
                artists=show_data.get("artists", []),
                poster_url=show_data.get("poster_url", ""),
                price_raw=show_data.get("extras", {}).get("price_raw", ""),
                status_raw=show_data.get("extras", {}).get("status_raw", ""),
                start_time_raw=show_data.get("extras", {}).get("start_time_raw", ""),
                sessions_raw=show_data.get("sessions", []),
                raw_payload={"from_api": show_data.get("extras", {}).get("from_api", False)},
                crawled_at=show_data.get("crawled_at"),
            )
            raw_items.append(raw)
        except Exception as exc:
            logger.warning(f"反序列化失败: {exc}")
            continue

    logger.info(f"成功加载 {len(raw_items)} 条待处理数据")

    if not raw_items:
        return

    # 3. 启动浏览器会话，批量富化
    logger.info("启动浏览器进行详情富化...")
    from app.browser.session import browser_session

    async with browser_session(config.browser, config.captcha, platform="damai") as session:
        async with session.page() as page:
            enriched = await enrich_items_detail(
                page,
                raw_items,
                delay_s=float(config.crawl.detail_delay_seconds or 1.5),
                fetch_all_dates=True,
                date_limit=int(config.crawl.detail_date_limit),
                request_attempts=int(config.crawl.detail_retry_attempts),
                max_retry_delay_s=float(
                    config.crawl.detail_retry_max_backoff_seconds
                ),
                project_attempts=int(config.crawl.detail_project_attempts),
                project_cooldown_s=float(
                    config.crawl.detail_project_cooldown_seconds
                ),
            )

    # 4. 规范化并入库
    logger.info("规范化并更新数据库...")
    shows = normalize_items(enriched, config=config.pipeline)

    # 使用 SqliteStorage 保存
    storage = SqliteStorage(root=db_path.parent / "backfill_run", db_path=db_path)
    storage.save_shows(shows)

    enriched_count = sum(1 for s in shows if s.extras and s.extras.get("detail_enriched"))
    logger.info(f"✓ 补跑完成: 处理 {len(shows)} 条，成功富化 {enriched_count} 条")


if __name__ == "__main__":
    asyncio.run(backfill_detail())
