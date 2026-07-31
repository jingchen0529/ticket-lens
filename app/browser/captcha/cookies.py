"""按平台持久化浏览器 storage_state，减少重复验证。"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import BrowserContext

logger = logging.getLogger(__name__)


def cookie_path(base_dir: str | Path, platform: str) -> Path:
    root = Path(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{platform}_storage.json"


async def load_storage_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        import orjson

        return orjson.loads(path.read_bytes())
    except Exception as exc:  # noqa: BLE001
        logger.warning("load storage_state failed %s: %s", path, exc)
        return None


async def save_storage_state(context: BrowserContext, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(path))
    logger.info("saved storage_state → %s", path)
