"""详情断点补跑入口。"""

from __future__ import annotations

import json

from app.models import RawShowItem, SourcePlatform
from app.repositories.storage.sqlite_store import SqliteStorage
from scripts.backfill_detail import load_pending_items


def _raw(item_id: str, detail: dict | None = None) -> RawShowItem:
    return RawShowItem(
        source=SourcePlatform.DAMAI,
        source_id=item_id,
        title=f"项目 {item_id}",
        raw_payload={"detail": detail} if detail is not None else {"from_api": True},
    )


def test_load_pending_items_reads_checkpoint_and_incomplete_raw_rows(tmp_path):
    db_path = tmp_path / "daxi.sqlite3"
    storage = SqliteStorage(tmp_path, db_path=db_path)
    storage.save_raw(
        [
            _raw("list-only"),
            _raw(
                "mobile-range",
                {
                    "detail_complete": True,
                    "detail_source": "damai_mobile_mtop",
                },
            ),
            _raw(
                "pc-complete",
                {
                    "detail_complete": True,
                    "detail_source": "damai_pc_subpage",
                },
            ),
        ]
    )
    checkpoint_item = _raw("checkpoint-first")
    checkpoint_path = tmp_path / "damai_detail_checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "state": "suspended",
                "pending_items": [checkpoint_item.model_dump(mode="json")],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    items, checkpoint_ids = load_pending_items(db_path, checkpoint_path)

    assert checkpoint_ids == {"checkpoint-first"}
    assert [item.source_id for item in items] == [
        "checkpoint-first",
        "mobile-range",
        "list-only",
    ]
    assert "pc-complete" not in {item.source_id for item in items}
