#!/usr/bin/env python3
"""只跑通一步：newslidecaptcha 双图 → 冰拓 1358。

模式：
  --offline   用 data/captcha_probe/fruit_live/{imageData.jpg,ques.png} 直接调 1358（约 2 点）
  --live      打开大麦，刷高页触发验证，监听 newslidecaptcha，落盘后再调 1358（约 2 点）
  --dry-run   只抓/校验双图，不调用冰拓（0 点）

用法（在项目根目录）：
  python scripts/test_bingtop_1358_newslidecaptcha.py --offline
  python scripts/test_bingtop_1358_newslidecaptcha.py --live --headed
  python scripts/test_bingtop_1358_newslidecaptcha.py --live --dry-run --start-page 20

  # 或已 editable 安装后：
  #   pip install -e .
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# 允许未 pip install -e . 时直接 python scripts/...（把 backend 根加进 path）
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.browser.captcha.providers import (  # noqa: E402
    BingtopProvider,
    image_meta,
    is_valid_image_bytes,
    to_b64,
)
from app.core.config import load_config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("test_1358")

# 相对项目根，避免 cwd 不是仓库根时写飞
OUT = _ROOT / "data/captcha_probe/bingtop_1358"
# 优先 live 落盘；其次 fruit_live 历史样张
_OFFLINE_CANDIDATES = [
    (OUT / "live_imageData.jpg", OUT / "live_ques.png"),
    (_ROOT / "data/captcha_probe/fruit_live/imageData.jpg", _ROOT / "data/captcha_probe/fruit_live/ques.png"),
    (
        _ROOT / "data/captcha_probe/deep2/img_5__data_imageData.jpg",
        _ROOT / "data/captcha_probe/deep2/img_5__data_ques.png",
    ),
]


def _resolve_offline_pair() -> tuple[Path, Path]:
    for a, b in _OFFLINE_CANDIDATES:
        if a.is_file() and b.is_file():
            return a, b
    raise SystemExit(
        "缺少双图样张。请先跑: python scripts/test_bingtop_1358_newslidecaptcha.py --live --dry-run"
    )


def _provider(cfg) -> BingtopProvider:
    user = cfg.captcha.username or ""
    pwd = cfg.captcha.password or ""
    if not user or not pwd:
        raise SystemExit("缺少冰拓账号：configs/default.yaml captcha.username/password 或环境变量")
    return BingtopProvider(user, pwd, fruit_type=1358)


async def run_offline(*, dry_run: bool) -> dict:
    offline_img, offline_ques = _resolve_offline_pair()
    img = offline_img.read_bytes()
    ques = offline_ques.read_bytes()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "offline_imageData.jpg").write_bytes(img)
    (OUT / "offline_ques.png").write_bytes(ques)
    log.info("offline using %s + %s", offline_img, offline_ques)
    result = {
        "mode": "offline",
        "main": image_meta(img),
        "sub": image_meta(ques),
        "recognition": None,
        "offset": None,
    }
    log.info("offline images main=%s sub=%s", result["main"], result["sub"])
    if not is_valid_image_bytes(img) or not is_valid_image_bytes(ques, min_size=80):
        result["error"] = "invalid image samples"
        return result
    if dry_run:
        result["skipped"] = "dry-run"
        return result
    cfg = load_config()
    p = _provider(cfg)
    off = await p.solve_fruit_offset(to_b64(img), to_b64(ques))
    result["offset"] = off
    log.info("1358 recognition offset=%s", off)
    return result


async def run_live(*, headed: bool, dry_run: bool, start_page: int) -> dict:
    from playwright.async_api import async_playwright

    from app.crawlers.damai.fruit_slider import (
        CaptchaPayload,
        attach_payload_listener,
        detect_fruit_slider,
    )

    cfg = load_config()
    OUT.mkdir(parents=True, exist_ok=True)
    payloads: list[CaptchaPayload] = []
    result: dict = {
        "mode": "live",
        "url": None,
        "captured": False,
        "main": None,
        "sub": None,
        "has_token": False,
        "offset": None,
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()
        page.set_default_timeout(12000)
        detach = await attach_payload_listener(page, payloads)

        log.info("goto search.htm")
        try:
            await page.goto(
                "https://search.damai.cn/search.htm?order=1",
                wait_until="domcontentloaded",
                timeout=35000,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("goto: %s", exc)
        await page.wait_for_timeout(800)

        async def fetch_page(n: int) -> dict:
            return await page.evaluate(
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
                    catch (e) { return {status: r.status, text: t.slice(0, 300)}; }
                  } finally { clearTimeout(timer); }
                }""",
                n,
            )

        def is_blocked(j) -> tuple[bool, str | None]:
            if not isinstance(j, dict):
                return False, None
            ret = j.get("ret") or []
            if not isinstance(ret, list):
                ret = [ret]
            if any("USER_VALIDATE" in str(x) or "RGV587" in str(x) for x in ret):
                data = j.get("data") if isinstance(j.get("data"), dict) else {}
                return True, data.get("url")
            return False, None

        # 连续刷页触发风控
        for n in range(start_page, start_page + 25):
            if payloads:
                break
            log.info("fetch currPage=%s payloads=%s", n, len(payloads))
            try:
                resp = await asyncio.wait_for(fetch_page(n), timeout=18)
            except Exception as exc:  # noqa: BLE001
                log.warning("fetch err: %s", exc)
                resp = {"j": None}
            j = resp.get("j") if isinstance(resp, dict) else None
            blocked, pun = is_blocked(j)
            if blocked and pun:
                u = pun if not pun.startswith("//") else "https:" + pun
                u = u.replace("://search.damai.cn//", "://search.damai.cn/")
                log.info("punish → %s", u[:120])
                try:
                    await page.goto(u, wait_until="domcontentloaded", timeout=25000)
                except Exception as exc:  # noqa: BLE001
                    log.warning("goto punish: %s", exc)
            # 等 UI + 出题
            for _ in range(40):
                if payloads:
                    break
                if await detect_fruit_slider(page):
                    # UI 已出，再等网络
                    pass
                await page.wait_for_timeout(200)
            if payloads:
                break
            if await detect_fruit_slider(page):
                log.info("fruit UI without payload yet, wait…")
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and not payloads:
                    await page.wait_for_timeout(200)
                if payloads:
                    break

        result["url"] = page.url
        detach()

        if not payloads:
            log.error("未捕获到 newslidecaptcha（可能未触发风控或监听过晚）")
            result["error"] = "no_payload"
            await page.screenshot(path=str(OUT / "no_payload.png"), full_page=True)
            await browser.close()
            return result

        pl = payloads[-1]
        assert pl.image_data
        (OUT / "live_imageData.bin").write_bytes(pl.image_data)
        # 按魔数落扩展名
        img_path = OUT / (
            "live_imageData.jpg" if pl.image_data[:3] == b"\xff\xd8\xff" else "live_imageData.png"
        )
        img_path.write_bytes(pl.image_data)
        if pl.ques:
            ques_path = OUT / (
                "live_ques.png" if pl.ques[:4] == b"\x89PNG" else "live_ques.bin"
            )
            ques_path.write_bytes(pl.ques)
        result["captured"] = True
        result["has_token"] = bool(pl.encrypt_token)
        result["main"] = image_meta(pl.image_data)
        result["sub"] = image_meta(pl.ques)
        log.info(
            "captured has_token=%s main=%s sub=%s",
            result["has_token"],
            result["main"],
            result["sub"],
        )

        if not is_valid_image_bytes(pl.image_data) or not (
            pl.ques and is_valid_image_bytes(pl.ques, min_size=80)
        ):
            result["error"] = "invalid_dual_images"
            await browser.close()
            return result

        if dry_run:
            result["skipped"] = "dry-run"
            log.info("dry-run: 不调用冰拓，图片已保存到 %s", OUT)
            await browser.close()
            return result

        p = _provider(cfg)
        off = await p.solve_fruit_offset(to_b64(pl.image_data), to_b64(pl.ques or b""))
        result["offset"] = off
        log.info("1358 offset=%s", off)
        await browser.close()
        return result


async def main() -> None:
    ap = argparse.ArgumentParser(description="newslidecaptcha → 冰拓 1358 单步验证")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--offline", action="store_true", help="用本地样张打 1358")
    g.add_argument("--live", action="store_true", help="触发大麦验证并监听 newslidecaptcha")
    ap.add_argument("--dry-run", action="store_true", help="只落盘双图，不调冰拓")
    ap.add_argument("--headed", action="store_true", help="有头浏览器（live）")
    ap.add_argument("--start-page", type=int, default=16, help="live 起始 currPage")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if args.offline:
        result = await run_offline(dry_run=args.dry_run)
    else:
        result = await run_live(
            headed=args.headed,
            dry_run=args.dry_run,
            start_page=args.start_page,
        )

    out_json = OUT / "last_result.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("result → %s\n%s", out_json, json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("offset") is None and not result.get("skipped"):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
