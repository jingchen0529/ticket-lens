"""统一演出数据模型。

各平台 crawler 产出 `RawShowItem`，经 pipeline 规范化为 `Show`。
对外只暴露 `Show`，保证下游存储/分析字段一致。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SourcePlatform(str, Enum):
    DAMAI = "damai"
    MAOYAN = "maoyan"


class ShowStatus(str, Enum):
    """票务状态（尽量映射到统一枚举，未知则 UNKNOWN）。"""

    ONSALE = "onsale"  # 在售
    PRESALE = "presale"  # 预售
    SOLD_OUT = "sold_out"  # 售罄
    DELAYED = "delayed"  # 延期
    CANCELLED = "cancelled"  # 取消
    ENDED = "ended"  # 已结束
    UNKNOWN = "unknown"


class Venue(BaseModel):
    name: str = ""
    city: str = ""
    address: str = ""
    # 经纬度可选
    lat: float | None = None
    lng: float | None = None


class PriceRange(BaseModel):
    currency: str = "CNY"
    min_price: float | None = None
    max_price: float | None = None
    # 原始展示文案，如 "280-1280" / "票价待定"
    raw: str = ""


class TicketTier(BaseModel):
    """票档（某一场次下的价格档）。"""

    sku_id: str = ""
    name: str = ""  # 如 N（80元）/ 180.0元
    price: float | None = None
    status: str = ""  # onsale / sold_out / presale / unknown
    salable: bool = False
    raw: str = ""


class ShowSession(BaseModel):
    """场次信息（一场演出可能有多场次）。"""

    session_id: str = ""
    name: str = ""  # 场次展示名，如 2026-08-14 星期五 19:30【…】
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: ShowStatus = ShowStatus.UNKNOWN
    raw_time: str = ""
    ticket_tiers: list[TicketTier] = Field(default_factory=list)


class RawShowItem(BaseModel):
    """平台原始抓取结果，字段尽量宽松，不做强校验。"""

    source: SourcePlatform
    source_id: str = ""
    url: str = ""
    title: str = ""
    city: str = ""
    venue_name: str = ""
    venue_address: str = ""
    category: str = ""
    artists: list[str] = Field(default_factory=list)
    poster_url: str = ""
    price_raw: str = ""
    status_raw: str = ""
    start_time_raw: str = ""
    end_time_raw: str = ""
    sessions_raw: list[dict[str, Any]] = Field(default_factory=list)
    # 原始 HTML/JSON 片段，便于排错与二次解析
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    crawled_at: datetime = Field(default_factory=datetime.utcnow)


class Show(BaseModel):
    """统一后的演出实体 —— 系统最终产物。"""

    # 稳定主键：{source}:{source_id}
    id: str
    source: SourcePlatform
    source_id: str
    url: str = ""

    title: str
    subtitle: str = ""
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    artists: list[str] = Field(default_factory=list)

    venue: Venue = Field(default_factory=Venue)
    price: PriceRange = Field(default_factory=PriceRange)
    status: ShowStatus = ShowStatus.UNKNOWN

    # 主时间：取首场/列表展示时间
    start_time: datetime | None = None
    end_time: datetime | None = None
    sessions: list[ShowSession] = Field(default_factory=list)

    poster_url: str = ""
    description: str = ""

    crawled_at: datetime = Field(default_factory=datetime.utcnow)
    normalized_at: datetime = Field(default_factory=datetime.utcnow)

    # 溯源：保留部分原始字段
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("title is required")
        return v

    @classmethod
    def make_id(cls, source: SourcePlatform, source_id: str) -> str:
        return f"{source.value}:{source_id}"


class CrawlJob(BaseModel):
    """一次采集任务描述。"""

    sources: list[SourcePlatform] = Field(
        default_factory=lambda: [SourcePlatform.DAMAI, SourcePlatform.MAOYAN]
    )
    cities: list[str] = Field(default_factory=lambda: ["北京"])
    keywords: list[str] = Field(default_factory=list)
    # 单平台分类；大麦映射 ctl，猫眼映射 categoryId；空字符串 = 全部分类。
    # 多平台任务不共享分类体系，必须为空。
    category: str = ""
    # 每个城市/关键词页数上限；0 = 不限制（跟列表 totalPage 采完）
    max_pages: int = 0
    # 列表拿到链接后是否再拉详情（场次/票档/场馆）
    enrich_detail: bool = True


class CrawlResult(BaseModel):
    """一次运行的汇总结果。"""

    job: CrawlJob
    started_at: datetime
    finished_at: datetime | None = None
    raw_count: int = 0
    show_count: int = 0
    # show_count 是实际规范化入库行；台账查询固定隐藏展览休闲/体育，单独保留
    # 可见与隐藏口径，避免任务结果看起来与数据查看页不一致。
    ledger_visible_count: int | None = None
    ledger_hidden_count: int | None = None
    ledger_hidden_by_category: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    output_path: str = ""
