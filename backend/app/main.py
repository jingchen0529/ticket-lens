"""本地 FastAPI 服务装配。

本地优先（local-first）：只监听 127.0.0.1，读本地固定 SQLite 库，
前端页面从这里取数据。不面向公网，无鉴权。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.routers import crawl, settings, shows

app = FastAPI(
    title="daxicrawler local API",
    description="本地演出数据查询与导出（local-first，仅监听 127.0.0.1）",
    version=__version__,
)

# 前端两种来源：
#   - 开发期 Vite dev server（5173），走代理
#   - Tauri 打包后 webview：origin 因平台而异
#       macOS/Linux → tauri://localhost
#       Windows     → http://tauri.localhost
# 仅本机使用，放开这几个固定 origin 即可，不面向公网。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
        "http://tauri.localhost",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(shows.router)
app.include_router(crawl.router)
app.include_router(settings.router)
