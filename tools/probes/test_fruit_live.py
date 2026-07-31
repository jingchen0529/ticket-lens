#!/usr/bin/env python3
"""实机测试大麦水果滑块：newslidecaptcha → updatePos 估距 → 一次拖动。

用法:
  source .venv/bin/activate
  python scripts/test_fruit_live.py [--headed] [--seconds 120] [--strategy local_only]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from app.core.config import load_config
from app.crawlers.damai.captcha import DamaiCaptchaSolver
from app.crawlers.damai.fruit_slider import (
    CaptchaPayload,
    attach_payload_listener,
    detect_fruit_slider,
    measure_geometry,
    solve_fruit_slider,
    wait_fruit_slider,
    _has_update_pos,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fruit_live")

OUT = Path("data/captcha_probe/fruit_live")
SEARCH_URL = (
    "https://search.damai.cn/search.htm?"
    "ctl=%E6%BC%94%E5%94%B1%E4%BC%9A&cty=%E5%8C%97%E4%BA%AC&order=1"
)
AJAX_PATH = (
    "/searchajax.html?keyword=%E6%BC%94%E5%94%B1%E4%BC%9A"
    "&cty=%E5%8C%97%E4%BA%AC&pageSize=5&currPage=1"
)


async def _safe(coro, name: str, default=None, timeout: float = 3.0):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        log.warning("%s: %s %s", name, type(exc).__name__, str(exc)[:140])
        return default


def _normalize_url(u: str) -> str:
    u = u.strip().rstrip("\\").rstrip("'\"")
    if u.startswith("//"):
        u = "https:" + u
    return u.replace("://search.damai.cn//", "://search.damai.cn/")


def _extract_punish_urls(text: str, base: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    patterns = [
        r"""((?:https?:)?//[^"'\\\s<>]+/_____tmd_____/punish\?x5secdata=[^"'\\\s<>]+)""",
        r"""['"]((?:https?:)?//[^"'\\\s]+/_____tmd_____/punish\?[^"'\\\s]+)['"]""",
        r"""['"](/(?:[^"'\\\s]*/)?_____tmd_____/punish\?x5secdata=[^"'\\\s]+)['"]""",
        r"""((?:https?:)?//search\.damai\.cn/+searchajax\.html/_____tmd_____/punish\?[^"'\\\s]+)""",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text):
            raw = m.group(1)
            u = urljoin(base, raw) if raw.startswith("/") else _normalize_url(raw)
            if "_____tmd_____" in u and "punish" in u and len(u) > 60:
                found.append(u)
    uniq: list[str] = []
    for u in found:
        if u not in uniq:
            uniq.append(u)
    uniq.sort(
        key=lambda u: (1 if "x5secdata=" in u else 0, 1 if "capslide" in u.lower() else 0, len(u)),
        reverse=True,
    )
    return uniq


def _best_punish(urls: list[str]) -> str | None:
    if not urls:
        return None
    best = sorted(
        urls,
        key=lambda u: (1 if "x5secdata=" in u else 0, 1 if "capslide" in u.lower() else 0, len(u)),
        reverse=True,
    )[0]
    if "x5secdata=" not in best and len(best) < 80:
        return None
    return best


async def _page_has_captcha_ui(page) -> bool:
    if await detect_fruit_slider(page):
        return True
    try:
        n = await page.evaluate(
            """() => {
              const q = (s) => document.querySelectorAll(s).length;
              return (
                q('.scratch-captcha-container') +
                q('.scratch-captcha-slider .button') +
                q('[class*="scratch-captcha"]')
              );
            }"""
        )
        return bool(n)
    except Exception:  # noqa: BLE001
        return False


async def _trigger_risk(page, events: dict, payloads: list) -> None:
    async def maybe_goto_punish(text: str, src: str) -> bool:
        if payloads or await _page_has_captcha_ui(page):
            return True
        urls = _extract_punish_urls(text, page.url)
        if urls:
            events.setdefault("punish_urls", []).extend(urls)
        best = _best_punish(events.get("punish_urls") or urls)
        if not best:
            return False
        if "x5secdata=" in page.url and "punish" in page.url:
            return True
        log.info("goto punish (%s): %s", src, best[:180])
        try:
            await page.goto(best, wait_until="domcontentloaded", timeout=20000)
            events["followed_punish"] = best
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("goto punish failed: %s", exc)
            return False

    try:
        body = await asyncio.wait_for(
            page.evaluate(
                """async (path) => {
                  try {
                    const r = await fetch(path, {
                      credentials:'include',
                      headers:{'X-Requested-With':'XMLHttpRequest'}
                    });
                    const t = await r.text();
                    return {status:r.status, url:r.url, text:t.slice(0, 8000)};
                  } catch (e) {
                    return {error: String(e)};
                  }
                }""",
                AJAX_PATH,
            ),
            timeout=10.0,
        )
        if isinstance(body, dict) and body.get("text"):
            events["ajax_fetch"] = {
                "status": body.get("status"),
                "has_tmd": "_____tmd_____" in body["text"],
                "snippet": body["text"][:200],
            }
            await maybe_goto_punish(body["text"], "fetch")
    except Exception as exc:  # noqa: BLE001
        log.warning("ajax_fetch failed: %s", exc)

    if payloads or await _page_has_captcha_ui(page):
        return

    try:
        await asyncio.wait_for(
            page.evaluate(
                """async () => {
                  await fetch('/searchajax.html?keyword=a&cty=%E5%8C%97%E4%BA%AC&pageSize=2',
                    {credentials:'include'}).catch(()=>{});
                }"""
            ),
            timeout=8.0,
        )
    except Exception:  # noqa: BLE001
        pass


