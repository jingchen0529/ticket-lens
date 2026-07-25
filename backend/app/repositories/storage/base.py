from __future__ import annotations

import abc
from pathlib import Path

from app.models import CrawlResult, RawShowItem, Show


class Storage(abc.ABC):
    @abc.abstractmethod
    def save_raw(self, items: list[RawShowItem]) -> Path:
        ...

    @abc.abstractmethod
    def save_shows(self, shows: list[Show]) -> Path:
        ...

    @abc.abstractmethod
    def save_result(self, result: CrawlResult) -> Path:
        ...

    @property
    @abc.abstractmethod
    def root(self) -> Path:
        ...
