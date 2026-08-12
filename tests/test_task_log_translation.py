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
            "subpage retry scheduled item=1070279743616 label=base "
            "attempt=2/5 retry_in=3.0s",
            "详情子项自动重试：项目编号 1070279743616，"
            "子项 基础信息，第 2/5 次，等待 3.0 秒",
        ),
        (
            "damai detail rejected item=1070279743616 attempts=2 reason=blocked",
            "大麦网项目详情不完整，已拒绝入库："
            "项目编号 1070279743616，已尝试 2 轮",
        ),
        (
            "damai mobile detail fallback item=1073716080825 "
            "url=https://m.damai.cn/shows/item.html?itemId=1073716080825 "
            "reason=pc business 404",
            "PC 详情不可用，已切换大麦移动端：项目编号 1073716080825，"
            "地址 https://m.damai.cn/shows/item.html?itemId=1073716080825",
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
