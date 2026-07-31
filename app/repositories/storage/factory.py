from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import StorageConfig
from app.repositories.storage.base import Storage
from app.repositories.storage.json_store import JsonStorage, make_run_dir
from app.repositories.storage.sqlite_store import SqliteStorage


def create_storage(config: StorageConfig) -> Storage:
    backend = (config.backend or "json").lower()
    if backend == "sqlite":
        # run_subdir=false → 写固定本地库并 upsert 累积（供前端/API 查询）
        if not config.run_subdir:
            db_path = Path(config.db_path)
            # root 用固定库所在目录，方便同时落 shows.json / result.json 快照
            return SqliteStorage(db_path.parent, db_path=db_path)
        root = make_run_dir(config.output_dir, run_subdir=True)
        return SqliteStorage(root)
    if backend == "json":
        root = make_run_dir(config.output_dir, run_subdir=config.run_subdir)
        return JsonStorage(root)
    raise ValueError(f"unknown storage backend: {backend}")


def open_readonly_db(db_path: str | Path) -> sqlite3.Connection:
    """打开固定本地库的只读连接，供 API 查询用。"""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"数据库不存在，请先采集：{path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
