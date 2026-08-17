"""采集任务管理器（单客户，内存态）。

采集是长任务：要开真实浏览器、可能弹窗等客户手动过验证码几分钟，
不能在 HTTP 请求里同步等。所以：

- POST 触发后立即返回 job_id，任务在 asyncio 后台跑
- GET 轮询状态 / 进度 / 结果 / 引擎日志（含验证码阶段）
- **同时只允许一个采集任务**：有头浏览器和 cookie 是全局资源，
  并发跑多个会互相抢窗口、cookie 打架。第二个请求直接拒绝。

单客户场景不需要持久化队列，进程重启后未完成任务即丢弃（符合预期：
浏览器窗口也随进程消失了）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from app.core.config import AppConfig, load_config
from app.models import CrawlJob, CrawlResult
from app.services.crawl import run_crawl
from app.utils.task_log_translation import translate_task_error, translate_task_log

logger = logging.getLogger(__name__)

# 前端 Console 只关心采集/验证码相关 logger，避免 uvicorn access 刷屏
_LOG_NAME_PREFIXES = (
    "captcha",
    "crawler",
    "app",
    "damai",
    "maoyan",
    "showstart",
)
_MAX_JOB_LOGS = 10000
_LEDGER_HIDDEN_LABEL = "展览休闲/体育"


def _result_ledger_counts(result: CrawlResult) -> tuple[int, int]:
    """兼容旧/测试结果：未携带新字段时按全部可见处理。"""
    hidden = result.ledger_hidden_count
    if hidden is None:
        hidden = sum(result.ledger_hidden_by_category.values())
    visible = result.ledger_visible_count
    if visible is None:
        visible = max(0, result.show_count - hidden)
    return int(visible), int(hidden)


class JobState(str, Enum):
    PENDING = "pending"       # 已创建，尚未开始
    RUNNING = "running"       # 采集中（浏览器已启动）
    SUCCEEDED = "succeeded"   # 正常完成
    FAILED = "failed"         # 抛异常中断
    CANCELLED = "cancelled"   # 被主动取消


def _level_name(levelno: int) -> str:
    if levelno >= logging.ERROR:
        return "ERROR"
    if levelno >= logging.WARNING:
        return "WARN"
    if levelno >= logging.INFO:
        return "INFO"
    return "DEBUG"


class _JobLogHandler(logging.Handler):
    """把采集相关日志写入 JobRecord.logs，供前端轮询展示。"""

    def __init__(self, record: "JobRecord") -> None:
        super().__init__(level=logging.INFO)
        self._record = record

    def emit(self, log_record: logging.LogRecord) -> None:
        try:
            name = log_record.name or ""
            if not any(name == p or name.startswith(p) for p in _LOG_NAME_PREFIXES):
                return
            msg = log_record.getMessage()
            if not msg or not str(msg).strip():
                return
            raw_text = str(msg).strip()
            # 如果日志包含多行（如堆栈或多行摘要），逐行解开追加，完整保留所有输出
            lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
            for line in lines:
                level = _level_name(log_record.levelno)
                translated = translate_task_log(
                    line,
                    level=level,
                    logger_name=name,
                )
                if not translated:
                    continue
                if len(translated) > 2000:
                    translated = translated[:1997] + "..."
                self._record.append_log(level, translated)
        except Exception:  # noqa: BLE001
            self.handleError(log_record)


@dataclass
class JobRecord:
    """一次采集任务的运行态快照。"""

    id: str
    job: CrawlJob
    state: JobState = JobState.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[CrawlResult] = None
    error: str = ""
    # 引擎/验证码阶段日志（前端 Console 轮询展示）
    logs: list[dict[str, str]] = field(default_factory=list)
    # 人工介入过验证提示状态（自动求解耗尽后触发）
    manual_captcha_required: Optional[dict[str, Any]] = None
    # 后台 asyncio 任务句柄，用于取消
    _task: Optional[asyncio.Task] = field(default=None, repr=False)

    def set_manual_captcha(self, reason: str = "", provider: str = "") -> None:
        """设置需要人工介入验证的状态"""
        self.manual_captcha_required = {
            "required": True,
            "reason": reason or "验证码自动破解失败，请在浏览器中手动拖动滑块",
            "provider": provider,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }

    def clear_manual_captcha(self) -> None:
        """清除人工介入验证状态"""
        self.manual_captcha_required = None

    def append_log(self, level: str, text: str) -> None:
        """追加一条可展示日志；超出上限丢弃最旧条目。"""
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": (level or "INFO").upper(),
            "text": text,
        }
        self.logs.append(entry)
        if len(self.logs) > _MAX_JOB_LOGS:
            del self.logs[: len(self.logs) - _MAX_JOB_LOGS]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state.value,
            "job": {
                "sources": [s.value for s in self.job.sources],
                "cities": self.job.cities,
                "keywords": self.job.keywords,
                "category": self.job.category,
                "max_pages": self.job.max_pages,
                "enrich_detail": bool(getattr(self.job, "enrich_detail", True)),
            },
            "created_at": self.created_at.isoformat() + "Z",
            "started_at": (self.started_at.isoformat() + "Z") if self.started_at else None,
            "finished_at": (self.finished_at.isoformat() + "Z") if self.finished_at else None,
            "error": self.error,
            "result": self._result_summary(),
            "logs": list(self.logs),
            "manual_captcha_required": self.manual_captcha_required,
        }

    def _result_summary(self) -> Optional[dict[str, Any]]:
        r = self.result
        if r is None:
            return None
        visible, hidden = _result_ledger_counts(r)
        return {
            "raw_count": r.raw_count,
            "show_count": r.show_count,
            "ledger_visible_count": visible,
            "ledger_hidden_count": hidden,
            "ledger_hidden_by_category": dict(r.ledger_hidden_by_category),
            "by_source": r.by_source,
            "errors": [translate_task_error(err) for err in r.errors],
            "output_path": r.output_path,
        }


class CrawlJobManager:
    """进程内单例，串行执行采集任务。"""

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._active_id: Optional[str] = None
        self._lock = asyncio.Lock()

    def get(self, job_id: str) -> Optional[JobRecord]:
        return self._jobs.get(job_id)

    def list(self) -> list[JobRecord]:
        # 新任务在前
        return sorted(self._jobs.values(), key=lambda r: r.created_at, reverse=True)

    @property
    def active(self) -> Optional[JobRecord]:
        if self._active_id is None:
            return None
        return self._jobs.get(self._active_id)

    async def submit(self, job: CrawlJob, config: Optional[AppConfig] = None) -> JobRecord:
        """提交一个采集任务。已有任务在跑时抛 RuntimeError。"""
        async with self._lock:
            active = self.active
            if active is not None and active.state in (JobState.PENDING, JobState.RUNNING):
                raise RuntimeError("已有采集任务在运行，请等待其完成或先取消")

            cfg = config or load_config()
            record = JobRecord(id=uuid.uuid4().hex, job=job)
            cities = "、".join(job.cities) if job.cities else "-"
            pages_label = "全部" if not job.max_pages or job.max_pages <= 0 else str(job.max_pages)
            category_label = job.category or "全部分类"
            detail_label = "开" if getattr(job, "enrich_detail", True) else "关"
            record.append_log(
                "INFO",
                f"任务已提交：任务编号 {record.id[:8]}，城市 {cities}，"
                f"分类 {category_label}，页数 {pages_label}，详情补全 {detail_label}",
            )
            self._jobs[record.id] = record
            self._active_id = record.id
            record._task = asyncio.create_task(self._run(record, cfg))
            logger.info("crawl job submitted id=%s", record.id)
            return record

    async def cancel(self, job_id: str) -> bool:
        """取消一个进行中的任务。返回是否确实发起了取消。"""
        record = self._jobs.get(job_id)
        if record is None:
            return False
        if record.state not in (JobState.PENDING, JobState.RUNNING):
            return False
        record.append_log("WARN", "收到取消请求，正在停止采集…")
        if record._task is not None:
            record._task.cancel()
        return True

    async def shutdown(self) -> None:
        """服务退出前取消并等待活动任务，让 Playwright 的 finally 完成清理。"""
        record = self.active
        if record is None or record._task is None:
            return

        task = record._task
        if not task.done():
            record.append_log("WARN", "应用正在更新或退出，当前采集任务已停止")
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        # create_task 后若任务尚未获得过执行机会，协程自己的 finally 不会运行。
        if record.state in (JobState.PENDING, JobState.RUNNING):
            record.state = JobState.CANCELLED
            record.error = "任务已取消"
            record.finished_at = datetime.utcnow()
        if self._active_id == record.id:
            self._active_id = None

    async def _run(self, record: JobRecord, config: AppConfig) -> None:
        record.state = JobState.RUNNING
        record.started_at = datetime.utcnow()
        record.append_log("INFO", "开始采集：正在启动采集环境…")

        handler = _JobLogHandler(record)
        root = logging.getLogger()
        # 保证 captcha/crawler 的 INFO 能冒泡到 root（默认可能是 WARNING）
        touched: list[tuple[logging.Logger, int]] = []
        for name in (
            "captcha",
            "crawler",
            "app.services.crawl",
            "app.browser",
            "app.crawlers",
            "app.services.crawl_jobs",
        ):
            lg = logging.getLogger(name)
            touched.append((lg, lg.level))
            if lg.level == logging.NOTSET or lg.level > logging.INFO:
                lg.setLevel(logging.INFO)
        root.addHandler(handler)
        try:
            result = await run_crawl(record.job, config)
            record.result = result
            visible_count, hidden_count = _result_ledger_counts(result)
            result_summary = (
                f"入库 {result.show_count} 条、台账可见 {visible_count} 条、"
                f"隐藏{_LEDGER_HIDDEN_LABEL} {hidden_count} 条"
            )
            if result.errors:
                record.state = JobState.FAILED
                translated_errors = [translate_task_error(err) for err in result.errors]
                record.error = "；".join(translated_errors)
                for err in translated_errors:
                    # run_crawl normally logged "crawler failed: <err>" already. Only
                    # synthesize a row for alternate implementations that returned an
                    # error without logging it, so the console does not show duplicates.
                    if not any(
                        row.get("level") == "ERROR" and err in (row.get("text") or "")
                        for row in record.logs
                    ):
                        record.append_log("ERROR", err)
                record.append_log(
                    "ERROR",
                    f"采集失败：{result_summary} / 原始 {result.raw_count} 条",
                )
            else:
                record.state = JobState.SUCCEEDED
                record.append_log(
                    "INFO",
                    f"采集完成：{result_summary} / 原始 {result.raw_count} 条",
                )
            logger.info(
                "crawl job done id=%s shows=%s ledger_visible=%s ledger_hidden=%s errors=%s",
                record.id,
                result.show_count,
                visible_count,
                hidden_count,
                len(result.errors),
            )
        except asyncio.CancelledError:
            record.state = JobState.CANCELLED
            record.error = "任务已取消"
            record.append_log("WARN", "任务已取消")
            logger.info("crawl job cancelled id=%s", record.id)
            raise
        except Exception as exc:  # noqa: BLE001
            record.state = JobState.FAILED
            record.error = translate_task_error(str(exc))
            record.append_log("ERROR", f"任务异常中断：{record.error}")
            logger.exception("crawl job failed id=%s: %s", record.id, exc)
        finally:
            root.removeHandler(handler)
            for lg, prev in touched:
                lg.setLevel(prev)
            record.finished_at = datetime.utcnow()
            if self._active_id == record.id:
                self._active_id = None


# 进程内单例
_manager: Optional[CrawlJobManager] = None


def get_job_manager() -> CrawlJobManager:
    global _manager
    if _manager is None:
        _manager = CrawlJobManager()
    return _manager


async def shutdown_job_manager() -> None:
    """FastAPI lifespan 使用；未创建管理器时不为关机额外创建实例。"""
    if _manager is not None:
        await _manager.shutdown()
