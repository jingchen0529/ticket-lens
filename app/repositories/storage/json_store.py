"""JSON 文件存储。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import orjson

from app.models import CrawlResult, RawShowItem, Show
from app.pipeline.normalize import split_show_by_sessions
from app.repositories.storage.base import Storage


def _dump(obj: object) -> bytes:
    return orjson.dumps(obj, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE)


class JsonStorage(Storage):
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def save_raw(self, items: list[RawShowItem]) -> Path:
        path = self._root / "raw_items.json"
        data = [i.model_dump(mode="json") for i in items]
        path.write_bytes(_dump(data))
        return path

    def save_shows(self, shows: list[Show]) -> Path:
        path = self._root / "shows.json"
        split_shows = [
            part
            for show in shows
            for part in (
                split_show_by_sessions(show) if len(show.sessions) > 1 else [show]
            )
        ]
        data = [s.model_dump(mode="json") for s in split_shows]
        path.write_bytes(_dump(data))
        return path

    def save_result(self, result: CrawlResult) -> Path:
        path = self._root / "result.json"
        path.write_bytes(_dump(result.model_dump(mode="json")))
        return path


def make_run_dir(base: str | Path, run_subdir: bool = True) -> Path:
    root = Path(base)
    if run_subdir:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = root / "runs" / stamp
    root.mkdir(parents=True, exist_ok=True)
    return root
