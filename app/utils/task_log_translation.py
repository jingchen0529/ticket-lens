"""客户可见任务日志的中文转换。

服务端技术日志保留原始内容；任务 API 只返回这里产生的客户可读文本。
已知结构化日志会保留项目编号、页码、HTTP 状态等排障信息；未知英文
技术日志转为中文摘要，避免将第三方库的英文异常直接抛给客户。
"""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_ENGLISH_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z_-]{2,}\b")

_PLATFORM_NAMES = {
    "damai": "大麦网",
    "maoyan": "猫眼",
    "showstart": "秀动",
}


def _platform(value: str) -> str:
    raw = str(value or "").strip().lower()
    return _PLATFORM_NAMES.get(raw, "其他采集平台")


def _value(value: str, default: str = "无") -> str:
    cleaned = str(value or "").strip()
    if cleaned in {"", "''", '""', "None", "none", "null", "-"}:
        return default
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "'\"":
        cleaned = cleaned[1:-1]
    return cleaned or default


def _yes_no(value: str) -> str:
    return "是" if str(value).strip().lower() in {"1", "true", "yes", "on"} else "否"


def _detail_label(value: str) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower()
    if lowered == "base":
        return "基础信息"
    if lowered.startswith("calendar:"):
        return f"日期 {raw.split(':', 1)[1]}"
    if lowered.startswith("perform:"):
        return f"场次 {raw.split(':', 1)[1]}"
    return "详情子项"


def _module_name(logger_name: str, text: str) -> str:
    blob = f"{logger_name} {text}".lower()
    if "captcha" in blob or "slider" in blob or "fruit" in blob or "bingtop" in blob:
        return "验证码模块"
    if "damai" in blob:
        return "大麦网采集"
    if "maoyan" in blob:
        return "猫眼采集"
    if "browser" in blob or "playwright" in blob:
        return "浏览器模块"
    if "storage" in blob or "sqlite" in blob:
        return "数据存储"
    if "normalize" in blob or "pipeline" in blob:
        return "数据整理"
    return "采集引擎"


def _technical_context(text: str) -> str:
    """从未知英文日志中只保留客户能用于排障的结构化字段。"""
    fields: list[str] = []
    specs = (
        (r"\b(?:item|item_id|source_id)=([^\s,:]+)", "项目编号"),
        (r"\bpage=([^\s,:]+)", "页码"),
        (r"\bround=([^\s,:()]+)", "轮次"),
        (r"\battempt(?:s)?=([^\s,:]+)", "尝试次数"),
        (r"\b(?:status|http)=([^\s,:]+)", "网络状态码"),
        (r"\bcode=([^\s,:]+)", "状态码"),
        (r"\bcity=([^\s,:]+)", "城市"),
    )
    for pattern, label in specs:
        match = re.search(pattern, text, re.I)
        if match:
            part = f"{label}：{_value(match.group(1))}"
            if part not in fields:
                fields.append(part)
    return f"（{'，'.join(fields)}）" if fields else ""


def _translate_mixed_chinese(text: str) -> str:
    """已有中文的异常只翻译其中的技术字段名。"""
    result = str(text).strip()
    result = re.sub(r"^damai\s*:\s*", "大麦网：", result, flags=re.I)
    result = re.sub(r"^maoyan\s*:\s*", "猫眼：", result, flags=re.I)
    result = re.sub(r"^\[damai\]\s*", "【大麦网】", result, flags=re.I)
    result = re.sub(r"^\[maoyan\]\s*", "【猫眼】", result, flags=re.I)
    replacements = (
        (r"\bsource_id=", "来源项目编号："),
        (r"\bitem=", "项目编号："),
        (r"\bperformId=", "场次编号："),
        (r"\bperformId\b", "场次编号"),
        (r"\bperform=", "场次编号："),
        (r"\battempts=", "尝试次数："),
        (r"\bdates=", "日期完整度："),
        (r"\bdate=", "日期："),
        (r"\burl=", "地址："),
        (r"\bskuList\b", "票档列表"),
        (r"\bHTTP\b", "网络状态码"),
        (r"\bJSON\b", "数据格式"),
        (r"\bCookie(?:s)?\b", "登录凭据"),
        (r"\bURL\b", "地址"),
        (r"\bheadless\b", "无界面模式"),
        (r"--headed\b", "有界面模式"),
        (r"\bTrue\b", "是"),
        (r"\bFalse\b", "否"),
        (r"\bNone\b", "无"),
    )
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.I)
    return result


def _excerpt(text: str, limit: int = 160) -> str:
    """取单行摘要并做常见词翻译，超长截断。用于把真实异常透传给客户。"""
    first = (str(text or "").strip().splitlines() or [""])[0].strip()
    if not first:
        return ""
    first = re.sub(r"\s+", " ", first)
    first = _translate_mixed_chinese(first)
    if len(first) > limit:
        first = first[: limit - 3] + "..."
    return first