async def run(*, headed: bool, wall: float, strategy: str, step: float) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):
        if old.is_file() and old.suffix in {".png", ".jpg", ".json"}:
            # 保留历史样本，只清本轮主要输出
            if old.name in {
                "before.png",
                "after.png",
                "meta.json",
                "imageData.jpg",
                "ques.png",
            } or old.name.startswith("curve_round"):
                old.unlink()

    t0 = time.monotonic()
    meta: dict = {"headed": headed, "wall": wall, "strategy": strategy, "step": step}
    events: dict = {}
    network_hits: list[dict] = []
    payloads: list[CaptchaPayload] = []

    def left() -> float:
        return wall - (time.monotonic() - t0)

    cfg = load_config("configs/default.yaml")
    cfg.captcha.provider = "local_slider"
    cfg.captcha.fruit_strategy = strategy
    cfg.captcha.fruit_scan_step = step
    cfg.captcha.allow_manual = False
    cfg.browser.headless = not headed

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not headed,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        try:
            ctx = await browser.new_context(
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            await ctx.add_init_script(
                """
                Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
                window.chrome = window.chrome || { runtime: {} };
                Object.defineProperty(navigator,'languages',{get:()=>['zh-CN','zh','en']});
                Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
                (function () {
                  try {
                    let _pos = null, _info = null;
                    Object.defineProperty(document, '__update_pos', {
                      configurable: true, enumerable: true,
                      get() { return _pos; },
                      set(v) { _pos = v; try { window.__daxiUpdatePos = v; } catch (e) {} }
                    });
                    Object.defineProperty(document, '__update_info', {
                      configurable: true, enumerable: true,
                      get() { return _info; },
                      set(v) { _info = v; try { window.__daxiUpdateInfo = v; } catch (e) {} }
                    });
                  } catch (e) {}
                })();
                """
            )
            page = await ctx.new_page()
            page.set_default_timeout(6000)
            page.set_default_navigation_timeout(25000)

            async def on_response(response) -> None:
                try:
                    url = response.url
                    low = url.lower()
                    interesting = any(
                        k in low
                        for k in (
                            "_____tmd_____",
                            "punish",
                            "captcha",
                            "newslidecaptcha",
                            "newslidevalidate",
                            "searchajax",
                        )
                    )
                    if not interesting:
                        return
                    ct = (response.headers or {}).get("content-type", "")
                    item: dict = {"status": response.status, "url": url[:260], "ct": ct[:60]}
                    if any(x in ct for x in ("json", "text", "javascript", "html")):
                        try:
                            text = await asyncio.wait_for(response.text(), timeout=2.5)
                        except Exception:  # noqa: BLE001
                            text = ""
                        item["len"] = len(text or "")
                        item["imageData"] = "imageData" in (text or "")
                        item["encryptToken"] = "encryptToken" in (text or "")
                        if "newslidecaptcha" in low or item["imageData"] or "punish" in low:
                            for u in _extract_punish_urls(text or "", url):
                                events.setdefault("punish_urls", []).append(u)
                            if "_____tmd_____/punish" in url and "x5secdata=" in url:
                                events.setdefault("punish_urls", []).append(_normalize_url(url))
                            network_hits.append(item)
                            log.info("net %s", item)
                        if "newslidevalidate" in low:
                            log.info("VERIFY resp status=%s body=%s", response.status, (text or "")[:200])
                            events["verify"] = {"status": response.status, "body": (text or "")[:300]}
                except Exception:  # noqa: BLE001
                    return

            page.on("response", lambda r: asyncio.create_task(on_response(r)))
            detach_payload = await attach_payload_listener(page, payloads)

            log.info("[%.1fs] goto search", time.monotonic() - t0)
            try:
                await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=25000)
            except Exception as exc:  # noqa: BLE001
                log.warning("goto search: %s", exc)

            await page.wait_for_timeout(800)
            log.info("[%.1fs] trigger risk", time.monotonic() - t0)
            await _trigger_risk(page, events, payloads)

            if not payloads and not await _page_has_captcha_ui(page):
                best = _best_punish(events.get("punish_urls") or [])
                if best and "x5secdata=" not in page.url:
                    log.info("follow best punish: %s", best[:180])
                    try:
                        await page.goto(best, wait_until="domcontentloaded", timeout=20000)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("follow punish: %s", exc)

            wait_budget = max(4.0, min(28.0, left() - 45))
            log.info("[%.1fs] wait fruit UI %.1fs payloads=%s", time.monotonic() - t0, wait_budget, len(payloads))
            deadline = time.monotonic() + wait_budget
            while time.monotonic() < deadline:
                if await detect_fruit_slider(page) and await measure_geometry(page):
                    break
                if payloads and await measure_geometry(page):
                    break
                await page.wait_for_timeout(250)

            fruit = await _safe(detect_fruit_slider(page), "detect", False, 2.5)
            geo = await _safe(measure_geometry(page), "geo", None, 3.0)
            has_up = await _safe(_has_update_pos(page), "update_pos", False, 2.0)
            solver = DamaiCaptchaSolver(cfg)
            ch = await _safe(solver.detect(page), "solver_detect", None, 5.0)

            await _safe(page.screenshot(path=str(OUT / "before.png"), timeout=2500), "shot_before", timeout=3.0)
            if payloads and payloads[-1].image_data:
                (OUT / "imageData.jpg").write_bytes(payloads[-1].image_data)
            if payloads and payloads[-1].ques:
                (OUT / "ques.png").write_bytes(payloads[-1].ques)

            meta.update(
                {
                    "url_before": page.url,
                    "fruit_detected": bool(fruit),
                    "has_geometry": geo is not None,
                    "max_slide": getattr(geo, "max_slide", None),
                    "payloads": len(payloads),
                    "has_update_pos": bool(has_up),
                    "network_hits": network_hits[-12:],
                    "challenge": (
                        None
                        if ch is None
                        else {"kind": ch.kind.value, "reason": ch.reason, "meta": ch.meta}
                    ),
                }
            )
            log.info(
                "[%.1fs] fruit=%s geo=%s payloads=%s update_pos=%s max_slide=%s",
                time.monotonic() - t0,
                fruit,
                bool(geo),
                len(payloads),
                has_up,
                getattr(geo, "max_slide", None),
            )

            if not fruit and not geo:
                meta.update({"ok": False, "reason": "no_fruit_slider_ui", "elapsed": time.monotonic() - t0})
                (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                detach_payload()
                return meta

            async def cleared_ui() -> bool:
                if await detect_fruit_slider(page):
                    return False
                return await measure_geometry(page) is None

            solve_budget = max(25.0, min(left() - 8, 70.0))
            log.info(
                "[%.1fs] solve_fruit_slider strategy=%s budget=%.1fs step=%.1f",
                time.monotonic() - t0,
                strategy,
                solve_budget,
                step,
            )
            ok = await _safe(
                solve_fruit_slider(
                    page,
                    step=step,
                    success_check=cleared_ui,
                    max_rounds=2,
                    wait_timeout_s=8.0,
                    strategy=strategy,
                    provider=None,
                    payload_hint=payloads[-1] if payloads else None,
                ),
                "solve",
                False,
                solve_budget,
            )
            await page.wait_for_timeout(1000)
            still = await _safe(detect_fruit_slider(page), "still", None, 2.5)
            await _safe(page.screenshot(path=str(OUT / "after.png"), timeout=2500), "shot_after", timeout=3.0)

            meta.update(
                {
                    "ok": bool(ok) and not bool(still),
                    "solve_returned": bool(ok),
                    "still_fruit": still,
                    "url_after": page.url,
                    "payloads_final": len(payloads),
                    "verify": events.get("verify"),
                    "elapsed": time.monotonic() - t0,
                }
            )
            (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info(
                "RESULT ok=%s solve=%s still=%s update_pos=%s elapsed=%.1fs",
                meta["ok"],
                ok,
                still,
                has_up,
                meta["elapsed"],
            )
            detach_payload()
            return meta
        finally:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--strategy", default="local_only", choices=["local_only", "local_first"])
    ap.add_argument("--step", type=float, default=4.0)
    args = ap.parse_args()
    wall = max(45.0, args.seconds)

    async def _main() -> dict:
        return await run(headed=args.headed, wall=wall, strategy=args.strategy, step=args.step)

    try:
        meta = asyncio.run(asyncio.wait_for(_main(), timeout=wall + 15))
    except TimeoutError:
        print("RESULT timeout")
        raise SystemExit(2)
    except Exception as exc:  # noqa: BLE001
        print(f"RESULT error {type(exc).__name__}: {exc}")
        raise SystemExit(3)

    print(
        "RESULT",
        json.dumps(
            {
                k: meta.get(k)
                for k in (
                    "ok",
                    "solve_returned",
                    "still_fruit",
                    "fruit_detected",
                    "has_geometry",
                    "has_update_pos",
                    "max_slide",
                    "payloads",
                    "reason",
                    "elapsed",
                    "url_before",
                    "url_after",
                    "challenge",
                    "verify",
                )
            },
            ensure_ascii=False,
        ),
    )
    raise SystemExit(0 if meta.get("ok") else 1)


if __name__ == "__main__":
    main()
