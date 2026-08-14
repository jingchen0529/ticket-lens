#!/usr/bin/env python3
"""低并发在线验收大麦详情与 bixi 熔断逻辑。

该脚本直接调用生产 ``enrich_items_detail``，但不会创建 Storage、写正式
SQLite 或保存浏览器 Cookie。所有观测结果写入独立的 artifacts 运行目录。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.browser.session import browser_session
from app.core.config import load_config
from app.crawlers.damai import detail as detail_module
from app.crawlers.damai.detail import (
    BixiPunishError,
    PcDetailCircuitOpenError,
    enrich_items_detail,
)
from app.models import RawShowItem, SourcePlatform


DEFAULT_ITEM_IDS = (
    "1074019772992",  # 低负载 PC 完整对照
    "1073716080825",  # PC 业务空壳，预期移动端区间价兜底
    "1007108168970",  # 历史 bixi 项目；必须放最后
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temp.replace(path)


def _file_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _make_item(item_id: str) -> RawShowItem:
    return RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id=item_id,
        title=f"在线验收-{item_id}",
        url=f"https://detail.damai.cn/item.htm?id={item_id}",
    )


def _session_summary(session: dict[str, Any]) -> dict[str, Any]:
    tiers = [tier for tier in session.get("ticket_tiers") or [] if isinstance(tier, dict)]
    prices = sorted(
        {
            float(tier["price"])
            for tier in tiers
            if isinstance(tier.get("price"), (int, float))
        }
    )
    return {
        "session_id": str(session.get("session_id") or session.get("id") or ""),
        "name": str(session.get("name") or ""),
        "start_time": str(session.get("start_time") or ""),
        "tier_count": len(tiers),
        "prices": prices,
    }


def _item_summary(item: RawShowItem) -> dict[str, Any]:
    detail = item.raw_payload.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    sessions = [s for s in item.sessions_raw if isinstance(s, dict)]
    session_summaries = [_session_summary(session) for session in sessions]
    detail_source = str(detail.get("detail_source") or "")
    tier_source = str(detail.get("ticket_tier_source") or "")
    if detail_source == "damai_pc_subpage" and detail.get("detail_complete") is True:
        outcome = "pc_complete"
    elif detail_source == "damai_mobile_mtop":
        outcome = "mobile_range_only"
    else:
        outcome = "incomplete"
    return {
        "item_id": item.source_id,
        "outcome": outcome,
        "title": item.title,
        "url": item.url,
        "price_raw": item.price_raw,
        "detail_source": detail_source,
        "ticket_tier_source": tier_source,
        "detail_complete": detail.get("detail_complete"),
        "session_count": len(sessions),
        "sessions_with_tiers": sum(s["tier_count"] > 0 for s in session_summaries),
        "tier_count": sum(s["tier_count"] for s in session_summaries),
        "calendar": {
            "count": detail.get("calendar_date_count"),
            "fetched": detail.get("calendar_dates_fetched"),
            "failed": detail.get("calendar_dates_failed") or [],
        },
        "tickets": {
            "requested": detail.get("ticket_sessions_requested"),
            "fetched": detail.get("ticket_sessions_fetched"),
            "failed": detail.get("ticket_sessions_failed") or [],
        },
        "sessions": session_summaries,
    }


class _JsonLogHandler(logging.Handler):
    def __init__(
        self,
        path: Path,
        messages: list[str],
        artifact_errors: list[str],
    ) -> None:
        super().__init__()
        self._stream = path.open("a", encoding="utf-8")
        self._messages = messages
        self._artifact_errors = artifact_errors

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            self._messages.append(message)
            payload = {
                "utc": _utc_now(),
                "monotonic_ns": time.monotonic_ns(),
                "level": record.levelname,
                "logger": record.name,
                "message": message,
            }
            self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._stream.flush()
        except Exception as exc:  # noqa: BLE001 - 观测失败不得改变生产控制流
            self._artifact_errors.append(
                f"engine_log:{type(exc).__name__}:{exc}"
            )
            self.handleError(record)

    def close(self) -> None:
        self._stream.close()
        super().close()


async def _run(item_ids: list[str], output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "items").mkdir()
    checkpoint_path = output_dir / "breaker_checkpoint.json"
    request_log_path = output_dir / "requests.jsonl"
    engine_messages: list[str] = []
    artifact_errors: list[str] = []
    json_handler = _JsonLogHandler(
        output_dir / "engine.jsonl",
        engine_messages,
        artifact_errors,
    )
    stream_handler = logging.StreamHandler()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[stream_handler, json_handler],
        force=True,
    )
    # httpx 的 INFO 日志包含移动 MTop 的短期签名查询串；验收只需要记录
    # mobile_mtop 成功/失败事件，不把签名写入可分享的引擎日志。
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = load_config()
    crawl = config.crawl
    captcha = config.captcha_for("damai")
    cookie_file = Path(captcha.cookie_dir) / "damai_storage.json"
    db_file = Path(config.storage.db_path)
    before_cookie = _file_state(cookie_file)
    before_db = _file_state(db_file)
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    request_events: list[dict[str, Any]] = []
    completed: dict[str, dict[str, Any]] = {}
    exception: dict[str, str] | None = None
    context_facts: dict[str, Any] = {}
    cancelled = False

    manifest = {
        "schema_version": 1,
        "started_at": started_at,
        "item_ids": item_ids,
        "production_entrypoint": "app.crawlers.damai.detail.enrich_items_detail",
        "single_browser_context": True,
        "single_page": True,
        "concurrency": 1,
        "database_used": False,
        "cookies_saved": False,
        "headless": bool(config.browser.headless),
        "proxy_enabled": bool(config.browser.proxy),
        "detail_delay_seconds": float(crawl.detail_delay_seconds),
        "ordinary_retry": {
            "attempts": int(crawl.detail_retry_attempts),
            "delay_seconds": float(crawl.detail_retry_delay_seconds),
        },
        "punish_cooldowns": [
            [
                float(crawl.detail_punish_cooldown_min_seconds),
                float(crawl.detail_punish_cooldown_max_seconds),
            ],
            [
                float(crawl.detail_punish_retry_cooldown_min_seconds),
                float(crawl.detail_punish_retry_cooldown_max_seconds),
            ],
        ],
        "punish_max_cooldowns": int(crawl.detail_punish_max_cooldowns),
        "cookie_file_before": before_cookie,
        "database_file_before": before_db,
    }
    _atomic_json(output_dir / "manifest.json", manifest)

    def record_request(payload: dict[str, Any]) -> None:
        request_events.append(payload)
        try:
            with request_log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 - 观测失败不得覆盖 bixi 异常
            artifact_errors.append(f"request_log:{type(exc).__name__}:{exc}")

    original_fetch_subpage = detail_module.fetch_subpage
    original_fetch_static = detail_module.fetch_item_static
    original_fetch_mobile = detail_module.fetch_mobile_item_detail
    request_sequence = 0

    async def traced_fetch_subpage(page: Any, item_id: str, **kwargs: Any) -> Any:
        nonlocal request_sequence
        request_sequence += 1
        sequence = request_sequence
        started = time.monotonic()
        event = {
            "seq": sequence,
            "utc": _utc_now(),
            "channel": "pc_subpage",
            "item_id": item_id,
            "data_type": str(kwargs.get("data_type") or ""),
            "data_id": str(kwargs.get("data_id") or ""),
        }
        try:
            result = await original_fetch_subpage(page, item_id, **kwargs)
            event["outcome"] = "parsed" if isinstance(result, dict) else "unavailable"
            return result
        except BixiPunishError as exc:
            event.update(
                {
                    "outcome": "bixi",
                    "status": exc.status,
                    "content_type": exc.content_type,
                    "body_chars": exc.body_chars,
                }
            )
            raise
        except Exception as exc:
            event.update({"outcome": "error", "error_type": type(exc).__name__})
            raise
        finally:
            event["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
            record_request(event)

    async def traced_fetch_static(page: Any, item_id: str, **kwargs: Any) -> Any:
        started = time.monotonic()
        event = {
            "utc": _utc_now(),
            "channel": "pc_item_static",
            "item_id": item_id,
        }
        try:
            result = await original_fetch_static(page, item_id, **kwargs)
            event["outcome"] = "parsed" if result else "empty"
            return result
        except Exception as exc:
            event["outcome"] = (
                "circuit_suspended"
                if isinstance(exc, PcDetailCircuitOpenError)
                else "error"
            )
            event["error_type"] = type(exc).__name__
            raise
        finally:
            event["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
            record_request(event)

    async def traced_fetch_mobile(item_id: str, **kwargs: Any) -> Any:
        started = time.monotonic()
        event = {
            "utc": _utc_now(),
            "channel": "mobile_mtop",
            "item_id": item_id,
        }
        try:
            result = await original_fetch_mobile(item_id, **kwargs)
            event["outcome"] = "parsed" if isinstance(result, dict) else "unavailable"
            return result
        except Exception as exc:
            event.update({"outcome": "error", "error_type": type(exc).__name__})
            raise
        finally:
            event["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
            record_request(event)

    detail_module.fetch_subpage = traced_fetch_subpage
    detail_module.fetch_item_static = traced_fetch_static
    detail_module.fetch_mobile_item_detail = traced_fetch_mobile

    async def persist_result(item: RawShowItem) -> None:
        summary = _item_summary(item.model_copy(deep=True))
        summary["finished_at"] = _utc_now()
        completed[item.source_id] = summary
        try:
            _atomic_json(output_dir / "items" / f"{item.source_id}.json", summary)
        except Exception as exc:  # noqa: BLE001 - 不干扰被验收的生产状态机
            artifact_errors.append(f"item_result:{type(exc).__name__}:{exc}")
        logging.getLogger(__name__).info(
            "live acceptance item complete id=%s outcome=%s sessions=%s tiers=%s",
            item.source_id,
            summary["outcome"],
            summary["session_count"],
            summary["tier_count"],
        )

    try:
        async with browser_session(config.browser, captcha, platform="damai") as session:
            async with session.page() as page:
                user_agent = await page.evaluate("() => navigator.userAgent")
                applicable_cookies = await page.context.cookies(
                    ["https://detail.damai.cn/"]
                )
                context_facts = {
                    "navigator_user_agent": str(user_agent),
                    "detail_cookie_count": len(applicable_cookies),
                    "detail_cookie_names": sorted(
                        {
                            f"{cookie.get('name')}@{cookie.get('domain')}"
                            for cookie in applicable_cookies
                        }
                    ),
                }
                await enrich_items_detail(
                    page,
                    [_make_item(item_id) for item_id in item_ids],
                    delay_s=float(crawl.detail_delay_seconds),
                    fetch_all_dates=True,
                    date_limit=int(crawl.detail_date_limit),
                    request_attempts=int(crawl.detail_retry_attempts),
                    retry_delay_s=float(crawl.detail_retry_delay_seconds),
                    max_retry_delay_s=float(crawl.detail_retry_max_backoff_seconds),
                    project_attempts=int(crawl.detail_project_attempts),
                    project_cooldown_s=float(crawl.detail_project_cooldown_seconds),
                    punish_cooldown_min_s=float(
                        crawl.detail_punish_cooldown_min_seconds
                    ),
                    punish_cooldown_max_s=float(
                        crawl.detail_punish_cooldown_max_seconds
                    ),
                    punish_retry_cooldown_min_s=float(
                        crawl.detail_punish_retry_cooldown_min_seconds
                    ),
                    punish_retry_cooldown_max_s=float(
                        crawl.detail_punish_retry_cooldown_max_seconds
                    ),
                    punish_max_cooldowns=int(crawl.detail_punish_max_cooldowns),
                    checkpoint_path=checkpoint_path,
                    on_item=persist_result,
                )
    except PcDetailCircuitOpenError as exc:
        exception = {"type": type(exc).__name__, "message": str(exc)}
        logging.getLogger(__name__).warning("live acceptance circuit suspended: %s", exc)
    except asyncio.CancelledError as exc:
        cancelled = True
        exception = {"type": type(exc).__name__, "message": "online acceptance cancelled"}
        logging.getLogger(__name__).warning("live acceptance cancelled")
    except Exception as exc:  # noqa: BLE001 - 验收必须写出失败摘要
        exception = {"type": type(exc).__name__, "message": str(exc)}
        logging.getLogger(__name__).exception("live acceptance failed")
    finally:
        detail_module.fetch_subpage = original_fetch_subpage
        detail_module.fetch_item_static = original_fetch_static
        detail_module.fetch_mobile_item_detail = original_fetch_mobile

    after_cookie = _file_state(cookie_file)
    after_db = _file_state(db_file)
    bixi_events = [event for event in request_events if event.get("outcome") == "bixi"]
    bixi_item_ids = {
        str(event.get("item_id") or "") for event in bixi_events if event.get("item_id")
    }
    for message in engine_messages:
        match = re.search(r"(?:subpage|item\.htm) bixi punish item=(\d+)", message)
        if match:
            bixi_item_ids.add(match.group(1))
    mobile_events = [event for event in request_events if event.get("channel") == "mobile_mtop"]
    mobile_item_ids = {
        str(event.get("item_id") or "") for event in mobile_events if event.get("item_id")
    }
    cooldowns = []
    for message in engine_messages:
        match = re.search(r"damai pc circuit open .* cooldown=([0-9.]+)s", message)
        if match:
            cooldowns.append(float(match.group(1)))
    checkpoint = None
    if checkpoint_path.exists():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            checkpoint = {"read_error": str(exc)}

    missing_ids = [item_id for item_id in item_ids if item_id not in completed]
    expected_errors: list[str] = []
    if item_ids == list(DEFAULT_ITEM_IDS):
        if completed.get(DEFAULT_ITEM_IDS[0], {}).get("outcome") != "pc_complete":
            expected_errors.append(f"{DEFAULT_ITEM_IDS[0]} expected pc_complete")
        if completed.get(DEFAULT_ITEM_IDS[1], {}).get("outcome") != "mobile_range_only":
            expected_errors.append(f"{DEFAULT_ITEM_IDS[1]} expected mobile_range_only")

    bixi_mobile_overlap = sorted(bixi_item_ids & mobile_item_ids)
    if bixi_item_ids:
        if bixi_mobile_overlap:
            verdict = "fail_bixi_used_mobile_fallback"
        elif exception and exception.get("type") == "PcDetailCircuitOpenError":
            checkpoint_item = str(
                ((checkpoint or {}).get("request") or {}).get("item_id") or ""
            )
            if (
                checkpoint_item in bixi_item_ids
                and (checkpoint or {}).get("state") == "suspended"
            ):
                verdict = "pass_circuit_suspended_without_mobile_fallback"
            else:
                verdict = "fail_circuit_checkpoint_mismatch"
        elif missing_ids or expected_errors:
            verdict = "fail_baseline_or_missing_after_bixi"
        elif all(
            completed.get(item_id, {}).get("outcome") == "pc_complete"
            for item_id in bixi_item_ids
        ):
            verdict = "pass_bixi_recovered_to_pc_complete"
        else:
            verdict = "fail_bixi_control_flow"
    elif exception or missing_ids or expected_errors:
        verdict = "fail_without_bixi"
    else:
        verdict = "inconclusive_bixi_not_observed"
    if artifact_errors:
        verdict = "fail_acceptance_artifact_write"

    summary = {
        "schema_version": 1,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "item_ids": item_ids,
        "completed_ids": list(completed),
        "not_reached_ids": missing_ids,
        "items": completed,
        "exception": exception,
        "request_count": len(request_events),
        "bixi_count": len(bixi_events),
        "bixi_item_ids": sorted(bixi_item_ids),
        "mobile_request_count": len(mobile_events),
        "bixi_mobile_overlap": bixi_mobile_overlap,
        "observed_cooldowns_seconds": cooldowns,
        "checkpoint_exists": checkpoint_path.exists(),
        "checkpoint": checkpoint,
        "logic_verdict": verdict,
        "expected_errors": expected_errors,
        "artifact_errors": artifact_errors,
        "context": context_facts,
        "cookie_file_unchanged": before_cookie == after_cookie,
        "database_file_unchanged": before_db == after_db,
        "cookie_file_after": after_cookie,
        "database_file_after": after_db,
        "database_used": False,
        "cookies_saved": False,
    }
    _atomic_json(output_dir / "summary.json", summary)
    logging.getLogger(__name__).info(
        "live acceptance finished verdict=%s output=%s", verdict, output_dir
    )
    json_handler.close()
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "logic_verdict": verdict,
                "completed_ids": list(completed),
                "request_count": len(request_events),
                "bixi_count": len(bixi_events),
                "exception": exception,
            },
            ensure_ascii=False,
        )
    )
    if cancelled:
        return 130
    return 0 if verdict.startswith("pass_") or verdict.startswith("inconclusive_") else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--item-id",
        action="append",
        dest="item_ids",
        help="按执行顺序追加项目 ID；不传时使用三个内置验收项目",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project_root / "artifacts" / "damai-live-detail-acceptance",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    requested_ids = args.item_ids or list(DEFAULT_ITEM_IDS)
    item_ids: list[str] = []
    for item_id in requested_ids:
        cleaned = str(item_id or "").strip()
        if not re.fullmatch(r"\d+", cleaned):
            raise SystemExit(f"无效项目 ID：{item_id!r}")
        if cleaned not in item_ids:
            item_ids.append(cleaned)
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    output_dir = args.output_root.resolve() / run_id
    print(f"LIVE_ACCEPTANCE_OUTPUT={output_dir}", flush=True)
    return asyncio.run(_run(item_ids, output_dir))


if __name__ == "__main__":
    raise SystemExit(main())
