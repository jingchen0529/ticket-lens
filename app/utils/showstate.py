"""演出状态判定 —— 按演出时间与当前日期比较。

规则（据用户要求）：
- 演出时间在未来（今天之后）→「未演出」
- 演出时间是今天             →「演出中」
- 演出时间已过（今天之前）   →「已演出」
- 已取消（票务状态 cancelled）→「取消」（时间比较对已取消无意义）
- 无演出时间                 → 空串

判定按"日"粒度（只比较日期，不比较时分），与台账口径一致。
"""

from __future__ import annotations

from datetime import date, datetime


def _to_date(value: datetime | date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def performance_status(
    start_time: datetime | date | str | None,
    *,
    raw_status: str | None = None,
    today: date | None = None,
) -> str:
    """返回演出状态标签，规则见模块文档。无法判定时返回空串。"""
    if raw_status and str(raw_status).strip().lower() == "cancelled":
        return "取消"

    d = _to_date(start_time)
    if d is None:
        return ""

    ref = today or datetime.now().date()
    if d > ref:
        return "未演出"
    if d == ref:
        return "演出中"
    return "已演出"
