"""采集触发与进度查询路由。

只读查询在 shows.py；这里负责"触发一次采集"这一写操作。
采集是长任务（开浏览器、可能人工过验证码），所以：
  POST /api/crawl        提交任务，立即返回 job_id（不阻塞）
  GET  /api/crawl        列出历史任务
  GET  /api/crawl/active 当前正在跑的任务（前端轮询用）
  GET  /api/crawl/{id}   单个任务状态
  POST /api/crawl/{id}/cancel  取消

单客户 + 有头浏览器：同时只允许一个采集任务在跑。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import CrawlJob, SourcePlatform
from app.services.crawl_jobs import get_job_manager

router = APIRouter(prefix="/api/crawl")


class CrawlRequest(BaseModel):
    """前端提交的采集参数。不传的字段回退配置文件默认值。"""

    sources: list[str] = Field(default_factory=lambda: ["damai", "maoyan", "showstart"])
    cities: Optional[list[str]] = None
    keywords: Optional[list[str]] = None
    # 单平台分类；大麦对应 ctl，猫眼对应 categoryId，秀动对应 showStyle；空值表示全部分类。
    category: str = Field(default="", max_length=50)
    # 每个城市/关键词最多翻页数。
    # None / 0 = 不限制，跟大麦 totalPage 采完全部；正整数 = 硬上限。
    max_pages: Optional[int] = Field(default=None, ge=0, le=9999)
    # 详情补全（场次/票档/场馆）由后端固定开启，不接受前端控制，故此处无字段。
    # 默认有头：大麦几乎必弹验证码，需要弹窗让客户手动拖滑块。
    # 设 false 走无头（仅适合已有 cookie、确信不触发验证码时）。
    headed: bool = True


def _parse_sources(sources: list[str]) -> list[SourcePlatform]:
    out: list[SourcePlatform] = []
    for s in sources:
        key = s.strip().lower()
        if key in ("all", ""):
            return [SourcePlatform.DAMAI, SourcePlatform.MAOYAN, SourcePlatform.SHOWSTART]
        if key in ("damai", "大麦"):
            out.append(SourcePlatform.DAMAI)
        elif key in ("maoyan", "猫眼"):
            out.append(SourcePlatform.MAOYAN)
        elif key in ("showstart", "秀动"):
            out.append(SourcePlatform.SHOWSTART)
        else:
            raise HTTPException(status_code=400, detail=f"未知数据源: {s}")
    if not out:
        return [SourcePlatform.DAMAI, SourcePlatform.MAOYAN, SourcePlatform.SHOWSTART]
    return out


def _category_for_sources(sources: list[SourcePlatform], category: str) -> str:
    """分类体系不跨平台共享，多平台任务强制按全部分类执行。"""
    return category.strip() if len(sources) == 1 else ""


@router.post("")
async def start_crawl(req: CrawlRequest) -> dict:
    """提交一次采集任务。已有任务在跑时返回 409。"""
    from app.core.config import load_config

    cfg = load_config()
    sources = _parse_sources(req.sources)
    cities = req.cities if req.cities else list(cfg.crawl.cities)
    keywords = req.keywords if req.keywords is not None else list(cfg.crawl.keywords)
    # 多平台任务不共享分类体系；仅单平台任务接受分类筛选。
    category = _category_for_sources(sources, req.category)
    # 前端约定：不传 / null / 0 → 全量（job.max_pages=0）；正整数 → 上限
    # 不再回退配置文件的 max_pages:3，避免「留空却只采 3 页」
    if req.max_pages is None or req.max_pages == 0:
        max_pages = 0
    else:
        max_pages = int(req.max_pages)

    # 覆盖 browser.headless：前端 headed=true → headless=false（弹窗手动拖滑块）
    cfg.browser.headless = not req.headed

    job = CrawlJob(
        sources=sources,
        cities=cities,
        keywords=keywords,
        category=category,
        max_pages=max_pages,
        enrich_detail=True,  # 详情补全固定开启，不由前端控制
    )

    manager = get_job_manager()
    try:
        record = await manager.submit(job, cfg)
    except RuntimeError as exc:
        # 已有任务在跑
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return record.to_dict()


@router.get("")
def list_crawls() -> dict:
    manager = get_job_manager()
    return {"items": [r.to_dict() for r in manager.list()]}


@router.get("/active")
def active_crawl() -> dict:
    """当前正在跑的任务；无则 active=null。前端轮询这个刷新进度。"""
    manager = get_job_manager()
    active = manager.active
    return {"active": active.to_dict() if active else None}


@router.get("/{job_id}")
def get_crawl(job_id: str) -> dict:
    manager = get_job_manager()
    record = manager.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return record.to_dict()


@router.post("/{job_id}/cancel")
async def cancel_crawl(job_id: str) -> dict:
    manager = get_job_manager()
    record = manager.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    ok = await manager.cancel(job_id)
    return {"cancelled": ok, "job": record.to_dict()}
