"""演出数据查询与导出路由。

只读本地固定 SQLite 库，供本地前端查询、导出 CSV/Excel。
"""

from __future__ import annotations

import urllib.parse
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from app.core.config import load_config
from app.repositories.show_repo import ShowQuery, ShowRepository
from app.services.export import to_csv, to_xlsx
from app.utils.holiday import holiday_label
from app.utils.showstate import performance_status

router = APIRouter(prefix="/api")


def _enrich(show: dict) -> dict:
    """给一条 Show 注入派生展示字段：节假日 + 演出状态（按时间比较）。

    这两列都依赖运行时上下文（节假日表 / 当前日期），不落库，
    查询时即时计算，保证查询页与导出口径一致。
    """
    start = show.get("start_time")
    show["holiday"] = holiday_label(start)
    show["perf_state"] = performance_status(start, raw_status=show.get("status"))
    return show


def _repo() -> ShowRepository:
    cfg = load_config()
    return ShowRepository(cfg.storage.db_path)


@router.get("/health")
def health() -> dict:
    repo = _repo()
    return {"status": "ok", "db": str(repo._db_path), "db_exists": repo.exists()}


@router.get("/stats")
def get_stats() -> dict:
    repo = _repo()
    return repo.stats()


@router.get("/facets")
def facets() -> dict:
    repo = _repo()
    return repo.facets()


@router.get("/cities")
def list_cities() -> list[str]:
    repo = _repo()
    return repo.facets().get("city", [])


@router.get("/shows")
def list_shows(
    source: Optional[str] = None,
    city: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    perf_state: Optional[str] = Query(None, pattern="^(upcoming|ongoing|done|cancelled)$"),
    keyword: Optional[str] = None,
    sort_by: str = "start_time",
    descending: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    repo = _repo()
    if not repo.exists():
        return {"total": 0, "items": [], "limit": limit, "offset": offset}
    q = ShowQuery(
        source=source,
        city=city,
        category=category,
        status=status,
        perf_state=perf_state,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    total = repo.count(q)
    items = [_enrich(s) for s in repo.list_shows(q, sort_by=sort_by, descending=descending)]
    return {"total": total, "items": items, "limit": limit, "offset": offset}


@router.get("/shows/{show_id}")
def get_show(show_id: str) -> dict:
    repo = _repo()
    show = repo.get_show(show_id) if repo.exists() else None
    if show is None:
        raise HTTPException(status_code=404, detail="show not found")
    return _enrich(show)


class ClearRequest(BaseModel):
    """清除数据请求。scope 决定范围，与导出的三态语义对齐：

    - all：整库清空（shows / raw_items / crawl_runs），保留城市预设与设置。
    - selected：只删勾选的 ids（忽略筛选条件）。
    - filtered：删全部匹配筛选条件的记录。
    """

    scope: str = "all"
    ids: Optional[str] = None
    source: Optional[str] = None
    city: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    perf_state: Optional[str] = None
    keyword: Optional[str] = None


@router.post("/data/clear")
def clear_data(req: ClearRequest | None = None) -> dict:
    """按范围清除采集数据。

    保留预设城市与设置，只删采集产物，并回收磁盘空间。
    用 POST 而非 DELETE：本地 CORS 只放开 GET/POST（见 main.py）。
    不传 body 时默认整库清空，兼容旧前端调用。
    """
    repo = _repo()
    req = req or ClearRequest()
    if req.scope == "all":
        deleted = repo.clear_data()
        return {"success": True, "deleted": deleted}

    if req.scope == "selected":
        id_list = [i for i in req.ids.split(",") if i] if req.ids else None
        if not id_list:
            raise HTTPException(status_code=400, detail="未指定要清除的记录")
        deleted = repo.delete_shows(ShowQuery(), ids=id_list)
    else:  # filtered
        q = ShowQuery(
            source=req.source, city=req.city, category=req.category,
            status=req.status, perf_state=req.perf_state, keyword=req.keyword,
        )
        deleted = repo.delete_shows(q)
    return {"success": True, "deleted": deleted}


@router.get("/export")
def export(
    fmt: str = Query("csv", pattern="^(csv|xlsx)$"),
    source: Optional[str] = None,
    city: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    perf_state: Optional[str] = Query(None, pattern="^(upcoming|ongoing|done|cancelled)$"),
    keyword: Optional[str] = None,
    ids: Optional[str] = None,
) -> Response:
    repo = _repo()
    if not repo.exists():
        raise HTTPException(status_code=404, detail="数据库不存在，请先运行采集")
    # ids 非空（前端勾选导出）时只导这些行，忽略筛选条件
    id_list = [i for i in ids.split(",") if i] if ids else None
    q = ShowQuery(
        source=source, city=city, category=category, status=status,
        perf_state=perf_state, keyword=keyword,
    )
    shows = repo.iter_for_export(q, ids=id_list)

    if fmt == "csv":
        data = to_csv(shows)
        media = "text/csv; charset=utf-8"
        filename = "shows.csv"
    else:
        data = to_xlsx(shows)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "shows.xlsx"

    # RFC 5987：文件名支持中文/非 ASCII（这里是固定名，保持一致做法）
    disp = f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"
    return Response(content=data, media_type=media, headers={"Content-Disposition": disp})
