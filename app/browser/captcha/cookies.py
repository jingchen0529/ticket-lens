"""按平台持久化浏览器 storage_state，减少重复验证。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from playwright.async_api import BrowserContext

logger = logging.getLogger(__name__)


def cookie_path(base_dir: str | Path, platform: str) -> Path:
    root = Path(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{platform}_storage.json"


def _domain_allowed(value: str, allowed_domains: tuple[str, ...]) -> bool:
    host = str(value or "").strip().lower().lstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def filter_storage_state(
    state: dict[str, Any],
    allowed_domains: Iterable[str] | None,
) -> dict[str, Any]:
    """按严格域边界过滤 Cookie 与 localStorage origins。"""
    domains = tuple(
        str(domain or "").strip().lower().lstrip(".")
        for domain in (allowed_domains or ())
        if str(domain or "").strip()
    )
    if not domains:
        return state
    filtered = dict(state)
    filtered["cookies"] = [
        cookie
        for cookie in state.get("cookies") or []
        if isinstance(cookie, dict)
        and _domain_allowed(str(cookie.get("domain") or ""), domains)
    ]
    origins = []
    for origin in state.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        try:
            host = str(urlparse(str(origin.get("origin") or "")).hostname or "")
        except ValueError:
            host = ""
        if _domain_allowed(host, domains):
            origins.append(origin)
    filtered["origins"] = origins
    return filtered


async def load_storage_state(
    path: Path,
    *,
    allowed_domains: Iterable[str] | None = None,
) -> dict | None:
    if not path.exists():
        return None
    try:
        import orjson

        state = orjson.loads(path.read_bytes())
        if not isinstance(state, dict):
            return None
        return filter_storage_state(state, allowed_domains)
    except Exception as exc:  # noqa: BLE001
        logger.warning("load storage_state failed %s: %s", path, exc)
        return None


async def save_storage_state(
    context: BrowserContext,
    path: Path,
    *,
    allowed_domains: Iterable[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not allowed_domains:
        await context.storage_state(path=str(path))
        logger.info("saved storage_state → %s", path)
        return

    import orjson

    state = await context.storage_state()
    filtered = filter_storage_state(state, allowed_domains)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_bytes(orjson.dumps(filtered, option=orjson.OPT_INDENT_2))
    temp_path.replace(path)
    logger.info("saved storage_state → %s", path)
