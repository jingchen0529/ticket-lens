#!/usr/bin/env python3
"""大麦水果滑块端到端测试：触发验证 → 自动过码 → 续拉 searchajax → 写 SQLite。

链路（复用现有业务代码，不另起一套协议）：
  1. BrowserSession 启 Chromium（可加载 data/cookies/damai 历史 cookie）
  2. DamaiCrawler：search.htm 建会话
  3. 从 --start 刷到 --end 的 currPage；命中 USER_VALIDATE / 水果滑块时
     DamaiCaptchaSolver.ensure_cleared（冰拓 1358 + 真鼠标拖官方滑块）
  4. 解析为 RawShowItem → normalize → SqliteStorage 落库
  5. 打印 solves / 行数 / db 路径，便于你一眼判断是否“过码 + 入库”成功

用法（在 backend/ 目录）：
  source .venv/bin/activate
  # 有头观察，从高页触发风控（更容易出滑块）
  python scripts/test_damai_slider_e2e_sqlite.py --headed --start 16 --end 25

  # 无头 + 指定固定库路径
  python scripts/test_damai_slider_e2e_sqlite.py --start 1 --end 3 \\
      --db data/daxi_e2e_test.sqlite3

  # 只测过码不写库
  python scripts/test_damai_slider_e2e_sqlite.py --headed --start 20 --end 30 --no-db

  # 强制关掉 manual 兜底（纯自动）
  python scripts/test_damai_slider_e2e_sqlite.py --headed --start 16 --end 22 --no-manual

依赖配置：
  configs/default.yaml 里 captcha.provider=bingtop + username/password
  或环境变量 DAXI_CAPTCHA_USERNAME / DAXI_CAPTCHA_PASSWORD
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.browser.session import BrowserSession  # noqa: E402
from app.core.config import load_config  # noqa: E402
from app.crawlers.damai.crawler import DamaiCrawler  # noqa: E402
from app.crawlers.damai.fruit_slider import (  # noqa: E402
    CaptchaPayload,
    attach_payload_listener,
    detect_fruit_slider,
    solve_fruit_slider,
)
from app.browser.captcha.base import CaptchaSolveResult  # noqa: E402
from app.models import CrawlJob, CrawlResult, RawShowItem, SourcePlatform  # noqa: E402
from app.pipeline.normalize import normalize_items  # noqa: E402
from app.repositories.storage.sqlite_store import SqliteStorage  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("e2e_slider_sqlite")

OUT_DIR = _ROOT / "data" / "captcha_probe" / "e2e_slider_sqlite"


def _db_counts(db_path: Path) -> dict[str, int]:
    if not db_path.is_file():
        return {"shows": 0, "raw_items": 0, "crawl_runs": 0}
    conn = sqlite3.connect(str(db_path))
    try:
        out: dict[str, int] = {}
        for table in ("shows", "raw_items", "crawl_runs"):
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                out[table] = int(row[0]) if row else 0
            except sqlite3.Error:
                out[table] = -1
        # damai 专表统计
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM shows WHERE source = ?",
                ("damai",),
            ).fetchone()
            out["shows_damai"] = int(row[0]) if row else 0
        except sqlite3.Error:
            out["shows_damai"] = -1
        return out
    finally:
        conn.close()


def _sample_titles(db_path: Path, limit: int = 5) -> list[str]:
    if not db_path.is_file():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT title FROM shows WHERE source = ? ORDER BY rowid DESC LIMIT ?",
            ("damai", limit),
        ).fetchall()
        return [str(r[0]) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


async def run_e2e(args: argparse.Namespace) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config(_ROOT / "configs" / "default.yaml")
    cfg.browser.headless = not args.headed
    if args.no_manual:
        cfg.captcha.allow_manual = False
    cfg.captcha.auto = True
    # 固定写 sqlite 路径（测试可指向临时库，避免污染生产库）
    cfg.storage.backend = "sqlite"
    cfg.storage.run_subdir = False
    if args.db:
        cfg.storage.db_path = args.db
    # 相对路径统一相对 backend/
    db_path = Path(cfg.storage.db_path)
    if not db_path.is_absolute():
        db_path = (_ROOT / db_path).resolve()
    cfg.storage.db_path = str(db_path)

    log.info(
        "config provider=%s strategy=%s type=%s user=%s headless=%s db=%s pages=%s..%s city=%r kw=%r",
        cfg.captcha.provider,
        cfg.captcha.fruit_strategy,
        cfg.captcha.fruit_captcha_type,
        bool(cfg.captcha.username),
        cfg.browser.headless,
        db_path,
        args.start,
        args.end,
        args.city,
        args.keyword,
    )
    if cfg.captcha.provider == "bingtop" and not (
        cfg.captcha.username and cfg.captcha.password
    ):
        raise SystemExit(
            "冰拓凭证缺失：请在 configs/default.yaml 填 captcha.username/password "
            "或 export DAXI_CAPTCHA_USERNAME / DAXI_CAPTCHA_PASSWORD"
        )

    before = _db_counts(db_path) if not args.no_db else {}
    meta: dict = {
        "started_at": datetime.utcnow().isoformat() + "Z",
        "pages_ok": [],
        "pages_empty": [],
        "blocked": [],
        "solves": [],
        "raw_count": 0,
        "show_count": 0,
        "errors": [],
        "db_path": str(db_path),
        "db_before": before,
        "db_after": {},
        "sample_titles": [],
    }
    collected: list[RawShowItem] = []
    verify_events: list[str] = []

    session = BrowserSession(cfg.browser, cfg.captcha)
    crawler = DamaiCrawler(session, cfg)

    await session.start(platform="damai")
    try:
        async with session.page() as page:
            # 监听官方 verify 回包，方便对照是否真过码
            async def on_resp(resp) -> None:
                try:
                    u = (resp.url or "").lower()
                    if "newslidevalidate" in u or "slidevalidate" in u:
                        t = await asyncio.wait_for(resp.text(), timeout=3)
                        verify_events.append(t[:400])
                        log.info("VALIDATE %s", t[:200])
                except Exception:  # noqa: BLE001
                    return

            page.on("response", lambda r: asyncio.create_task(on_resp(r)))

            # 关键就挂 listener：出题包常在 searchajax 挂起期间就返回，
            # 若等过码时再挂会永远 miss → 冰拓 1358 无双图。
            early_payloads: list[CaptchaPayload] = []
            detach_payload = await attach_payload_listener(page, early_payloads)

            entry = crawler._build_search_url(args.city, args.keyword, 1)
            log.info("goto search entry %s", entry[:120])
            try:
                await crawler.goto(page, entry, wait_until="domcontentloaded")
            except Exception as exc:  # noqa: BLE001
                log.warning("goto entry: %s", exc)
            await page.wait_for_timeout(1000)
            # 首屏也可能直接出验证
            if await detect_fruit_slider(page) or "punish" in (page.url or ""):
                log.info("captcha already present on entry, solving…")
                t0 = time.time()
                await crawler._maybe_solve_captcha(page)
                meta["solves"].append(
                    {
                        "page": 0,
                        "sec": round(time.time() - t0, 2),
                        "trigger": "entry",
                        "verify": verify_events[-1] if verify_events else None,
                        "url": (page.url or "")[:160],
                    }
                )

            page_no = max(1, args.start)
            end = max(page_no, args.end)
            captcha_retries = 0
            max_captcha_retries = args.max_solves

            while page_no <= end:
                # 拉页前先看是否已弹滑块（避免 fetch 挂死前 UI 已出但没人处理）
                if await detect_fruit_slider(page) or "punish" in (page.url or ""):
                    log.warning(
                        "fruit/punish already visible before fetch page=%s url=%s",
                        page_no,
                        (page.url or "")[:100],
                    )
                    payload = None
                    fetch_hung = True
                else:
                    fetch_hung = False
                    log.info(
                        "fetch page=%s retries=%s items=%s",
                        page_no,
                        captcha_retries,
                        len(collected),
                    )
                    payload = await crawler._fetch_search_ajax(
                        page,
                        city=args.city,
                        keyword=args.keyword,
                        page_no=page_no,
                        timeout_ms=args.fetch_timeout_ms,
                    )
                    if payload is None:
                        # 超时/挂起：常见于风控拦截，需走滑块
                        fruit = await detect_fruit_slider(page)
                        log.warning(
                            "fetch returned None page=%s fruit=%s url=%s — treat as blocked",
                            page_no,
                            fruit,
                            (page.url or "")[:100],
                        )
                        fetch_hung = True

                if (
                    crawler._is_user_validate(payload)
                    or fetch_hung
                    or (payload is None and await detect_fruit_slider(page))
                ):
                    punish = (
                        crawler._punish_url(payload) if isinstance(payload, dict) else None
                    )
                    log.warning(
                        "blocked page=%s punish=%s hung=%s url=%s",
                        page_no,
                        (punish or "")[:100],
                        fetch_hung,
                        (page.url or "")[:80],
                    )
                    meta["blocked"].append(
                        {"page": page_no, "punish": punish, "at": datetime.utcnow().isoformat()}
                    )
                    if captcha_retries >= max_captcha_retries:
                        meta["errors"].append(
                            f"captcha retries exhausted at page={page_no}"
                        )
                        log.error("captcha retries exhausted at page=%s", page_no)
                        break
                    captcha_retries += 1

                    if punish:
                        try:
                            await crawler.goto(page, punish, wait_until="domcontentloaded")
                        except Exception as exc:  # noqa: BLE001
                            log.warning("goto punish: %s", exc)

                    # 等 UI
                    for _ in range(30):
                        if await detect_fruit_slider(page):
                            break
                        await page.wait_for_timeout(200)

                    t0 = time.time()
                    last_pl = early_payloads[-1] if early_payloads else None
                    log.info(
                        "solving fruit slider… (provider=%s strategy=%s early_payloads=%s "
                        "img=%s ques=%s)",
                        cfg.captcha.provider,
                        cfg.captcha.fruit_strategy,
                        len(early_payloads),
                        bool(last_pl and last_pl.image_data) if last_pl else False,
                        bool(last_pl and last_pl.ques) if last_pl else False,
                    )
                    result: CaptchaSolveResult | None = None
                    try:
                        # 有提前截获的双图时直接带 payload_hint，避免 solver 内新建空 listener 错过出题
                        if last_pl and last_pl.image_data and last_pl.ques:

                            async def _cleared() -> bool:
                                return not await detect_fruit_slider(page)

                            ok_drag = await asyncio.wait_for(
                                solve_fruit_slider(
                                    page,
                                    step=float(cfg.captcha.fruit_scan_step or 5),
                                    success_check=_cleared,
                                    max_rounds=2,
                                    wait_timeout_s=6.0,
                                    provider=getattr(crawler.captcha, "provider", None),
                                    strategy=str(cfg.captcha.fruit_strategy or "provider_first"),
                                    payload_hint=last_pl,
                                ),
                                timeout=args.solve_timeout,
                            )
                            result = CaptchaSolveResult(
                                ok=bool(ok_drag),
                                method=f"fruit_slider+early_payload:{cfg.captcha.provider}",
                                message="used early newslidecaptcha payload"
                                if ok_drag
                                else "early payload drag failed",
                            )
                        else:
                            result = await asyncio.wait_for(
                                crawler.captcha.ensure_cleared(page),
                                timeout=args.solve_timeout,
                            )
                    except Exception as exc:  # noqa: BLE001
                        log.warning("ensure_cleared/solve error: %s", exc)
                        result = None
                    # 用过一次出题包就清掉，避免下一轮拿过期 token
                    if last_pl is not None and early_payloads and early_payloads[-1] is last_pl:
                        early_payloads.clear()
                    dt = round(time.time() - t0, 2)
                    ok = bool(
                        result
                        and (
                            getattr(result, "ok", False)
                            or getattr(result, "success", False)
                        )
                    )
                    solve_rec = {
                        "page": page_no,
                        "ok": ok,
                        "sec": dt,
                        "method": getattr(result, "method", None) if result else None,
                        "message": (getattr(result, "message", None) or str(result))[:200]
                        if result
                        else None,
                        "verify": verify_events[-1] if verify_events else None,
                        "url_after": (page.url or "")[:160],
                        "early_payloads": len(early_payloads),
                    }
                    meta["solves"].append(solve_rec)
                    log.info("solve result %s", solve_rec)

                    # 仍在 punish 页则回 search 域
                    if "punish" in (page.url or "") or "_____tmd_____" in (page.url or ""):
                        try:
                            await crawler.goto(page, entry, wait_until="domcontentloaded")
                            await page.wait_for_timeout(600)
                        except Exception:  # noqa: BLE001
                            pass
                    # 同页重试，不推进 page_no
                    await page.wait_for_timeout(500)
                    continue

                batch = crawler._parse_api_payload(
                    {"url": "searchajax", "data": payload},
                    city=args.city or "全国",
                )
                if not batch and page_no == args.start:
                    batch = await crawler._parse_dom(page, city=args.city or "全国")

                if not batch:
                    log.warning("empty page=%s", page_no)
                    meta["pages_empty"].append(page_no)
                    # 连续空可能是真到头了；仍推进以免死循环
                    page_no += 1
                    captcha_retries = 0
                    await crawler._delay()
                    continue

                collected.extend(batch)
                meta["pages_ok"].append(page_no)
                sample = batch[0].title if batch else None
                log.info("OK page=%s n=%s sample=%r total_raw=%s", page_no, len(batch), sample, len(collected))
                captcha_retries = 0
                page_no += 1
                await crawler._delay()

            # 保存 cookie 供下次少触发验证
            try:
                await session.save_platform_cookies("damai")
                log.info("cookies saved for damai")
            except Exception as exc:  # noqa: BLE001
                log.warning("save cookies: %s", exc)

            try:
                detach_payload()
            except Exception:  # noqa: BLE001
                pass

    finally:
        await session.stop()

    meta["raw_count"] = len(collected)
    shows = normalize_items(collected, cfg.pipeline)
    meta["show_count"] = len(shows)
    meta["finished_at"] = datetime.utcnow().isoformat() + "Z"

    if args.no_db:
        log.info("skip db write (--no-db); raw=%s shows=%s", len(collected), len(shows))
    else:
        storage = SqliteStorage(db_path.parent, db_path=db_path)
        storage.save_raw(collected)
        storage.save_shows(shows)
        job = CrawlJob(
            sources=[SourcePlatform.DAMAI],
            cities=[args.city] if args.city else list(cfg.crawl.cities),
            keywords=[args.keyword] if args.keyword else [],
            max_pages=args.end - args.start + 1,
        )
        result = CrawlResult(
            job=job,
            started_at=datetime.fromisoformat(meta["started_at"].replace("Z", "")),
            finished_at=datetime.utcnow(),
            raw_count=len(collected),
            show_count=len(shows),
            by_source={"damai": len(collected)},
            errors=list(meta["errors"]),
            output_path=str(db_path),
        )
        storage.save_result(result)
        meta["db_after"] = _db_counts(db_path)
        meta["sample_titles"] = _sample_titles(db_path)
        log.info(
            "sqlite written path=%s before=%s after=%s samples=%s",
            db_path,
            meta["db_before"],
            meta["db_after"],
            meta["sample_titles"],
        )

    # 落盘 meta，便于 CI / 人工对照
    meta_path = OUT_DIR / "last_e2e_meta.json"
    # 不把完整 raw 塞进 meta；另存轻量 items 摘要
    summary_items = [
        {
            "source_id": i.source_id,
            "title": i.title,
            "city": i.city,
            "venue": i.venue_name,
            "showtime": i.start_time_raw,
            "price": i.price_raw,
            "url": i.url,
        }
        for i in collected[:200]
    ]
    (OUT_DIR / "last_items_summary.json").write_text(
        json.dumps(
            {"count": len(collected), "items": summary_items},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("meta → %s", meta_path)
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(
        description="大麦滑块 e2e：过验证 + searchajax 翻页 + 写 SQLite"
    )
    ap.add_argument("--start", type=int, default=16, help="起始 currPage（高页更易触发滑块）")
    ap.add_argument("--end", type=int, default=22, help="结束 currPage（含）")
    ap.add_argument("--city", default="", help="城市，空=全国")
    ap.add_argument("--keyword", default="", help="关键词")
    ap.add_argument("--headed", action="store_true", help="有头浏览器，方便观察/人工兜底")
    ap.add_argument(
        "--db",
        default="",
        help="SQLite 路径（默认 configs 的 storage.db_path，通常 data/daxi.sqlite3）",
    )
    ap.add_argument("--no-db", action="store_true", help="只跑链路不写库")
    ap.add_argument("--no-manual", action="store_true", help="关闭人工兜底，纯自动")
    ap.add_argument("--max-solves", type=int, default=8, help="单次运行最多过码次数")
    ap.add_argument("--solve-timeout", type=float, default=90.0, help="单次 ensure_cleared 超时秒")
    ap.add_argument(
        "--fetch-timeout-ms",
        type=int,
        default=12000,
        help="searchajax fetch AbortController 超时（毫秒）；过短易误判，过长会像卡住",
    )
    args = ap.parse_args()

    meta = asyncio.run(run_e2e(args))

    # 退出码：有数据或至少成功过一次码视为链路可用
    ok_solves = [s for s in meta.get("solves") or [] if s.get("ok")]
    has_data = (meta.get("raw_count") or 0) > 0
    pages_ok = meta.get("pages_ok") or []

    print("\n========== E2E SUMMARY ==========")
    print(f"pages_ok     : {pages_ok}")
    print(f"raw / shows  : {meta.get('raw_count')} / {meta.get('show_count')}")
    print(f"solves       : {json.dumps(meta.get('solves'), ensure_ascii=False)}")
    print(f"blocked times: {len(meta.get('blocked') or [])}")
    print(f"errors       : {meta.get('errors')}")
    if not args.no_db:
        print(f"db           : {meta.get('db_path')}")
        print(f"db_before    : {meta.get('db_before')}")
        print(f"db_after     : {meta.get('db_after')}")
        print(f"samples      : {meta.get('sample_titles')}")
    print(f"meta file    : {OUT_DIR / 'last_e2e_meta.json'}")
    print("=================================\n")

    if has_data or pages_ok:
        return 0
    if ok_solves and not has_data:
        # 过了码但没拉到页：仍算半成功，exit 2 方便脚本区分
        log.warning("captcha solved but no items collected")
        return 2
    if meta.get("blocked") and not ok_solves:
        log.error("hit captcha but solve failed")
        return 3
    log.error("no pages ok and no successful solve")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
