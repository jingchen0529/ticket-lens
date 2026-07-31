#!/usr/bin/env python3
"""冰拓 1358 + 真鼠标过水果滑块，并从指定 currPage 续拉 searchajax。

用法:
  source .venv/bin/activate
  python scripts/bingtop_live_crawl.py [--start 16] [--end 40] [--headless]

默认开启 DAXI_CAPTCHA_PROBE=1，每轮拖动后落盘：
  data/captcha_probe/bingtop_live/last_compare.png   # 对照图
  data/captcha_probe/bingtop_live/last_ab_grid.png   # A/B 网格
  data/captcha_probe/bingtop_live/last_drag_compare.json
  data/captcha_probe/bingtop_live/success_history.jsonl  # 仅 code=0
用 --no-probe 关闭。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from playwright.async_api import async_playwright  # noqa: E402

from app.core.config import load_config  # noqa: E402
from app.browser.captcha.cookies import (  # noqa: E402
    cookie_path,
    load_storage_state,
    save_storage_state,
)
from app.crawlers.damai.captcha import DamaiCaptchaSolver  # noqa: E402
from app.crawlers.damai.fruit_slider import (  # noqa: E402
    CaptchaPayload,
    attach_payload_listener,
    detect_fruit_slider,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bingtop_live")
OUT = Path("data/captcha_probe/bingtop_live")
MERGED = Path("data/damai_search_items_merged.json")


def _kid(it: dict) -> str:
    return str(it.get("id") or it.get("projectid") or it.get("projectId") or it.get("itemId") or "")


def _is_blocked(j: dict | None) -> tuple[bool, str | None]:
    if not isinstance(j, dict):
        return False, None
    ret = j.get("ret") or []
    if not isinstance(ret, list):
        ret = [ret]
    if any("USER_VALIDATE" in str(x) or "RGV587" in str(x) for x in ret):
        data = j.get("data") if isinstance(j.get("data"), dict) else {}
        return True, data.get("url")
    return False, None


def _items(j: dict | None) -> list:
    if not isinstance(j, dict):
        return []
    pd = j.get("pageData") or j
    rd = pd.get("resultData") if isinstance(pd, dict) else None
    if isinstance(rd, list):
        return rd
    if isinstance(rd, dict) and isinstance(rd.get("projectInfo"), list):
        return rd["projectInfo"]
    return []


def _norm_punish(u: str) -> str:
    if u.startswith("//"):
        u = "https:" + u
    return u.replace("://search.damai.cn//", "://search.damai.cn/")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=16)
    ap.add_argument("--end", type=int, default=40)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max-solves", type=int, default=3)
    ap.add_argument(
        "--rounds",
        type=int,
        default=2,
        help="每次 solve 最多提交的新题数（失败自动换题后可继续，默认 2）",
    )
    ap.add_argument(
        "--no-probe",
        action="store_true",
        help="关闭对照图/A/B 网格落盘（默认开启 DAXI_CAPTCHA_PROBE=1）",
    )
    args = ap.parse_args()

    if args.no_probe:
        os.environ.pop("DAXI_CAPTCHA_PROBE", None)
    else:
        os.environ["DAXI_CAPTCHA_PROBE"] = "1"

    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg.browser.headless = args.headless
    cfg.captcha.allow_manual = False
    cfg.captcha.fruit_max_rounds = max(1, min(5, args.rounds))
    solver = DamaiCaptchaSolver(cfg)
    log.info(
        "provider=%s strategy=%s type=%s user=%s probe=%s",
        cfg.captcha.provider,
        cfg.captcha.fruit_strategy,
        cfg.captcha.fruit_captcha_type,
        bool(cfg.captcha.username),
        os.environ.get("DAXI_CAPTCHA_PROBE") == "1",
    )

    results: dict = {"pages_ok": [], "items": {}, "solves": [], "blocked": []}
    verify_events: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=args.headless,
            args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
        )
        context_kwargs: dict = dict(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 900},
        )
        storage_path = cookie_path(cfg.captcha.cookie_dir, "damai")
        if cfg.captcha.persist_cookies:
            storage_state = await load_storage_state(storage_path)
            if storage_state:
                context_kwargs["storage_state"] = storage_state
                log.info("loaded damai storage state from %s", storage_path)
        # Let Chromium advertise its real UA.  A fixed Chrome/122 UA does not
        # match the installed Playwright Chromium and is visible to risk checks.
        ctx = await browser.new_context(**context_kwargs)
        page = await ctx.new_page()
        page.set_default_timeout(10000)
        page.set_default_navigation_timeout(35000)
        payloads: list[CaptchaPayload] = []
        detach = await attach_payload_listener(page, payloads)

        async def on_resp(resp) -> None:
            try:
                if "newslidevalidate" in resp.url.lower():
                    t = await asyncio.wait_for(resp.text(), timeout=3)
                    verify_events.append(t[:300])
                    log.info("VALIDATE %s", t[:180])
            except Exception:  # noqa: BLE001
                return

        page.on("response", lambda r: asyncio.create_task(on_resp(r)))

        log.info("goto search.htm")
        try:
            await page.goto(
                "https://search.damai.cn/search.htm?order=1",
                wait_until="domcontentloaded",
                timeout=35000,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("goto search: %s", exc)
        await page.wait_for_timeout(800)

        async def fetch_page(n: int) -> dict:
            return await asyncio.wait_for(
                page.evaluate(
                    """async (n) => {
                      const url = 'https://search.damai.cn/searchajax.html?keyword=&cty=&ctl=&sctl=&tsg=0&st=&et=&order=1&pageSize=30&currPage=' + n + '&tn=';
                      const ctrl = new AbortController();
                      const timer = setTimeout(() => ctrl.abort(), 12000);
                      try {
                        const r = await fetch(url, {
                          credentials: 'include',
                          signal: ctrl.signal,
                          headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                            'Accept': 'application/json, text/javascript, */*; q=0.01',
                            'Referer': 'https://search.damai.cn/search.htm'
                          }
                        });
                        const t = await r.text();
                        try { return {status: r.status, j: JSON.parse(t)}; }
                        catch (e) { return {status: r.status, text: t.slice(0, 400)}; }
                      } finally {
                        clearTimeout(timer);
                      }
                    }""",
                    n,
                ),
                timeout=18.0,
            )

        cur = args.start
        solves = 0
        attempts = 0
        while cur <= args.end and attempts < (args.end - args.start + 1) * 3:
            attempts += 1
            log.info("fetch currPage=%s attempt=%s solves=%s", cur, attempts, solves)
            try:
                resp = await fetch_page(cur)
            except Exception as exc:  # noqa: BLE001
                log.warning("fetch timeout/error page=%s: %s", cur, exc)
                # 可能已弹出 captcha
                if await detect_fruit_slider(page) or "punish" in page.url:
                    pass
                else:
                    await page.wait_for_timeout(1000)
                    continue
                resp = {"j": None}

            j = resp.get("j") if isinstance(resp, dict) else None
            blocked, pun = _is_blocked(j)
            if blocked or j is None:
                log.info("blocked/missing at %s pun=%s url=%s", cur, (pun or "")[:100], page.url[:80])
                results["blocked"].append({"page": cur, "punish": pun})
                if pun:
                    try:
                        await page.goto(
                            _norm_punish(pun),
                            wait_until="domcontentloaded",
                            timeout=25000,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning("goto punish: %s", exc)
                for _ in range(25):
                    if await detect_fruit_slider(page):
                        break
                    await page.wait_for_timeout(200)
                if not await detect_fruit_slider(page):
                    log.warning("no fruit UI after punish; page text=%s", (await page.inner_text("body"))[:120])
                    solves += 1
                    continue

                if solves >= max(0, args.max_solves):
                    log.error("captcha solve budget exhausted (%s)", args.max_solves)
                    break

                solves += 1
                t0 = time.time()
                # 出题响应已在外层 listener 截到；必须把 last payload 传给 solver，
                # 否则 ensure_cleared 内新建空 listener 永远 miss（response 不能重放）。
                last_pl = payloads[-1] if payloads else None
                log.info(
                    "solving fruit with bingtop… (payloads=%s img=%s ques=%s has_token=%s key=%s)",
                    len(payloads),
                    len(last_pl.image_data) if last_pl and last_pl.image_data else 0,
                    len(last_pl.ques) if last_pl and last_pl.ques else 0,
                    bool(last_pl and last_pl.encrypt_token),
                    (last_pl.content_key()[:40] if last_pl else ""),
                )
                # 交给 solver 的 hint 只用于本次；本地 list 立刻清空，避免失败后再次塞旧图
                payloads.clear()
                try:
                    result = await asyncio.wait_for(
                        solver.ensure_cleared(page, payload_hint=last_pl),
                        timeout=120.0,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("ensure_cleared error: %s", exc)
                    result = None
                dt = time.time() - t0
                ok = bool(getattr(result, "ok", False) or getattr(result, "success", False))
                log.info(
                    "solve ok=%s in %.1fs result=%s verify=%s",
                    ok,
                    dt,
                    str(result)[:160],
                    verify_events[-1] if verify_events else None,
                )
                results["solves"].append(
                    {
                        "ok": ok,
                        "sec": round(dt, 2),
                        "verify": verify_events[-1] if verify_events else None,
                        "page": cur,
                        "had_payload": bool(last_pl and last_pl.image_data and last_pl.ques),
                        "payload_img_b": len(last_pl.image_data) if last_pl and last_pl.image_data else 0,
                        "payload_ques_b": len(last_pl.ques) if last_pl and last_pl.ques else 0,
                    }
                )
                payloads.clear()
                await page.wait_for_timeout(600)
                # 成功后从同页重试，不回 page1
                continue

            items = _items(j)
            if not items:
                log.warning("empty items page=%s keys=%s", cur, list(j.keys())[:12])
                cur += 1
                continue
            results["pages_ok"].append(cur)
            results["items"][str(cur)] = items
            log.info(
                "OK page %s n=%s sample=%s",
                cur,
                len(items),
                items[0].get("name") if items else None,
            )
            cur += 1
            await page.wait_for_timeout(180)

        detach()
        # merge
        old = json.loads(MERGED.read_text()) if MERGED.exists() else {"items": [], "pages_ok": []}
        items = list(old.get("items") or [])
        seen = {_kid(x) for x in items if _kid(x)}
        pages = set(old.get("pages_ok") or [])
        added = 0
        for pk, its in results["items"].items():
            pages.add(int(pk))
            for it in its:
                k = _kid(it)
                if k and k not in seen:
                    seen.add(k)
                    items.append(it)
                    added += 1
        out = {
            "pages_ok": sorted(pages),
            "count": len(items),
            "items": items,
            "last_run": {
                "pages_ok": results["pages_ok"],
                "added": added,
                "solves": results["solves"],
            },
        }
        MERGED.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        (OUT / "run_meta.json").write_text(
            json.dumps(
                {
                    "pages_ok": results["pages_ok"],
                    "added": added,
                    "solves": results["solves"],
                    "blocked": results["blocked"][-5:],
                    "total": len(items),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        log.info(
            "DONE run_pages=%s added=%s total=%s solves=%s",
            results["pages_ok"],
            added,
            len(items),
            results["solves"],
        )
        if cfg.captcha.persist_cookies and any(s.get("ok") for s in results["solves"]):
            await save_storage_state(ctx, storage_path)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
