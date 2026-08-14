"""任务日志客户可读中文转换。"""

from __future__ import annotations

import pytest

from app.utils.task_log_translation import translate_task_error, translate_task_log


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "browser started headless=False proxy=False",
            "自动化采集浏览器已启动（有界面，代理：否）",
        ),
        (
            "source damai item=1070279743616 persisted sessions=2 rows=2",
            "大麦网项目已入库：项目编号 1070279743616，场次 2 个，数据 2 条",
        ),
        (
            "source damai list checkpoint persisted projects=389",
            "大麦网列表已保存断点：项目 389 个，详情中断后可重新补跑",
        ),
        (
            "subpage retry scheduled item=1070279743616 label=base "
            "attempt=2/5 retry_in=3.0s",
            "详情子项自动重试：项目编号 1070279743616，"
            "子项 基础信息，第 2/5 次，等待 3.0 秒",
        ),
        (
            "damai pc circuit open item=1007108168970 "
            "label=perform:280339080 dataType=2 dataId=280339080 "
            "round=1/2 cooldown=180.0s resume_at=2026-08-13T12:00:00+00:00 "
            "checkpoint_saved=true trigger=bixi",
            "大麦 PC 详情风控冷却：项目编号 1007108168970，"
            "子项 场次 280339080，第 1/2 轮，暂停 180.0 秒后重试原请求",
        ),
        (
            "damai pc circuit probe invalid item=1007108168970 "
            "label=perform:280339080 dataType=2 dataId=280339080 "
            "response=unavailable",
            "大麦 PC 详情冷却后的原请求仍未恢复：项目编号 1007108168970，"
            "子项 场次 280339080；将进入下一轮长冷却",
        ),
        (
            "damai pc circuit exhausted item=1007108168970 "
            "label=perform:280339080 dataType=2 dataId=280339080 "
            "cooldowns=2 checkpoint_saved=false trigger=probe_invalid",
            "大麦 PC 详情通道恢复失败，断点保存失败并停止本批详情："
            "项目编号 1007108168970，子项 场次 280339080；需要重新发起详情补跑",
        ),
        (
            "damai detail rejected item=1070279743616 attempts=2 reason=blocked",
            "大麦网项目详情不完整，已拒绝入库："
            "项目编号 1070279743616，已尝试 2 轮",
        ),
        (
            "damai mobile detail fallback item=1073716080825 "
            "url=https://m.damai.cn/shows/item.html?itemId=1073716080825 "
            "reason=pc_no_price",
            "PC 详情已正常返回但未显示价格，已使用大麦移动端补全："
            "项目编号 1073716080825，"
            "地址 https://m.damai.cn/shows/item.html?itemId=1073716080825",
        ),
        (
            "subpage pc unavailable item=1073716080825 dataType=2 "
            "dataId=281393778 reason=html_response status=200 "
            "content_type=text/html chars=1234",
            "大麦 PC 详情通道暂时受限：项目编号 1073716080825，"
            "子项类型 2，网络状态码 200；"
            "系统将重试原请求，不切换移动端",
        ),
        (
            "damai pc price absent item=1073716080825 sessions=3 "
            "explicit_ticket_sessions=3",
            "大麦 PC 详情已完整返回但未显示价格：项目编号 1073716080825，"
            "场次 3 个；将使用移动端补全价格",
        ),
        (
            "damai pc app only item=1055929918278 buy_status=100 buy_origin=109",
            "大麦 PC 项目页可正常访问，但当前渠道仅支持大麦 App 购买："
            "项目编号 1055929918278；将使用移动端补全场次和价格",
        ),
        (
            "damai mobile detail fallback item=1055929918278 "
            "url=https://m.damai.cn/shows/item.html?itemId=1055929918278 "
            "reason=pc_app_only",
            "PC 项目明确仅支持大麦 App 购买，已使用移动端补全："
            "项目编号 1055929918278，"
            "地址 https://m.damai.cn/shows/item.html?itemId=1055929918278",
        ),
        (
            "damai pc detail batch suspended item=1073716080825 progress=3/90 "
            "reason=channel unavailable",
            "大麦 PC 详情通道暂未恢复，已暂停本批详情：项目编号 1073716080825，"
            "进度 3/90；未切换移动端，可从断点补跑",
        ),
        (
            "item.htm pc retry scheduled item=1073716080825 reason=http_502 "
            "attempt=2/3 retry_in=2.0s",
            "大麦 PC 项目页自动重试：项目编号 1073716080825，"
            "第 2/3 次，等待 2.0 秒；不切换移动端",
        ),
        (
            "item.htm pc semantic failure item=1073716080825 "
            "reason=http_200_404_shell status=200 chars=2048",
            "大麦 PC 项目页返回错误页面：项目编号 1073716080825，"
            "未切换移动端，将跳过该项目",
        ),
        (
            "damai detail skipped item=1073716080825 reason=mobile blocked",
            "大麦网详情获取失败，已跳过项目 1073716080825 并继续下一个",
        ),
        (
            "maoyan page=2 records=10 new_items=8",
            "猫眼第 2 页采集完成：返回 10 条，新增 8 条",
        ),
        (
            "maoyan crawl city=北京 keyword='' pages=3",
            "开始采集猫眼：城市 北京，关键词 无，页数 3",
        ),
        (
            "[damai] captcha detected kind=slider reason=fruit_slider_ui "
            "url=https://example.test",
            "大麦网触发安全验证，系统正在自动处理",
        ),
        (
            "bingtop needs username + password",
            "冰拓验证码服务配置不完整：请填写用户名和密码",
        ),
    ],
)
def test_known_task_logs_are_translated(raw, expected):
    assert translate_task_log(raw) == expected


def test_unknown_english_log_returns_chinese_summary_with_context():
    translated = translate_task_log(
        "TimeoutError while fetching item=1070279743616 page=3",
        level="ERROR",
        logger_name="app.crawlers.damai.detail",
    )

    assert translated == (
        "大麦网采集发生错误，详细原因已记录在服务端日志"
        "（项目编号：1070279743616，页码：3）"
    )
    assert "TimeoutError" not in translated
    assert "fetching" not in translated


def test_task_error_and_mixed_fields_are_translated():
    raw = "damai: damai captcha solver failed city=北京 keyword='' page=1"
    assert translate_task_error(raw) == (
        "大麦网验证码自动处理失败（城市：北京，关键词：无，第 1 页）"
    )

    mixed = translate_task_error(
        "damai: 大麦详情最终失败 item=123 attempts=5"
    )
    assert mixed == "大麦网：大麦详情最终失败 项目编号：123 尝试次数：5"

    unknown_mixed = translate_task_error("详情请求失败：TimeoutError item=123")
    assert unknown_mixed == (
        "采集引擎发生异常，详细原因已记录在服务端日志"
        "（项目编号：123）"
    )