def translate_task_error(text: str, *, logger_name: str = "") -> str:
    """把任务 error / result.errors 转为客户可读中文。"""
    raw = str(text or "").strip()
    if not raw:
        return "未知采集异常"

    platform_match = re.fullmatch(r"(damai|maoyan|showstart)\s*:\s*(.*)", raw, re.I)
    if platform_match:
        platform_name = _platform(platform_match.group(1))
        detail = translate_task_error(platform_match.group(2), logger_name=logger_name)
        if detail.startswith(platform_name):
            return detail
        return f"{platform_name}：{detail}"

    patterns = (
        (
            r"damai captcha solver failed city=(.*?) keyword=(.*?) page=(\d+)",
            lambda m: (
                f"大麦网验证码自动处理失败（城市：{_value(m[1])}，"
                f"关键词：{_value(m[2])}，第 {m[3]} 页）"
            ),
        ),
        (
            r"damai captcha retries exhausted city=(.*?) keyword=(.*?) page=(\d+)",
            lambda m: (
                f"大麦网验证码重试次数已耗尽（城市：{_value(m[1])}，"
                f"关键词：{_value(m[2])}，第 {m[3]} 页）"
            ),
        ),
        (
            r"damai searchajax failed city=(.*?) keyword=(.*?) page=(\d+):.*",
            lambda m: (
                f"大麦网列表接口请求失败（城市：{_value(m[1])}，"
                f"关键词：{_value(m[2])}，第 {m[3]} 页）"
            ),
        ),
        (
            r"damai .*failed city=(.*?) keyword=(.*?) page=(\d+)(?::.*)?",
            lambda m: (
                f"大麦网采集失败（城市：{_value(m[1])}，"
                f"关键词：{_value(m[2])}，第 {m[3]} 页）"
            ),
        ),
        (
            r"executable doesn't exist at (.*)",
            lambda m: (
                f"浏览器组件缺失：未找到 {m[1]}，请重新安装或升级到最新版"
            ),
        ),
        (
            r"(?:target page, context or browser has been closed|browser closed "
            r"unexpectedly|process exited with code \S+|renderer process crashed"
            r"|connection refused).*",
            lambda m: "浏览器进程异常退出（可能被安全软件拦截或系统资源不足），请重试",
        ),
    )
    for pattern, renderer in patterns:
        match = re.fullmatch(pattern, raw, re.I | re.S)
        if match:
            return renderer(match)

    if _CJK_RE.search(raw):
        translated = _translate_mixed_chinese(raw)
        if not _ENGLISH_WORD_RE.search(translated):
            return translated

    module = _module_name(logger_name, raw)
    return (
        f"{module}发生异常，详细原因已记录在服务端日志"
        f"{_technical_context(raw)}"
    )


