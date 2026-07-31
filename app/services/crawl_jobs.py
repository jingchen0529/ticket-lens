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

logger = logging.getLogger(__name__)

# 前端 Console 只关心采集/验证码相关 logger，避免 uvicorn access 刷屏
_LOG_NAME_PREFIXES = (
    "captcha.",
    "crawler.",
    "app.services.crawl",
    "app.browser.",
    "app.crawlers.",
)
_MAX_JOB_LOGS = 300


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
            # 过长堆栈只留首行，避免 Console 被 traceback 淹没
            text = str(msg).strip()
            if "\n" in text:
                text = text.split("\n", 1)[0].strip()
            if len(text) > 500:
                text = text[:497] + "..."
            self._record.append_log(_level_name(log_record.levelno), text)
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
        return {
            "raw_count": r.raw_count,
            "show_count": r.show_count,
            "by_source": r.by_source,
            "errors": r.errors,
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
            detail_label = "开" if getattr(job, "enrich_detail", True) else "关"
            record.append_log(
                "INFO",
                f"任务已提交 id={record.id[:8]} 城市={cities} 页数={pages_label} 详情补全={detail_label}",
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

    async def _run(self, record: JobRecord, config: AppConfig) -> None:
        record.state = JobState.RUNNING
        record.started_at = datetime.utcnow()
        record.append_log("INFO", "开始采集：启动浏览器并进入大麦搜索…")

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
            record.state = JobState.SUCCEEDED
            if result.errors:
                for err in result.errors:
                    record.append_log("ERROR", err)
                record.append_log(
                    "WARN",
                    f"采集结束（含错误）入库 {result.show_count} 条 / 原始 {result.raw_count} 条",
                )
            else:
                record.append_log(
                    "INFO",
                    f"采集完成：入库 {result.show_count} 条 / 原始 {result.raw_count} 条",
                )
            logger.info(
                "crawl job done id=%s shows=%s errors=%s",
                record.id, result.show_count, len(result.errors),
            )
        except asyncio.CancelledError:
            record.state = JobState.CANCELLED
            record.error = "任务已取消"
            record.append_log("WARN", "任务已取消")
            logger.info("crawl job cancelled id=%s", record.id)
            raise
        except Exception as exc:  # noqa: BLE001
            record.state = JobState.FAILED
            record.error = str(exc)
            record.append_log("ERROR", f"任务异常中断: {exc}")
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
