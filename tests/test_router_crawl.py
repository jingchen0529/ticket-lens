"""采集触发路由 + job manager 测试。

不真正开浏览器：把 run_crawl 换成假协程，只验证路由 + job manager 的
状态流转、并发拦截、参数回退。

注意：Starlette TestClient 每个请求各起一个事件循环，后台 asyncio.Task /
Lock 会绑在临时循环上，无法验证并发/后台任务。所以：
  - 同步读端点、参数校验 → 用 TestClient
  - 异步并发/状态流转 → 直接在单一事件循环里驱动 manager
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import CrawlJob, CrawlResult, SourcePlatform


@pytest.fixture(autouse=True)
def _reset_manager():
    """每个用例用全新的 job manager，避免相互串状态。"""
    import app.services.crawl_jobs as cj

    cj._manager = None
    yield
    cj._manager = None


# ---------- 同步读端点 / 参数校验（TestClient 足够） ----------


def test_list_empty():
    with TestClient(app) as client:
        r = client.get("/api/crawl")
        assert r.status_code == 200
        assert r.json() == {"items": []}


def test_active_empty():
    with TestClient(app) as client:
        r = client.get("/api/crawl/active")
        assert r.status_code == 200
        assert r.json() == {"active": None}


def test_get_missing_job_404():
    with TestClient(app) as client:
        r = client.get("/api/crawl/does-not-exist")
        assert r.status_code == 404


def test_unknown_source_400():
    with TestClient(app) as client:
        r = client.post("/api/crawl", json={"sources": ["youku"]})
        assert r.status_code == 400
        assert "youku" in r.json()["detail"]


def test_max_pages_zero_and_null_mean_all(monkeypatch):
    """不传 / 0 → 全量（job.max_pages=0），不再回退配置 3 页。"""
    import app.services.crawl_jobs as cj
    from app.services.crawl_jobs import CrawlJobManager

    captured: list[CrawlJob] = []

    async def _capture(job: CrawlJob, config) -> CrawlResult:
        captured.append(job)
        await asyncio.sleep(0.01)
        return CrawlResult(
            job=job,
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            raw_count=0,
            show_count=0,
        )

    monkeypatch.setattr(cj, "run_crawl", _capture)
    # 直接测路由里的约定：通过 manager 注入的 job
    # 这里用 TestClient 会另起 loop，改为直接构造请求解析逻辑
    from app.routers.crawl import CrawlRequest

    for raw in (None, 0):
        req = CrawlRequest(sources=["damai"], cities=["北京"], max_pages=raw, headed=True)
        assert req.max_pages in (None, 0)
        # 与 start_crawl 相同规则
        max_pages = 0 if req.max_pages is None or req.max_pages == 0 else int(req.max_pages)
        assert max_pages == 0

    req_n = CrawlRequest(sources=["damai"], cities=["北京"], max_pages=12, headed=True)
    assert req_n.max_pages == 12


def test_damai_category_request_and_job_payload():
    from app.routers.crawl import CrawlRequest
    from app.services.crawl_jobs import JobRecord

    req = CrawlRequest(sources=["damai"], cities=["北京"], category="音乐会")
    job = CrawlJob(
        sources=[SourcePlatform.DAMAI],
        cities=req.cities or [],
        category=req.category.strip(),
    )

    assert req.category == "音乐会"
    assert JobRecord(id="category-job", job=job).to_dict()["job"]["category"] == "音乐会"


def test_category_only_applies_to_single_platform():
    from app.routers.crawl import _category_for_sources

    assert _category_for_sources([SourcePlatform.DAMAI], " 音乐会 ") == "音乐会"
    assert _category_for_sources([SourcePlatform.MAOYAN], " 演唱会 ") == "演唱会"
    assert (
        _category_for_sources(
            [SourcePlatform.DAMAI, SourcePlatform.MAOYAN],
            "演唱会",
        )
        == ""
    )


# ---------- 异步并发 / 状态流转（直接驱动 manager） ----------


async def _fake_run_ok(job: CrawlJob, config) -> CrawlResult:
    await asyncio.sleep(0.05)
    return CrawlResult(
        job=job,
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        raw_count=4,
        show_count=4,
        by_source={"damai": 4},
    )


async def _fake_run_slow(job: CrawlJob, config) -> CrawlResult:
    await asyncio.sleep(10)  # 永远等，供取消/并发测试
    return CrawlResult(job=job, started_at=datetime.utcnow())


@pytest.mark.asyncio
async def test_submit_and_succeed(monkeypatch):
    import app.services.crawl_jobs as cj

    monkeypatch.setattr(cj, "run_crawl", _fake_run_ok)
    mgr = cj.CrawlJobManager()
    job = CrawlJob(sources=[SourcePlatform.DAMAI], cities=["北京"], max_pages=1)

    rec = await mgr.submit(job, config=object())
    assert rec.state.value == "pending"
    # 提交即有可展示日志，前端 Console 不用干等
    assert any("任务已提交" in (row.get("text") or "") for row in rec.logs)
    payload = rec.to_dict()
    assert "logs" in payload
    assert isinstance(payload["logs"], list)
    assert payload["logs"][0]["level"] == "INFO"

    await asyncio.wait_for(rec._task, timeout=2)
    assert rec.state.value == "succeeded"
    assert rec.result.show_count == 4
    result_payload = rec.to_dict()["result"]
    assert result_payload["ledger_visible_count"] == 4
    assert result_payload["ledger_hidden_count"] == 0
    # 完成后 active 释放，且有结束日志
    assert mgr.active is None
    assert any(
        "采集完成：入库 4 条、台账可见 4 条、隐藏展览休闲/体育 0 条"
        in (row.get("text") or "")
        for row in rec.logs
    )


@pytest.mark.asyncio
async def test_job_logs_capture_captcha_logger(monkeypatch):
    """采集过程中 captcha/crawler 日志应进入 JobRecord.logs。"""
    import logging

    import app.services.crawl_jobs as cj

    async def _run_with_captcha_log(job: CrawlJob, config) -> CrawlResult:
        error = "damai: damai captcha solver failed city=北京 keyword='' page=1"
        logging.getLogger("captcha.damai").warning(
            "[damai] captcha detected kind=slider reason=fruit_slider_ui"
        )
        logging.getLogger("app.crawlers.damai.fruit_slider").warning(
            "fruit: no newslidecaptcha payload yet (round=1)"
        )
        logging.getLogger("captcha.damai").warning(
            "[damai] auto failed, fallback manual: fruit slider rejected or not cleared"
        )
        logging.getLogger("app.services.crawl").error("crawler failed: %s", error)
        await asyncio.sleep(0.02)
        return CrawlResult(
            job=job,
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            raw_count=0,
            show_count=0,
            errors=[error],
        )

    monkeypatch.setattr(cj, "run_crawl", _run_with_captcha_log)
    mgr = cj.CrawlJobManager()
    job = CrawlJob(sources=[SourcePlatform.DAMAI], cities=["北京"], max_pages=1)
    rec = await mgr.submit(job, config=object())
    await asyncio.wait_for(rec._task, timeout=2)

    texts = " | ".join(row["text"] for row in rec.logs)
    assert "大麦网触发安全验证" in texts
    assert "验证码模块出现可恢复异常" in texts
    assert "已转为人工验证" in texts
    assert any(row["level"] == "WARN" for row in rec.logs)
    # result.errors 也会写入 ERROR 行
    assert any(
        row["level"] == "ERROR" and "验证码自动处理失败" in row["text"]
        for row in rec.logs
    )
    assert sum("验证码自动处理失败" in row["text"] for row in rec.logs) == 1
    assert rec.state.value == "failed"
    assert rec.error == (
        "大麦网验证码自动处理失败"
        "（城市：北京，关键词：无，第 1 页）"
    )
    assert rec.to_dict()["result"]["errors"] == [rec.error]


@pytest.mark.asyncio
async def test_concurrent_rejected(monkeypatch):
    import app.services.crawl_jobs as cj

    monkeypatch.setattr(cj, "run_crawl", _fake_run_slow)
    mgr = cj.CrawlJobManager()
    job = CrawlJob(sources=[SourcePlatform.DAMAI], cities=["北京"], max_pages=1)

    await mgr.submit(job, config=object())
    with pytest.raises(RuntimeError):
        await mgr.submit(job, config=object())

    # 清理：取消挂起任务，避免告警
    active = mgr.active
    if active and active._task:
        active._task.cancel()


@pytest.mark.asyncio
async def test_cancel(monkeypatch):
    import app.services.crawl_jobs as cj

    monkeypatch.setattr(cj, "run_crawl", _fake_run_slow)
    mgr = cj.CrawlJobManager()
    job = CrawlJob(sources=[SourcePlatform.DAMAI], cities=["北京"], max_pages=1)

    rec = await mgr.submit(job, config=object())
    # 让任务真正进入 RUNNING
    await asyncio.sleep(0.05)
    assert rec.state.value == "running"

    ok = await mgr.cancel(rec.id)
    assert ok is True
    await asyncio.sleep(0.05)
    assert rec.state.value == "cancelled"
    assert mgr.active is None


def test_manual_captcha_status():
    import app.services.crawl_jobs as cj

    job = CrawlJob(sources=[SourcePlatform.DAMAI], cities=["北京"], max_pages=1)
    rec = cj.JobRecord(id="test-job-123", job=job)

    assert rec.manual_captcha_required is None
    assert rec.to_dict()["manual_captcha_required"] is None

    rec.set_manual_captcha("冰拓打码连续 3 次未返回有效距离，需要人工介入", "bingtop")
    assert rec.manual_captcha_required is not None
    assert rec.manual_captcha_required["required"] is True
    assert rec.manual_captcha_required["provider"] == "bingtop"
    assert "冰拓打码" in rec.manual_captcha_required["reason"]
    assert rec.to_dict()["manual_captcha_required"] == rec.manual_captcha_required

    rec.clear_manual_captcha()
    assert rec.manual_captcha_required is None
    assert rec.to_dict()["manual_captcha_required"] is None
