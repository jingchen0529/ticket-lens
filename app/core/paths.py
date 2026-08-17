r"""统一路径解析：兼顾源码运行与 PyInstaller 打包、跨 macOS / Windows。

三类路径需要分开处理，否则打包后 CWD 不可控会全线出错：

1. **只读资源**（配置模板等）：源码运行在项目里，打包后在 `sys._MEIPASS` 内。
2. **可执行文件所在目录**：打包后 App 的落脚点。数据默认放它旁边。
3. **用户数据目录**（DB / cookie / 导出）：优先"App 同级 data/"，
   不可写时回退到系统用户目录（Windows `%LOCALAPPDATA%`，macOS
   `~/Library/Application Support`）。App 目录在 Windows 装到
   `C:\Program Files` 时只读，直接写会崩，必须能回退。

所有路径用 pathlib，不写死分隔符，保证 Mac 开发 / Windows 交付一致。
"""

from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

APP_NAME = "daxi"

# 允许运维/客户显式指定数据目录，优先级最高
_ENV_DATA_DIR = "DAXI_DATA_DIR"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 冻结环境。"""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """只读资源根目录（打包内 configs 等随包资源）。

    - 打包后：PyInstaller 解包临时目录 `sys._MEIPASS`。
    - 源码运行：项目根目录（本文件的上上级）。
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    # app/core/paths.py → 上溯到项目根目录
    return Path(__file__).resolve().parents[2]


def executable_dir() -> Path:
    """可执行文件所在目录。

    - 打包后：真实 exe 所在目录（不是 _MEIPASS 临时解包目录）。
    - 源码运行：项目根目录，便于本地开发数据仍落在项目内。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _system_user_data_dir() -> Path:
    """系统规范的用户数据目录（回退用）。"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Local" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    # Linux / 其他
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_NAME


def _is_writable(directory: Path) -> bool:
    """目录可创建且可写才返回 True（探测式，避免 Program Files 只读崩溃）。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".daxi_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _migrate_legacy_data(legacy: Path, target: Path) -> None:
    """把旧安装目录数据合并到用户目录，但绝不覆盖用户目录中的现有文件。

    Windows 历史版本以管理员权限运行时，数据可能写在 Program Files 下的
    ``backend/data``。新版降为普通权限后必须在首次启动时把这些数据带到
    LOCALAPPDATA，否则数据库和 Cookie 会看起来像是“消失”了。macOS 旧版
    App 包内数据也复用同一迁移规则。
    """
    try:
        if not legacy.is_dir():
            return
        target.mkdir(parents=True, exist_ok=True)

        def copy_missing(source: Path, destination: Path) -> None:
            try:
                if source.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    for child in source.iterdir():
                        copy_missing(child, destination / child.name)
                elif not destination.exists():
                    shutil.copy2(source, destination)
            except OSError:
                # 单个损坏/不可读文件不应阻断其他数据库、Cookie 或配置迁移。
                return

        for source in legacy.iterdir():
            copy_missing(source, target / source.name)
    except OSError:
        # 迁移失败不阻止启动，后续仍使用可写的系统用户数据目录。
        return


@lru_cache(maxsize=1)
def data_dir() -> Path:
    """用户数据目录（DB / cookie / 导出落这里）。

    优先级：
      1. 环境变量 DAXI_DATA_DIR（客户/设置页显式指定）
      2. 可执行文件同级 data/（客户装 D 盘时数据就在 App 旁，直观好找）
      3. 系统用户数据目录（App 装在 Program Files 等只读位置时回退）
    """
    env = os.environ.get(_ENV_DATA_DIR)
    if env:
        d = Path(env).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        return d

    if is_frozen():
        if sys.platform == "darwin":
            target = _system_user_data_dir()
            _migrate_legacy_data(executable_dir() / "data", target)
            target.mkdir(parents=True, exist_ok=True)
            return target

        beside_app = executable_dir() / "data"
        if _is_writable(beside_app):
            return beside_app
        fallback = _system_user_data_dir()
        if sys.platform == "win32":
            _migrate_legacy_data(beside_app, fallback)
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    # 源码运行：保持项目内 data/，与既有开发习惯一致
    d = executable_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    """配置文件路径。

    优先用户数据目录下的 configs/default.yaml（客户可改），
    不存在时回退随包只读模板。首次运行时把模板落到数据目录，方便客户编辑。
    """
    user_cfg = data_dir() / "configs" / "default.yaml"
    if user_cfg.exists():
        return user_cfg

    bundled = resource_dir() / "configs" / "default.yaml"
    if is_frozen() and bundled.exists():
        # 首次运行：把随包模板复制到用户目录，之后客户改的是这份
        try:
            user_cfg.parent.mkdir(parents=True, exist_ok=True)
            user_cfg.write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")
            return user_cfg
        except OSError:
            return bundled
    return bundled


def db_path() -> Path:
    """固定 SQLite 库路径。"""
    return data_dir() / "daxi.sqlite3"


def cookie_dir() -> Path:
    """cookie 存储目录。"""
    d = data_dir() / "cookies"
    return d


# Playwright 浏览器环境变量：设了它，Playwright 就去这个目录找
# chromium-xxxx/，而不是用户默认缓存目录。
_PW_ENV = "PLAYWRIGHT_BROWSERS_PATH"


def bundled_browsers_dir() -> Optional[Path]:
    """随包 Chromium 目录（若存在）。

    优先检查 pw-browsers/chromium-*/chrome-mac-arm64/（本地 dev 结构）
    其次检查打包后的 ms-playwright/。
    """
    candidates = []

    # 1. pw-browsers（本地结构） - 无论 frozen 都尝试
    pw_dir = Path(__file__).parent.parent / "pw-browsers"
    if pw_dir.is_dir():
        for subdir in pw_dir.iterdir():
            if subdir.is_dir() and "chromium" in subdir.name:
                chrome_dir = subdir / "chrome-mac-arm64"
                if chrome_dir.is_dir():
                    candidates.append(chrome_dir)

    # 2. 打包后的 ms-playwright
    exe_dir = executable_dir()
    candidate = exe_dir / "ms-playwright"
    if candidate.is_dir():
        candidates.append(candidate)

    if candidates:
        # 返回第一个可用的
        return candidates[0]
    return None


def setup_browser_env() -> None:
    """在启动浏览器前调用：把 PLAYWRIGHT_BROWSERS_PATH 指向随包 Chromium。

    - 已由外部显式设置该环境变量时不覆盖（便于调试指向系统 Chromium）。
    - 无论 frozen 与否，都优先用 pw-browsers 目录。
    """
    if os.environ.get(_PW_ENV):
        return
    bundled = bundled_browsers_dir()
    if bundled is not None:
        os.environ[_PW_ENV] = str(bundled)
    else:
        # 作为 fallback，尝试直接在 pw-browsers 根目录下找
        pw_root = Path(__file__).parent.parent / "pw-browsers"
        if pw_root.is_dir():
            os.environ[_PW_ENV] = str(pw_root)
