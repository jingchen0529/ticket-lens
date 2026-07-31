#!/usr/bin/env python3
"""大麦 searchajax 翻页探针（与 MCP 验证一致）。

用法（在项目根目录）:
  .venv/bin/python scripts/damai_search_paginate.py --start 1 --end 15 --headed
  .venv/bin/python scripts/damai_search_paginate.py --start 11 --end 30 --headed

逻辑：
1. 打开 search.htm 建会话
2. 同页 fetch searchajax.html?currPage=N
3. 若 FAIL_SYS_USER_VALIDATE，打开 punish 页等人工/自动过验证后重试当前页（不回第 1 页浪费额度）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.browser.session import BrowserSession  # noqa: E402
from app.core.config import load_config  # noqa: E402
from app.crawlers.damai.crawler import DamaiCrawler  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Damai searchajax pagination probe")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=10)
    ap.add_argument("--city", default="")
    ap.add_argument("--keyword", default="")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--out", default="data/damai_search_probe.json")
    args = ap.parse_args()

    cfg = load_config(ROOT / "configs" / "default.yaml")
    if args.headed:
        cfg.browser.headless = False

    session = BrowserSession(cfg)
    crawler = DamaiCrawler(session, cfg)
    items = []
    await session.start()
    try:
        async with session.page() as page:
            entry = crawler._build_search_url(args.city, args.keyword, 1)
            await crawler.goto(page, entry, wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)
            await crawler._maybe_solve_captcha(page)

            page_no = max(1, args.start)
            end = max(page_no, args.end)
            captcha_retries = 0
            while page_no <= end:
                payload = await crawler._fetch_search_ajax(
                    page, city=args.city, keyword=args.keyword, page_no=page_no
                )
                if crawler._is_user_validate(payload):
                    print(f"[block] page={page_no} ret={getattr(payload, 'get', lambda k: None)('ret') if isinstance(payload, dict) else payload}")
                    punish = crawler._punish_url(payload)
                    if captcha_retries >= 5:
                        print("[fail] captcha retries exhausted")
                        break
                    captcha_retries += 1
                    if punish:
                        await crawler.goto(page, punish, wait_until="domcontentloaded")
                    await crawler._maybe_solve_captcha(page)
                    if "punish" in (page.url or "") or "_____tmd_____" in (page.url or ""):
                        await crawler.goto(page, entry, wait_until="domcontentloaded")
                        await page.wait_for_timeout(600)
                    continue

                batch = crawler._parse_api_payload(
                    {"url": "searchajax", "data": payload}, city=args.city or "全国"
                )
                print(f"[ok] page={page_no} n={len(batch)}")
                if not batch:
                    break
                for it in batch:
                    items.append(
                        {
                            "page": page_no,
                            "source_id": it.source_id,
                            "title": it.title,
                            "city": it.city,
                            "venue": it.venue_name,
                            "showtime": it.start_time_raw,
                            "price": it.price_raw,
                            "status": it.status_raw,
                            "url": it.url,
                        }
                    )
                captcha_retries = 0
                page_no += 1
                await crawler._delay()
    finally:
        await session.stop()

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"count": len(items), "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"saved {len(items)} items -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
