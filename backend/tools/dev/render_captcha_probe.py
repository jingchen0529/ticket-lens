#!/usr/bin/env python3
"""离线生成水果滑块对照图 + A/B 网格（0 点，不打码）。

用法（在 backend/ 下）:
  # 用 live 样本 + 已知 recognition
  python scripts/render_captcha_probe.py \\
      --image data/captcha_probe/bingtop_1358/live_imageData.jpg \\
      --ques  data/captcha_probe/bingtop_1358/live_ques.png \\
      --raw 191

  # 指定已拖 ui / validate code
  python scripts/render_captcha_probe.py \\
      --image ... --ques ... --raw 171 --ui 151 --code 300

产物默认写到 data/captcha_probe/bingtop_live/offline_*.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.browser.captcha.providers import map_bingtop_fruit_offset_to_ui  # noqa: E402
from app.crawlers.damai.fruit_probe import (  # noqa: E402
    default_ab_candidates,
    render_ab_grid,
    render_compare_image,
    write_probe_artifacts,
)
from app.crawlers.damai.fruit_slider import (  # noqa: E402
    FRUIT_PROTOCOL_EDGE_PX,
    CaptchaPayload,
    enrich_payload,
    estimate_offset_from_payload,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render captcha compare + A/B grid offline")
    ap.add_argument("--image", required=True, type=Path, help="imageData path")
    ap.add_argument("--ques", type=Path, default=None, help="ques path")
    ap.add_argument("--raw", type=float, required=True, help="bingtop recognition")
    ap.add_argument("--ui", type=float, default=None, help="override ui_x actually dragged")
    ap.add_argument("--max-slide", type=float, default=272.0)
    ap.add_argument("--logic-w", type=float, default=None, help="default=image width")
    ap.add_argument("--ui-width", type=float, default=320.0)
    ap.add_argument("--code", type=int, default=None, help="validate code if known")
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("data/captcha_probe/bingtop_live"),
        help="output directory",
    )
    ap.add_argument(
        "--no-write-bundle",
        action="store_true",
        help="only write compare/ab_grid png, skip history jsonl",
    )
    args = ap.parse_args()

    img = args.image.read_bytes()
    ques = args.ques.read_bytes() if args.ques and args.ques.exists() else None

    from PIL import Image
    from io import BytesIO

    with Image.open(BytesIO(img)) as im:
        logic_w = float(args.logic_w or im.size[0] or 320.0)

    ui_x = args.ui
    if ui_x is None:
        ui_x = map_bingtop_fruit_offset_to_ui(
            float(args.raw),
            max_slide=float(args.max_slide),
            image_width=logic_w,
            ui_width=float(args.ui_width),
            edge_pad=FRUIT_PROTOCOL_EDGE_PX,
            style="right_edge",
        )

    offline_ui = None
    target_name = ""
    try:
        pl = CaptchaPayload(
            encrypt_token="",
            image_data=img,
            ques=ques,
        )
        pl = enrich_payload(pl)
        target_name = pl.target_name or ""
        offline_ui = estimate_offset_from_payload(
            pl, max_slide=float(args.max_slide), image_logic_width=logic_w
        )
    except Exception as exc:  # noqa: BLE001
        print(f"offline prior skipped: {exc}")

    args.out.mkdir(parents=True, exist_ok=True)

    if args.no_write_bundle:
        display_raw = float(args.raw) * (float(args.ui_width) / max(logic_w, 1.0))
        cmp = render_compare_image(
            img,
            raw_off=display_raw,
            ui_x=float(ui_x),
            edge_pad=FRUIT_PROTOCOL_EDGE_PX,
            ques=ques,
            validate_code=args.code,
            target_name=target_name,
            title="offline",
        )
        cands = default_ab_candidates(
            float(args.raw),
            max_slide=float(args.max_slide),
            image_width=logic_w,
            ui_width=float(args.ui_width),
            edge_pad=FRUIT_PROTOCOL_EDGE_PX,
            offline_ui=offline_ui,
        )
        grid = render_ab_grid(
            img,
            cands,
            ques=ques,
            validate_code=args.code,
            raw_off=float(args.raw),
            title="offline A/B",
        )
        cmp_path = args.out / "offline_compare.png"
        grid_path = args.out / "offline_ab_grid.png"
        cmp_path.write_bytes(cmp)
        grid_path.write_bytes(grid)
        print(f"wrote {cmp_path}")
        print(f"wrote {grid_path}")
    else:
        meta = write_probe_artifacts(
            args.out,
            image_data=img,
            ques=ques,
            raw_off=float(args.raw),
            ui_x=float(ui_x),
            max_slide=float(args.max_slide),
            logic_w=logic_w,
            ui_width=float(args.ui_width),
            edge_pad=FRUIT_PROTOCOL_EDGE_PX,
            map_mode="fruit_right_edge",
            round_i=0,
            validate_code=args.code,
            target_name=target_name,
            offline_ui=offline_ui,
            img_key="offline",
        )
        print("wrote bundle:")
        for k, v in meta.paths.items():
            print(f"  {k}: {args.out / v}")
        print(f"  last_drag_compare.json: {args.out / 'last_drag_compare.json'}")
        print(f"  last_compare.png / last_ab_grid.png")

    print(
        f"raw={args.raw:.1f} ui_x={ui_x:.1f} reveal={ui_x + FRUIT_PROTOCOL_EDGE_PX:.1f} "
        f"offline={offline_ui} target={target_name!r} code={args.code}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
