#!/usr/bin/env python3
"""采集水果滑块实机 x→score 曲线（硬超时，不 OCR，避免卡死）。

用法:
  source .venv/bin/activate
  python scripts/probe_live_frames.py [--headed] [--seconds 45]

输出: data/captcha_probe/live_frames/{frames,samples.json,meta.json,imageData.jpg}
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import time
from pathlib import Path

from playwright.async_api import async_playwright

from app.crawlers.damai.fruit_slider import (
    CaptchaPayload,
    _screenshot_target,
    build_focus_boxes,
    detect_fruit_slider,
    drag_to_offset,
    find_best_offset_by_scores,
    measure_geometry,
    score_completeness,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("probe")

OUT = Path("data/captcha_probe/live_frames")
URL = (
    "https://search.damai.cn/search.htm?"
    "ctl=%E6%BC%94%E5%94%B1%E4%BC%9A&cty=%E5%8C%97%E4%BA%AC&order=1"
)


async def _safe(coro, name: str, default=None, timeout: float = 3.0):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        log.warning("%s: %s %s", name, type(exc).__name__, str(exc)[:100])
        return default


async def run(headed: bool, wall: float) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    for p in list(OUT.glob("frame_*.png")) + [OUT / "samples.json", OUT / "meta.json"]:
        if p.exists():
            p.unlink()

    t0 = time.monotonic()
    payloads: list[CaptchaPayload] = []
    payload_ev = asyncio.Event()
    samples: list[dict] = []
    meta: dict = {"headed": headed, "wall": wall}

    def left() -> float:
        return wall - (time.monotonic() - t0)

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
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page = await ctx.new_page()
            page.set_default_timeout(4000)
            page.set_default_navigation_timeout(15000)

            async def on_response(response) -> None:
                try:
                    if response.status != 200:
                        return
                    ct = (response.headers or {}).get("content-type", "")
                    if "json" not in ct and "text" not in ct:
                        return
                    # 短超时读 body，防止导航中卡住
                    text = await asyncio.wait_for(response.text(), timeout=2.5)
                    if "imageData" not in text or "encryptToken" not in text:
                        return
                    data = json.loads(text)
                    d = data.get("data") or {}
                    if not isinstance(d, dict):
                        return

                    def dec(v: object) -> bytes | None:
                        if not isinstance(v, str):
                            return None
                        s = v.split(",", 1)[1] if v.startswith("data:") else v
                        return base64.b64decode(s)

                    img = dec(d.get("imageData"))
                    ques = dec(d.get("ques"))
                    if not img:
                        return
                    payloads.append(
                        CaptchaPayload(
                            encrypt_token=str(d.get("encryptToken") or ""),
                            image_data=img,
                            ques=ques,
                        )
                    )
                    (OUT / "imageData.jpg").write_bytes(img)
                    if ques:
                        (OUT / "ques.png").write_bytes(ques)
                    log.info("payload#%s img=%s", len(payloads), len(img))
                    payload_ev.set()
                except Exception:  # noqa: BLE001
                    return

            page.on("response", lambda r: asyncio.create_task(on_response(r)))

            log.info("[%.1fs] goto", time.monotonic() - t0)
            try:
                await page.goto(URL, wait_until="domcontentloaded", timeout=15000)
            except Exception as exc:  # noqa: BLE001
                log.warning("goto: %s", exc)

            # 轻量触发 + 等 payload / UI（不在循环里 evaluate 多次以免卡死）
            try:
                await asyncio.wait_for(
                    page.evaluate(
                        "fetch('/searchajax.html?keyword=演唱会&cty=北京&pageSize=5',"
                        "{credentials:'include'}).catch(()=>{})"
                    ),
                    timeout=3.0,
                )
            except Exception:  # noqa: BLE001
                pass

            # 等 payload 或 fruit UI，最多 min(12, left-15)
            wait_budget = max(2.0, min(12.0, left() - 15))
            deadline = time.monotonic() + wait_budget
            while time.monotonic() < deadline and left() > 15:
                if payload_ev.is_set() or await detect_fruit_slider(page):
                    break
                await page.wait_for_timeout(200)

            log.info(
                "[%.1fs] payloads=%s fruit=%s url=%s",
                time.monotonic() - t0,
                len(payloads),
                await _safe(detect_fruit_slider(page), "det", False, 1.5),
                page.url[:100],
            )

            await _safe(
                page.screenshot(path=str(OUT / "before.png"), timeout=2000),
                "before",
                timeout=2.5,
            )

            focus = None
            if payloads and payloads[-1].image_data:
                # 无 OCR：用最大若干 blob 作弱聚焦
                focus = build_focus_boxes(payloads[-1].image_data, None, 4)
                log.info("focus_boxes=%s", len(focus or []))

            # 再等按钮可点
            for _ in range(20):
                if left() < 12:
                    break
                geo = await _safe(measure_geometry(page), "geo", timeout=2.0)
                if geo is not None:
                    break
                await page.wait_for_timeout(250)
            else:
                geo = await _safe(measure_geometry(page), "geo2", timeout=2.0)

            if geo is None:
                info = await _safe(
                    page.evaluate(
                        """() => ({
                          u: location.href.slice(0,140),
                          btn: document.querySelectorAll('.scratch-captcha-slider .button').length,
                          box: document.querySelectorAll('.scratch-captcha-container').length,
                          scratch: !!document.querySelector('[class*=scratch]'),
                          ifr: [...document.querySelectorAll('iframe')].map(f=>f.src).slice(0,4)
                        })"""
                    ),
                    "dom",
                    {},
                    2.0,
                )
                meta.update(
                    {
                        "payloads": len(payloads),
                        "samples": 0,
                        "dom": info,
                        "url": page.url,
                        "elapsed": time.monotonic() - t0,
                    }
                )
                (OUT / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                log.warning("no geometry; dom=%s", info)
                return meta

            log.info("max_slide=%.1f ibox=%s", geo.max_slide, geo.image_box)
            box = await geo.button.bounding_box() or geo.button_box
            sx = box["x"] + box["width"] / 2
            sy = box["y"] + box["height"] / 2
            await page.mouse.move(sx, sy)
            await page.mouse.down()

            x, idx, step = 0.0, 0, 8.0
            while x <= geo.max_slide + 0.1 and idx < 36 and left() > 8:
                await page.mouse.move(sx + x, sy)
                await page.wait_for_timeout(35)
                png = await _safe(_screenshot_target(geo, page), f"shot{idx}", timeout=1.8)
                if png:
                    sc = score_completeness(png, focus_boxes=focus)
                    samples.append({"x": round(x, 1), "score": round(sc, 2)})
                    (OUT / f"frame_{idx:03d}_x{int(x)}.png").write_bytes(png)
                    log.info("x=%5.1f score=%7.1f", x, sc)
                x += step
                idx += 1

            try:
                await page.mouse.up()
            except Exception:  # noqa: BLE001
                pass

            (OUT / "samples.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")
            best = None
            if samples:
                best = find_best_offset_by_scores([(s["x"], s["score"]) for s in samples])
                log.info("BEST x=%.1f min=%.1f", best, min(s["score"] for s in samples))
                geo2 = await _safe(measure_geometry(page), "geo3", timeout=2.0) or geo
                await _safe(drag_to_offset(page, geo2, best, release=True), "drag", timeout=8.0)
                await page.wait_for_timeout(1200)
                await _safe(
                    page.screenshot(path=str(OUT / "after.png"), timeout=2000),
                    "after",
                    timeout=2.5,
                )
                still = await _safe(detect_fruit_slider(page), "still", None, 1.5)
                meta["still"] = still
                log.info("still_fruit=%s", still)

            meta.update(
                {
                    "payloads": len(payloads),
                    "samples": len(samples),
                    "best": best,
                    "curve": samples,
                    "url": page.url,
                    "elapsed": time.monotonic() - t0,
                }
            )
            (OUT / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return meta
        finally:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="有头模式")
    ap.add_argument("--seconds", type=float, default=45.0, help="墙钟超时秒数")
    args = ap.parse_args()
    wall = max(20.0, args.seconds)

    async def _main() -> None:
        meta = await run(headed=args.headed, wall=wall)
        print("RESULT", json.dumps({k: meta.get(k) for k in (
            "samples", "best", "payloads", "still", "elapsed", "url"
        )}, ensure_ascii=False))

    try:
        asyncio.run(asyncio.wait_for(_main(), timeout=wall + 8))
    except TimeoutError:
        print("RESULT timeout")
    except Exception as exc:  # noqa: BLE001
        print(f"RESULT error {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
