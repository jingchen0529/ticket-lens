"""PyInstaller 打包入口。

打包后的可执行文件从这里启动，转交给 typer CLI。
这样 `daxi version` / `daxi serve` / `daxi crawl` 在打包后仍可用。
"""

from __future__ import annotations

from app.cli import main

if __name__ == "__main__":
    main()
