"""统一日志配置。

CLI / 服务共用，基于 rich 输出彩色日志。
"""

from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler


def setup_logging(verbose: bool = False, console: Console | None = None) -> None:
    """初始化根日志。

    verbose=True 时输出 DEBUG，否则 INFO。可传入已有 Console 复用。
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_path=False,
            )
        ],
    )
