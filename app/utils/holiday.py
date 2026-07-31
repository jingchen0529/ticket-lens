"""中国法定节假日判定 —— 对齐《北京市演出信息》模板「节假日」列。

底层用 `chinesecalendar`（按国务院放假通知人工维护，覆盖 2004~最近公布年份）。
模板该列的取值规则（据样本 6713 空 / 264 春节 / 106 上班 …）：

- 法定节假日当天 → 中文节名：元旦节 / 春节 / 清明节 / 劳动节 / 端午节 / 中秋节 / 国庆节
- 中秋与国庆连休（如 2025）→ 合并标「中秋国庆节」，与模板一致
- 调休补班日（周末但需上班）→「上班」
- 其余平常日 / 周末 → 空串
- 库未覆盖年份（如 2027+）或解析失败 → 空串兜底（不抛错）

元宵节属民俗节日、非法定假，库不产出；模板里仅 10 条人工标注，这里不处理。
"""

from __future__ import annotations

from datetime import date, datetime

# chinesecalendar 的英文节名 → 模板中文名
_HOLIDAY_ZH: dict[str, str] = {
    "New Year's Day": "元旦节",
    "Spring Festival": "春节",
    "Tomb-sweeping Day": "清明节",
    "Labour Day": "劳动节",
    "Dragon Boat Festival": "端午节",
    "Mid-autumn Festival": "中秋节",
    "National Day": "国庆节",
    # 历史特殊假（阅兵等），少见，直接给通用名避免报错
    "Anti-Fascist 70th Day": "抗战胜利日",
}


def _to_date(value: datetime | date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # API 层传入的是 JSON 里的 ISO 字符串（如 2026-10-01T20:00:00）
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def holiday_label(value: datetime | date | None) -> str:
    """返回某日期的节假日标签，规则见模块文档。无法判定时返回空串。"""
    d = _to_date(value)
    if d is None:
        return ""

    try:
        # 延迟导入：库缺失或环境异常时整体降级为空串，不影响导出
        from chinese_calendar import get_holiday_detail, is_workday
    except Exception:  # noqa: BLE001
        return ""

    try:
        on_holiday, name = get_holiday_detail(d)
    except NotImplementedError:
        # 库未覆盖该年份（如未公布放假通知的未来年份）
        return ""
    except Exception:  # noqa: BLE001
        return ""

    if on_holiday and name:
        zh = _HOLIDAY_ZH.get(name, "")
        if not zh:
            return ""
        # 中秋 / 国庆连休：同一放假区间内若两者都出现，合并为「中秋国庆节」
        if name in ("Mid-autumn Festival", "National Day") and _is_midautumn_national_merged(d):
            return "中秋国庆节"
        return zh

    # 非放假日：判断是否调休补班（周末但需上班）
    try:
        if d.weekday() >= 5 and is_workday(d):
            return "上班"
    except Exception:  # noqa: BLE001
        return ""
    return ""


def _is_midautumn_national_merged(d: date) -> bool:
    """判断 d 所在的连续放假区间里是否同时含中秋与国庆。

    2025 等年份中秋国庆连休，模板合并标注为「中秋国庆节」。
    从 d 出发向两侧沿"连续放假日"扩展（遇到非放假日即断开），
    只统计与 d 相连的这一段区间里的节名，避免跨越独立假期误并。
    """
    from datetime import timedelta

    try:
        from chinese_calendar import get_holiday_detail
    except Exception:  # noqa: BLE001
        return False

    def name_at(probe: date) -> str | None:
        try:
            on, name = get_holiday_detail(probe)
        except Exception:  # noqa: BLE001
            return None
        return name if on and name else None

    names: set[str] = set()
    base = name_at(d)
    if base:
        names.add(base)

    # 向前 / 向后沿连续放假日扩展，遇断点停止（连休一般 ≤ 8 天）
    for step in (-1, 1):
        for k in range(1, 9):
            nm = name_at(d + timedelta(days=step * k))
            if nm is None:
                break
            names.add(nm)

    return {"Mid-autumn Festival", "National Day"} <= names
