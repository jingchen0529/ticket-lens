"""统一日志配置。

CLI / 服务共用：终端（rich 彩色）+ 落盘文件双通道。

- 终端：开发者本地排障。
- 文件：`data_dir()/logs/server.log`。Windows 打包版后端控制台被 Tauri
  用 CREATE_NO_WINDOW 抑制，任务日志里「详细原因已记录在服务端日志」指的
  就是这份文件——客户机器出问题时把 server.log 发回来即可定位。
"""

from __future__ import annotations

import logging
import logging.handlers
import os

from rich.console import Console
from rich.logging import RichHandler

_FILE_LOG_NAME = "server.log"
_FILE_LOG_MAX_BYTES = 5 * 1024 * 1024
_FILE_LOG_BACKUPS = 3


def _attach_file_handler(root: logging.Logger) -> logging.Handler | None:
    """把落盘日志挂到根 logger；同一路径只挂一次（幂等）。"""
    from app.core.paths import data_dir

    try:
        log_dir = data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 数据目录不可写（异常环境）时不落盘，不阻塞启动。
        return None

    target = str(log_dir / _FILE_LOG_NAME)
    for existing in root.handlers:
        if (
            isinstance(existing, logging.handlers.RotatingFileHandler)
            and getattr(existing, "baseFilename", "") == target
        ):
            return existing

    handler = logging.handlers.RotatingFileHandler(
        target,
        maxBytes=_FILE_LOG_MAX_BYTES,
        backupCount=_FILE_LOG_BACKUPS,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)
    return handler


def setup_logging(verbose: bool = False, console: Console | None = None) -> None:
    """初始化根日志：rich 控制台（终端可见）+ 落盘文件（排障用）。

    verbose=True 时输出 DEBUG，否则 INFO。可传入已有 Console 复用。
    重复调用安全：处理器按类型/路径去重，不会叠加。
    """
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    _attach_file_handler(root)
    if not any(isinstance(h, RichHandler) for h in root.handlers):
        root.addHandler(
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_path=False,
            )
        )