def translate_task_log(
    text: str,
    *,
    level: str = "INFO",
    logger_name: str = "",
) -> str:
    """把一条引擎日志转为客户可读中文。"""
    raw = str(text or "").strip()
    if not raw:
        return ""

    match = re.fullmatch(
        r"browser started headless=(\S+) proxy=(\S+)", raw, re.I
    )
    if match:
        mode = "无界面" if _yes_no(match[1]) == "是" else "有界面"
        return f"自动化采集浏览器已启动（{mode}，代理：{_yes_no(match[2])}）"
    if re.fullmatch(r"browser (?:cleanup complete|stopped)", raw, re.I):
        return "自动化采集浏览器资源已清理"
    match = re.fullmatch(r"loaded cookies for (\w+) from (.*)", raw, re.I)
    if match:
        return f"已加载{_platform(match[1])}登录凭据"
    if re.fullmatch(r"saved storage_state(?:\s+→\s+.*)?", raw, re.I):
        return "平台登录凭据已安全保存"

    match = re.fullmatch(
        r"source (\w+) item=(\S+) persisted sessions=(\d+) rows=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"{_platform(match[1])}项目已入库：项目编号 {match[2]}，"
            f"场次 {match[3]} 个，数据 {match[4]} 条"
        )
    match = re.fullmatch(
        r"source (\w+) list checkpoint persisted projects=(\d+)", raw, re.I
    )
    if match:
        return (
            f"{_platform(match[1])}列表已保存断点：项目 {match[2]} 个，"
            "详情中断后可重新补跑"
        )
    match = re.fullmatch(r"source (\w+) raw=(\d+)", raw, re.I)
    if match:
        return f"{_platform(match[1])}原始数据采集完成：{match[2]} 条"
    if raw.lower().startswith("crawler failed:"):
        reason = raw.split(":", 1)[1].strip()
        return f"平台采集失败：{translate_task_error(reason, logger_name=logger_name)}"

    # 浏览器会话启动失败：把真实异常摘要直接透传给客户（完整堆栈在 server.log）
    match = re.fullmatch(r"browser session startup failed: (.*)", raw, re.I | re.S)
    if match:
        return f"采集浏览器启动失败：{_excerpt(match[1])}"

    match = re.fullmatch(
        r"crawl finished raw=(\d+) shows=(\d+) ledger_visible=(\d+) "
        r"ledger_hidden=(\d+) out=.* errors=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"采集统计：原始 {match[1]} 条，入库 {match[2]} 条，"
            f"台账可见 {match[3]} 条，隐藏展览休闲/体育 {match[4]} 条，"
            f"异常 {match[5]} 条"
        )
    match = re.fullmatch(
        r"crawl finished raw=(\d+) shows=(\d+) out=.* errors=(\d+)", raw, re.I
    )
    if match:
        return (
            f"采集统计：原始 {match[1]} 条，入库 {match[2]} 条，"
            f"异常 {match[3]} 条"
        )
    match = re.fullmatch(
        r"crawl job done id=(\w+) shows=(\d+) ledger_visible=(\d+) "
        r"ledger_hidden=(\d+) errors=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"采集任务已结束：任务编号 {match[1]}，入库 {match[2]} 条，"
            f"台账可见 {match[3]} 条，隐藏 {match[4]} 条，"
            f"异常 {match[5]} 条"
        )
    match = re.fullmatch(
        r"crawl job done id=(\w+) shows=(\d+) errors=(\d+)", raw, re.I
    )
    if match:
        return (
            f"采集任务已结束：任务编号 {match[1]}，"
            f"入库 {match[2]} 条，异常 {match[3]} 条"
        )

    match = re.fullmatch(
        r"damai crawl city=(.*?) category=(.*?) keyword=(.*?) pages=(\S+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"开始采集大麦网：城市 {_value(match[1])}，"
            f"分类 {_value(match[2], '全部')}，关键词 {_value(match[3])}，"
            f"页数 {match[4]}"
        )
    match = re.fullmatch(r"damai detail enrich start count=(\d+)", raw, re.I)
    if match:
        return f"开始补全大麦网项目详情：共 {match[1]} 个项目"
    match = re.fullmatch(r"damai detail enrich done with_sessions=(\d+)", raw, re.I)
    if match:
        return f"大麦网项目详情补全完成：{match[1]} 个项目含场次"
    match = re.fullmatch(r"damai done raw=(\d+)", raw, re.I)
    if match:
        return f"大麦网列表采集完成：原始项目 {match[1]} 个"
    match = re.fullmatch(
        r"damai city=(.*?) kw=(.*?) page=(\d+) got=(\d+) totalPage=(\S+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦网第 {match[3]} 页采集完成：新增 {match[4]} 个项目，"
            f"总页数 {_value(match[5], '未知')}"
        )
    match = re.fullmatch(
        r"damai empty page city=(.*?) kw=(.*?) page=(\d+)", raw, re.I
    )
    if match:
        return f"大麦网第 {match[3]} 页无新数据，停止翻页"
    match = re.fullmatch(r"damai detail progress (\d+)/(\d+) id=(\S+)", raw, re.I)
    if match:
        return f"大麦网详情进度：{match[1]}/{match[2]}，当前项目 {match[3]}"
    match = re.fullmatch(r"damai detail processing (\d+)/(\d+) id=(\S+)", raw, re.I)
    if match:
        return f"正在处理大麦网详情：{match[1]}/{match[2]}，项目编号 {match[3]}"
    match = re.fullmatch(
        r"damai pc price absent item=(\S+) sessions=(\d+) "
        r"explicit_ticket_sessions=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦 PC 详情已完整返回但未显示价格：项目编号 {match[1]}，"
            f"场次 {match[2]} 个；将使用移动端补全价格"
        )
    match = re.fullmatch(
        r"damai pc app only item=(\S+) buy_status=(\S+) buy_origin=(\S+)",
        raw,
        re.I,
    )
    if match:
        return (
            "大麦 PC 项目页可正常访问，但当前渠道仅支持大麦 App 购买："
            f"项目编号 {match[1]}；将使用移动端补全场次和价格"
        )
    match = re.fullmatch(
        r"damai mobile detail fallback item=(\S+) url=(\S+) reason=(\S+)",
        raw,
        re.I,
    )
    if match:
        if match[3].lower() == "pc_app_only":
            return (
                "PC 项目明确仅支持大麦 App 购买，已使用移动端补全："
                f"项目编号 {match[1]}，地址 {match[2]}"
            )
        return (
            "PC 详情已正常返回但未显示价格，已使用大麦移动端补全："
            f"项目编号 {match[1]}，"
            f"地址 {match[2]}"
        )
    match = re.fullmatch(
        r"damai mobile detail success item=(\S+) url=(\S+) sessions=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦移动端详情获取成功：项目编号 {match[1]}，"
            f"场次 {match[3]} 个，地址 {match[2]}"
        )
    match = re.fullmatch(
        r"damai mobile detail failed item=(\S+) attempt=(\d+)/(\d+) reason=.*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"大麦移动端详情暂时失败：项目编号 {match[1]}，"
            f"尝试 {match[2]}/{match[3]}"
        )
    match = re.fullmatch(
        r"damai mobile detail retry item=(\S+) attempt=(\d+)/(\d+) "
        r"retry_in=([\d.]+)s",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦移动端详情自动重试：项目编号 {match[1]}，"
            f"第 {match[2]}/{match[3]} 次，等待 {match[4]} 秒"
        )
    match = re.fullmatch(
        r"damai mobile detail exhausted item=(\S+) attempts=(\d+) reason=.*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"大麦移动端详情重试已耗尽：项目编号 {match[1]}，"
            f"已尝试 {match[2]} 次"
        )
    match = re.fullmatch(r"damai detail skipped item=(\S+) reason=.*", raw, re.I | re.S)
    if match:
        return f"大麦网详情获取失败，已跳过项目 {match[1]} 并继续下一个"
    match = re.fullmatch(
        r"damai pc detail skipped item=(\S+) reason=.*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            "大麦 PC 详情业务数据不完整，未切换移动端，"
            f"已跳过项目 {match[1]} 并继续下一个"
        )
    match = re.fullmatch(
        r"damai pc detail batch suspended item=(\S+) progress=(\d+)/(\d+) reason=.*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"大麦 PC 详情通道暂未恢复，已暂停本批详情：项目编号 {match[1]}，"
            f"进度 {match[2]}/{match[3]}；未切换移动端，可从断点补跑"
        )
    match = re.fullmatch(
        r"damai item static skipped item=(\S+) price_confirmed=true reason=(\S+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦 PC 票价已获取，项目编号 {match[1]}；"
            "项目介绍暂不可用，继续保留 PC 详情"
        )
    match = re.fullmatch(
        r"damai detail batch done success=(\d+) skipped=(\d+) total=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦网详情批次完成：成功 {match[1]} 个，"
            f"跳过 {match[2]} 个，共 {match[3]} 个"
        )

    match = re.fullmatch(
        r"damai detail item=(\S+) venue=(.*?) addr=(.*?) sessions=(\d+) "
        r"complete=(\S+) dates=(\d+)/(\d+) ticket_sessions=(\d+)/(\d+) "
        r"troupe=(.*?) organizers=(.*)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦网项目详情已完成：项目编号 {match[1]}，"
            f"场馆 {_value(match[2], '未提供')}，场次 {match[4]} 个，"
            f"日期 {match[6]}/{match[7]}，票档场次 {match[8]}/{match[9]}，"
            f"完整性：{_yes_no(match[5])}"
        )
    match = re.fullmatch(
        r"damai detail item=(\S+) venue=(.*?) addr=(.*?) sessions=(\d+) "
        r"troupe=(.*?) organizers=(.*)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦网项目详情处理完成：项目编号 {match[1]}，"
            f"场馆 {_value(match[2], '未提供')}，场次 {match[4]} 个"
        )

    match = re.fullmatch(
        r"subpage pc unavailable item=(\S+) dataType=(\S+) dataId=(\S+) "
        r"reason=(\S+) status=(\S+) content_type=(\S+) chars=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦 PC 详情通道暂时受限：项目编号 {match[1]}，"
            f"子项类型 {match[2]}，网络状态码 {match[5]}；"
            "系统将重试原请求，不切换移动端"
        )
    match = re.fullmatch(
        r"item\.htm pc unavailable item=(\S+) reason=(\S+) status=(\S+) "
        r"content_type=(\S+) chars=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦 PC 项目页暂时受限：项目编号 {match[1]}，"
            f"网络状态码 {match[3]}；系统将重试原请求，不切换移动端"
        )
    match = re.fullmatch(
        r"item\.htm pc retry scheduled item=(\S+) reason=(\S+) "
        r"attempt=(\d+)/(\d+) retry_in=([\d.]+)s",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦 PC 项目页自动重试：项目编号 {match[1]}，"
            f"第 {match[3]}/{match[4]} 次，等待 {match[5]} 秒；不切换移动端"
        )
    match = re.fullmatch(
        r"item\.htm pc semantic failure item=(\S+) reason=(\S+) "
        r"status=(\S+) chars=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦 PC 项目页返回错误页面：项目编号 {match[1]}，"
            "未切换移动端，将跳过该项目"
        )
    match = re.fullmatch(r"subpage http (\d+) item=(\S+) dataId=(\S+)", raw, re.I)
    if match:
        return (
            f"详情子请求收到网络状态码 {match[1]}，"
            f"项目编号 {match[2]}，将自动重试"
        )
    match = re.fullmatch(r"subpage request failed item=(\S+):.*", raw, re.I | re.S)
    if match:
        return f"详情子请求暂时失败，项目编号 {match[1]}，将自动重试"
    match = re.fullmatch(
        r"subpage empty response item=(\S+) status=(\S+) content_type=(\S+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"详情子请求返回空响应，项目编号 {match[1]}，"
            f"网络状态码 {match[2]}，将自动重试"
        )
    match = re.fullmatch(
        r"subpage (?:invalid response|parse failed) item=(\S+).*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"详情子请求响应格式暂不可用，项目编号 {match[1]}，"
            "将自动重试"
        )
    match = re.fullmatch(
        r"subpage bixi punish item=(\S+) dataType=(\S+) dataId=(\S+).*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"大麦 PC 详情触发临时风控：项目编号 {match[1]}，"
            f"子项类型 {match[2]}，子项编号 {match[3]}；已停止快速重试"
        )
    match = re.fullmatch(
        r"damai pc circuit open item=(\S+) label=(\S+).*round=(\d+)/(\d+) "
        r"cooldown=([\d.]+)s resume_at=(\S+) checkpoint_saved=(true|false) "
        r"trigger=(\S+)",
        raw,
        re.I | re.S,
    )
    if match:
        suffix = "" if match[7].lower() == "true" else "；断点保存失败"
        channel_state = "风控" if match[8].lower() == "bixi" else "通道异常"
        return (
            f"大麦 PC 详情{channel_state}冷却：项目编号 {match[1]}，"
            f"子项 {_detail_label(match[2])}，第 {match[3]}/{match[4]} 轮，"
            f"暂停 {match[5]} 秒后重试原请求{suffix}"
        )
    match = re.fullmatch(
        r"damai pc circuit probe invalid item=(\S+) label=(\S+).*response=(\S+)",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"大麦 PC 详情冷却后的原请求仍未恢复：项目编号 {match[1]}，"
            f"子项 {_detail_label(match[2])}；将进入下一轮长冷却"
        )
    match = re.fullmatch(
        r"damai pc circuit probe item=(\S+) label=(\S+).*round=(\d+)",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"大麦 PC 详情冷却结束，正在重试原请求：项目编号 {match[1]}，"
            f"子项 {_detail_label(match[2])}"
        )
    match = re.fullmatch(
        r"damai pc circuit closed item=(\S+) label=(\S+) recovered_round=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"大麦 PC 详情通道已恢复：项目编号 {match[1]}，"
            f"继续采集 {_detail_label(match[2])}"
        )
    match = re.fullmatch(
        r"damai pc circuit exhausted item=(\S+) label=(\S+).*"
        r"checkpoint_saved=(true|false).*",
        raw,
        re.I | re.S,
    )
    if match:
        checkpoint_text = (
            "已保存待处理列表"
            if match[3].lower() == "true"
            else "断点保存失败"
        )
        return (
            f"大麦 PC 详情通道恢复失败，{checkpoint_text}并停止本批详情："
            f"项目编号 {match[1]}，子项 {_detail_label(match[2])}；"
            "需要重新发起详情补跑"
        )
    match = re.fullmatch(r"subpage response fail item=(\S+) code=(\S+)", raw, re.I)
    if match:
        return (
            f"详情子请求业务响应未成功，项目编号 {match[1]}，"
            f"状态码 {match[2]}，将自动重试"
        )
    match = re.fullmatch(
        r"subpage semantic mismatch item=(\S+) label=(\S+).*attempt=(\d+)/(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"详情子项内容不匹配，项目编号 {match[1]}，"
            f"子项 {_detail_label(match[2])}，尝试 {match[3]}/{match[4]}"
        )
    match = re.fullmatch(
        r"subpage retry scheduled item=(\S+) label=(\S+) attempt=(\d+)/(\d+) "
        r"retry_in=([\d.]+)s",
        raw,
        re.I,
    )
    if match:
        return (
            f"详情子项自动重试：项目编号 {match[1]}，"
            f"子项 {_detail_label(match[2])}，第 {match[3]}/{match[4]} 次，"
            f"等待 {match[5]} 秒"
        )
    match = re.fullmatch(
        r"subpage retries exhausted item=(\S+) label=(\S+).*attempts=(\d+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"详情子项重试已耗尽，项目编号 {match[1]}，"
            f"子项 {_detail_label(match[2])}；未切换移动端"
        )
    match = re.fullmatch(
        r"damai detail project retry item=(\S+) attempt=(\d+)/(\d+) "
        r"cooldown=([\d.]+)s reason=.*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"大麦网项目详情整体重试：项目编号 {match[1]}，"
            f"第 {match[2]}/{match[3]} 轮，冷却 {match[4]} 秒"
        )
    match = re.fullmatch(
        r"damai detail rejected item=(\S+) attempts=(\d+) reason=.*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"大麦网项目详情不完整，已拒绝入库："
            f"项目编号 {match[1]}，已尝试 {match[2]} 轮"
        )
    match = re.fullmatch(r"item\.htm http (\d+) item=(\S+)", raw, re.I)
    if match:
        return f"项目介绍页请求收到网络状态码 {match[1]}，项目编号 {match[2]}"
    match = re.fullmatch(r"item\.htm fetch failed item=(\S+):.*", raw, re.I | re.S)
    if match:
        return f"项目介绍页请求暂时失败，项目编号 {match[1]}"

    match = re.fullmatch(
        r"maoyan crawl city=(.*?) category=(.*?) keyword=(.*?) pages=(\S+)",
        raw,
        re.I,
    )
    if match:
        return (
            f"开始采集猫眼：城市 {_value(match[1])}，"
            f"分类 {_value(match[2], '全部')}，关键词 {_value(match[3])}，"
            f"页数 {match[4]}"
        )
    match = re.fullmatch(
        r"maoyan crawl city=(.*?) keyword=(.*?) pages=(\S+)", raw, re.I
    )
    if match:
        return (
            f"开始采集猫眼：城市 {_value(match[1])}，"
            f"关键词 {_value(match[2])}，页数 {match[3]}"
        )
    match = re.fullmatch(
        r"maoyan mobile API crawl: city=(.*?) cityId=(\S+) category=(.*?) "
        r"categoryId=(\S+) keyword=(.*)",
        raw,
        re.I,
    )
    if match:
        return (
            f"猫眼列表接口已就绪：城市 {_value(match[1])}，"
            f"分类 {_value(match[3], '全部')}，关键词 {_value(match[5])}"
        )
    # 兼容旧日志格式（没有分类字段）。
    match = re.fullmatch(
        r"maoyan mobile API crawl: city=(.*?) cityId=(\S+) keyword=(.*)", raw, re.I
    )
    if match:
        return (
            f"猫眼列表接口已就绪：城市 {_value(match[1])}，"
            f"关键词 {_value(match[3])}"
        )
    match = re.fullmatch(r"maoyan fetching page=(\d+)", raw, re.I)
    if match:
        return f"正在采集猫眼第 {match[1]} 页"
    match = re.fullmatch(
        r"maoyan page=(\d+) records=(\d+) new_items=(\d+)", raw, re.I
    )
    if match:
        return (
            f"猫眼第 {match[1]} 页采集完成："
            f"返回 {match[2]} 条，新增 {match[3]} 条"
        )
    match = re.fullmatch(r"maoyan API status=(\d+) page=(\d+)", raw, re.I)
    if match:
        return f"猫眼第 {match[2]} 页请求收到网络状态码 {match[1]}"
    match = re.fullmatch(r"maoyan invalid JSON response page=(\d+)", raw, re.I)
    if match:
        return f"猫眼第 {match[1]} 页响应格式暂不可用"
    match = re.fullmatch(r"maoyan empty page=(\d+), stopping", raw, re.I)
    if match:
        return f"猫眼第 {match[1]} 页无新数据，停止翻页"
    match = re.fullmatch(r"maoyan API error page=(\d+):.*", raw, re.I | re.S)
    if match:
        return f"猫眼第 {match[1]} 页请求失败"
    match = re.fullmatch(
        r"maoyan crawl finished: city=(.*?) total_items=(\d+)", raw, re.I
    )
    if match:
        return f"猫眼城市采集完成：{_value(match[1])}，共 {match[2]} 个项目"
    match = re.fullmatch(r"maoyan done raw=(\d+)", raw, re.I)
    if match:
        return f"猫眼列表采集完成：原始项目 {match[1]} 个"

    match = re.fullmatch(
        r"\[(damai|maoyan|showstart)\] captcha detected kind=(\S+) reason=(\S+).*",
        raw,
        re.I | re.S,
    )
    if match:
        return f"{_platform(match[1])}触发安全验证，系统正在自动处理"
    match = re.fullmatch(
        r"\[(damai|maoyan|showstart)\] auto solve attempt (\d+)/(\d+)", raw, re.I
    )
    if match:
        return f"{_platform(match[1])}正在自动处理验证码：第 {match[2]}/{match[3]} 次"
    match = re.fullmatch(
        r"\[(damai|maoyan|showstart)\] captcha cleared via (.*)", raw, re.I
    )
    if match:
        return f"{_platform(match[1])}安全验证已通过"
    match = re.fullmatch(
        r"\[(damai|maoyan|showstart)\] auto failed, fallback manual:.*",
        raw,
        re.I | re.S,
    )
    if match:
        return f"{_platform(match[1])}自动验证未通过，已转为人工验证"
    match = re.fullmatch(
        r"\[(damai|maoyan|showstart)\] 请在浏览器中手动完成验证（.*?），"
        r"最多等待 (\d+)s …",
        raw,
        re.I,
    )
    if match:
        return (
            f"{_platform(match[1])}需要人工验证："
            f"请在浏览器中完成操作，最多等待 {match[2]} 秒"
        )
    if re.fullmatch(r"bingtop needs username \+ password", raw, re.I):
        return "冰拓验证码服务配置不完整：请填写用户名和密码"
    if re.fullmatch(r"chaojiying needs username \+ password \+ soft_id", raw, re.I):
        return (
            "超级鹰验证码服务配置不完整："
            "请填写用户名、密码和软件编号"
        )
    if re.fullmatch(r"yunma needs api_key\(token\)", raw, re.I):
        return "云码验证码服务配置不完整：请填写访问密钥"

    # 验证码诊断仅展示安全数值；URL、captchaId、图片和令牌不进入客户日志。
    match = re.fullmatch(
        r"bingtop dual upload type=(\d+)\s+main=.*\s+sub=.*",
        raw,
        re.I | re.S,
    )
    if match:
        return f"冰拓滑块题图片已提交：类型 {match[1]}"
    match = re.fullmatch(
        r"bingtop ok type=(\d+) url=\S+ captchaId=\S+ "
        r"recognition=(-?\d+(?:\.\d+)?).*",
        raw,
        re.I | re.S,
    )
    if match:
        return f"冰拓识别成功：类型 {match[1]}，返回原始距离 {match[2]}"
    if re.fullmatch(r"bingtop (?:type1357 )?request failed:.*", raw, re.I | re.S):
        return "冰拓识别请求失败，未取得滑块距离（详细原因见服务端日志）"
    match = re.fullmatch(
        r"bingtop (?:non-json|error|empty recognition|recognition error|"
        r"non-numeric recognition) type=(\d+).*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"冰拓未返回有效距离：类型 {match[1]}"
            "（服务响应详情见服务端日志）"
        )
    match = re.fullmatch(
        r"bingtop type=(\d+) (?:needs captchaData\+subCaptchaData|"
        r"refuse non-image(?: payload| main)?|missing subCaptchaData).*",
        raw,
        re.I | re.S,
    )
    if match:
        return f"冰拓滑块题图片不完整或格式无效：类型 {match[1]}，未发起识别"

    match = re.fullmatch(r"provider upload prep type=(\d+) .*", raw, re.I | re.S)
    if match:
        return f"滑块题图片准备完成：类型 {match[1]}，正在调用打码服务"
    if re.fullmatch(r"provider solve_fruit_offset error:.*", raw, re.I | re.S):
        return "打码服务调用异常，未取得滑块距离（详细原因见服务端日志）"
    match = re.fullmatch(
        r"provider returned no offset \(round=(\d+)/(\d+)\)", raw, re.I
    )
    if match:
        return f"打码服务第 {match[1]}/{match[2]} 次未返回有效滑块距离"
    match = re.fullmatch(
        r"provider returned no offset; refreshing captcha to retry "
        r"\((\d+)/(\d+)\)",
        raw,
        re.I,
    )
    if match:
        return f"打码服务未返回距离，正在刷新验证码后重试（{match[1]}/{match[2]}）"
    match = re.fullmatch(
        r"provider \(bingtop\) failed (\d+) times consecutively without offset;.*",
        raw,
        re.I | re.S,
    )
    if match:
        return f"冰拓连续 {match[1]} 次未返回有效滑块距离，自动识别停止"
    match = re.fullmatch(
        r"provider path: stale payload key=.* round=(\d+), refresh",
        raw,
        re.I | re.S,
    )
    if match:
        return f"第 {match[1]} 轮滑块题已过期，正在刷新题目"
    match = re.fullmatch(r"provider path: geometry missing \(round=(\d+)\)", raw, re.I)
    if match:
        return f"第 {match[1]} 轮未读取到滑块页面尺寸，正在重试"
    match = re.fullmatch(
        r"provider path: wait newslidecaptcha dual images "
        r"\(round=(\d+) img=(\S+) ques=(\S+)\)",
        raw,
        re.I,
    )
    if match:
        return (
            f"第 {match[1]} 轮正在等待滑块双图"
            f"（主图：{_yes_no(match[2])}，题图：{_yes_no(match[3])}）"
        )
    match = re.fullmatch(r"provider path: no image for round=(\d+)", raw, re.I)
    if match:
        return f"第 {match[1]} 轮未取得滑块图片，正在刷新题目"

    match = re.fullmatch(
        r"provider map styles edge_ui=(-?\d+(?:\.\d+)?) "
        r"raw_ui=(-?\d+(?:\.\d+)?) \(drag edge_ui\)",
        raw,
        re.I,
    )
    if match:
        return (
            f"滑块坐标换算核对：右边缘模式 {match[1]}，"
            f"原始坐标模式 {match[2]}，本次采用 {match[1]}"
        )
    match = re.fullmatch(
        r"provider fruit offset raw=(-?\d+(?:\.\d+)?) "
        r"logic_w=(-?\d+(?:\.\d+)?) ui_x=(-?\d+(?:\.\d+)?) "
        r"max_slide=(-?\d+(?:\.\d+)?) map=\S+",
        raw,
        re.I,
    )
    if match:
        return (
            f"滑块距离换算：原始返回 {match[1]}，页面拖动 {match[3]}"
            f"（题图宽 {match[2]}，最大可滑 {match[4]}）"
        )
    match = re.fullmatch(
        r"drag_to_offset target=(-?\d+(?:\.\d+)?) "
        r"dist=(-?\d+(?:\.\d+)?) mouse_dx=(-?\d+(?:\.\d+)?) "
        r"knob_dx=(-?\d+(?:\.\d+)?).*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"滑块拖动完成：目标 {match[1]}，鼠标位移 {match[3]}，"
            f"滑块实际位移 {match[4]}"
        )
    match = re.fullmatch(
        r"fruit validate seq=(\d+) http=(\S+) code=(\S+).*",
        raw,
        re.I | re.S,
    )
    if match:
        code = _value(match[3], "未知")
        if code == "0":
            outcome = "通过"
        elif code == "未知":
            outcome = "未取得结果"
        else:
            outcome = "未通过"
        return (
            f"大麦滑块校验{outcome}：状态码 {code}，"
            f"网络状态码 {_value(match[2], '未知')}"
        )
    match = re.fullmatch(
        r"provider validate correlation seq=\S+ "
        r"protocol_per=(-?\d+(?:\.\d+)?) actual_per=(-?\d+(?:\.\d+)?)",
        raw,
        re.I,
    )
    if match:
        return f"滑块比例核对：预计 {match[1]}，实际 {match[2]}"
    match = re.fullmatch(
        r"provider drag vs bingtop: raw=(-?\d+(?:\.\d+)?) "
        r"ui_x=(-?\d+(?:\.\d+)?) mouse_dx=(-?\d+(?:\.\d+)?) "
        r"knob_dx=(-?\d+(?:\.\d+)?).*",
        raw,
        re.I | re.S,
    )
    if match:
        return (
            f"冰拓距离执行核对：原始 {match[1]}，目标 {match[2]}，"
            f"鼠标位移 {match[3]}，滑块位移 {match[4]}"
        )
    match = re.fullmatch(
        r"fruit slider accepted by validate at ui_x=(-?\d+(?:\.\d+)?)",
        raw,
        re.I,
    )
    if match:
        return f"水果滑块验证已通过（页面拖动距离 {match[1]}）"
    match = re.fullmatch(
        r"fruit slider rejected by validate code=(\S+) "
        r"at ui_x=(-?\d+(?:\.\d+)?)",
        raw,
        re.I,
    )
    if match:
        return f"大麦拒绝本次滑块：状态码 {match[1]}，页面拖动距离 {match[2]}"
    match = re.fullmatch(
        r"validate rejected code=(\S+) but no replacement puzzle arrived",
        raw,
        re.I,
    )
    if match:
        return f"大麦拒绝滑块（状态码 {match[1]}），且未下发新题，自动处理停止"
    match = re.fullmatch(
        r"provider path: knob stuck at ui_x=(-?\d+(?:\.\d+)?);.*",
        raw,
        re.I | re.S,
    )
    if match:
        return f"滑块未跟随鼠标移动（目标距离 {match[1]}），正在刷新重试"
    if re.fullmatch(r"fruit slider error:.*", raw, re.I | re.S):
        return "滑块自动处理发生异常，已停止本次自动验证（详细原因见服务端日志）"

    match = re.fullmatch(r"fruit slider round[= ](\d+)(?:/(\d+))?.*", raw, re.I | re.S)
    if match:
        total = f"/{match[2]}" if match[2] else ""
        return f"正在处理水果滑块验证：第 {match[1]}{total} 轮"
    if raw.lower().startswith("fruit slider cleared") or raw.lower().startswith(
        "fruit slider accepted"
    ):
        return "水果滑块验证已通过"
    if "new puzzle" in raw.lower() or "puzzle changed" in raw.lower():
        return "验证码题目已更新，正在处理新题目"
    if raw.lower().startswith("provider fruit failed"):
        return "第三方验证未通过，已转为本地处理"
    if raw.lower().startswith("local fruit failed"):
        return "本地验证未通过，已转为第三方处理"

    match = re.fullmatch(r"normalize: in=(\d+) out=(\d+) dropped=(\d+)", raw, re.I)
    if match:
        return (
            f"数据整理完成：输入 {match[1]} 条，"
            f"输出 {match[2]} 条，过滤 {match[3]} 条"
        )
    match = re.fullmatch(r"normalize failed:.* raw=(\S+)", raw, re.I | re.S)
    if match:
        return f"数据整理失败：项目编号 {match[1]}"
    match = re.fullmatch(
        r"keep existing (?:raw|show) detail source=(\w+) source_id=(\S+).*",
        raw,
        re.I | re.S,
    )
    if match:
        return f"新详情不完整，已保留{_platform(match[1])}项目 {match[2]} 的旧数据"

    if _CJK_RE.search(raw):
        translated = _translate_mixed_chinese(raw)
        if not _ENGLISH_WORD_RE.search(translated):
            return translated

    module = _module_name(logger_name, raw)
    context = _technical_context(raw)
    normalized_level = str(level or "INFO").upper()
    if normalized_level in {"ERROR", "CRITICAL"}:
        return f"{module}发生错误，详细原因已记录在服务端日志{context}"
    if normalized_level in {"WARN", "WARNING"}:
        return f"{module}出现可恢复异常，系统正在处理{context}"
    return f"{module}正在处理任务{context}"
