"""台账展示口径：统一维护入库行与台账可见行的分类差异。"""

from __future__ import annotations

from collections.abc import Iterable


LEDGER_HIDDEN_CATEGORIES: tuple[str, ...] = ("展览休闲", "体育")


def summarize_ledger_visibility(
    categories: Iterable[str | None],
) -> tuple[int, int, dict[str, int]]:
    """返回（台账可见数、隐藏数、按隐藏分类计数）。"""
    counts = {category: 0 for category in LEDGER_HIDDEN_CATEGORIES}
    total = 0
    for category in categories:
        total += 1
        if category in counts:
            counts[category] += 1
    hidden_by_category = {
        category: counts[category]
        for category in LEDGER_HIDDEN_CATEGORIES
        if counts[category]
    }
    hidden_count = sum(hidden_by_category.values())
    return total - hidden_count, hidden_count, hidden_by_category
