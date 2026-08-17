"""桌面壳对后端进程的生命周期监督。

Tauri 启动后端时会把子进程 stdin 连接到一条专用管道，并始终持有写端。
桌面应用正常退出、更新器直接终止进程或发生崩溃时，操作系统都会关闭写端；
后端读到 EOF 后通知 Uvicorn 优雅退出，从而不再留下占用 8756 的旧服务。
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import BinaryIO, Protocol

logger = logging.getLogger(__name__)


class _StoppableServer(Protocol):
    should_exit: bool


def start_parent_pipe_watchdog(
    server: _StoppableServer,
    stream: BinaryIO | None = None,
) -> threading.Thread:
    """后台等待父进程管道关闭，并请求 Uvicorn 退出。

    ``stream`` 仅用于测试；生产环境固定读取由 Tauri 管理的 stdin 管道。
    """

    parent_stream = stream or getattr(sys.stdin, "buffer", sys.stdin)

    def _watch() -> None:
        try:
            while parent_stream.read(1):
                # 监督管道正常不会传输数据；即使收到字节也只继续等待 EOF。
                pass
        except (OSError, ValueError):
            # 管道异常与 EOF 具有相同语义：父桌面进程已经无法继续监督后端。
            logger.warning("desktop supervisor pipe failed; shutting down backend")
        else:
            logger.info("desktop supervisor pipe closed; shutting down backend")
        finally:
            server.should_exit = True

    thread = threading.Thread(
        target=_watch,
        name="daxi-parent-watchdog",
        daemon=True,
    )
    thread.start()
    return thread
