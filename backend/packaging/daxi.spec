# -*- mode: python ; coding: utf-8 -*-
"""最小打包 spec（阶段零验证）。

目标：确认 PyInstaller 能正确收集 Playwright + FastAPI + uvicorn + app 包。
此阶段【不】打包 Chromium，仅验证后端能否被打包并启动。
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH 是 PyInstaller 注入的变量，指向本 spec 文件所在目录（packaging/）。
# backend 根目录是它的上一级。所有数据/入口都用绝对路径，避免相对 CWD 出错。
BACKEND_DIR = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = []
binaries = []
hiddenimports = []

# Playwright：驱动 node 二进制 + package.json 等数据文件
for pkg in ("playwright",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# uvicorn / fastapi 动态加载的子模块
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("app")

# 应用配置文件（打包进内部；运行时路径处理后续再做）
datas += [(os.path.join(BACKEND_DIR, "configs"), "configs")]

block_cipher = None

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[BACKEND_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="daxi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="daxi",
)
