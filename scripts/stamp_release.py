"""把同一发布身份写入 Tauri 配置与 PyInstaller 后端源码。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def stamp_release(
    *,
    version: str,
    build_id: str,
    updater_url: str,
    config_path: Path,
    build_info_path: Path,
) -> None:
    """原子发布所需的两个身份来源必须在后端打包前一起更新。"""
    if not _SEMVER_RE.fullmatch(version):
        raise ValueError(f"非法发布版本: {version!r}")
    if not build_id.strip():
        raise ValueError("后端 build_id 不能为空")
    parsed_url = urlparse(updater_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise ValueError("updater URL 必须是完整 HTTPS 地址")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    endpoints = config.get("plugins", {}).get("updater", {}).get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise ValueError("tauri.conf.json 缺少 updater endpoints")

    config["version"] = version
    config["plugins"]["updater"]["endpoints"] = [updater_url, *endpoints[1:]]
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    build_info_path.write_text(
        '"""由发布流水线生成；不要在构建产物中手工修改。"""\n\n'
        f"BACKEND_VERSION = {version!r}\n"
        f"BACKEND_BUILD_ID = {build_id!r}\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--updater-url", required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("web/src-tauri/tauri.conf.json"),
    )
    parser.add_argument("--build-info", type=Path, default=Path("app/build_info.py"))
    args = parser.parse_args()
    stamp_release(
        version=args.version,
        build_id=args.build_id,
        updater_url=args.updater_url,
        config_path=args.config,
        build_info_path=args.build_info,
    )


if __name__ == "__main__":
    main()
