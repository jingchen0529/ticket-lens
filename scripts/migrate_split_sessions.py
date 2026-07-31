#!/usr/bin/env python3
"""把历史库中的“单行多场次”记录迁移为每场次一行。"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import orjson

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.core.config import load_config  # noqa: E402
from app.models import RawShowItem, Show  # noqa: E402
from app.pipeline.normalize import normalize_items, split_show_by_sessions  # noqa: E402
from app.repositories.storage.sqlite_store import SqliteStorage  # noqa: E402


def migrate(db_path: Path, *, apply: bool) -> tuple[int, int, Path | None]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT source, source_id, payload
            FROM shows
            WHERE json_array_length(json_extract(payload, '$.sessions')) > 1
            """
        ).fetchall()

        replacements: list[Show] = []
        for row in rows:
            raw_row = conn.execute(
                """
                SELECT payload FROM raw_items
                WHERE source = ? AND source_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (row["source"], row["source_id"]),
            ).fetchone()
            if raw_row is not None:
                raw = RawShowItem.model_validate(orjson.loads(raw_row["payload"]))
                replacements.extend(normalize_items([raw]))
            else:
                aggregate = Show.model_validate(orjson.loads(row["payload"]))
                replacements.extend(split_show_by_sessions(aggregate))

        if not apply or not rows:
            return len(rows), len(replacements), None

        backup = db_path.with_name(
            f"{db_path.name}.pre-session-split-{datetime.now():%Y%m%d-%H%M%S}.bak"
        )
        with sqlite3.connect(backup) as backup_conn:
            conn.backup(backup_conn)

    storage = SqliteStorage(db_path.parent, db_path=db_path)
    storage.save_shows(replacements)

    # save_shows 的 JSON 是“本批快照”；迁移后重建为完整库快照。
    with sqlite3.connect(db_path) as conn:
        payloads = [
            orjson.loads(row[0])
            for row in conn.execute("SELECT payload FROM shows ORDER BY start_time, id")
        ]
    (db_path.parent / "shows.json").write_bytes(
        orjson.dumps(payloads, option=orjson.OPT_INDENT_2)
    )
    return len(rows), len(replacements), backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写库；默认只预览")
    parser.add_argument("--db", type=Path, help="SQLite 路径，默认读取应用配置")
    args = parser.parse_args()

    db_path = args.db or Path(load_config().storage.db_path)
    aggregate_count, split_count, backup = migrate(db_path, apply=args.apply)
    mode = "已迁移" if args.apply else "待迁移"
    print(f"{mode}聚合项目 {aggregate_count} 个，拆分后 {split_count} 行")
    if backup is not None:
        print(f"备份: {backup}")


if __name__ == "__main__":
    main()
