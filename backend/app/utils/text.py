"""文本清洗工具。"""

from __future__ import annotations

import re


_WS_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return _WS_RE.sub(" ", value).strip()


def split_artists(raw: str | None) -> list[str]:
    """把「周杰伦/林俊杰」「A、B、C」等拆成列表。"""
    if not raw:
        return []
    text = clean_text(raw)
    parts = re.split(r"[/|、,，&＋+]+", text)
    return [p.strip() for p in parts if p.strip()]


def clean_poster_url(value: str | None) -> str:
    """清洗海报 URL。

    大麦 API 的 verticalPic 常是「双拼」脏数据，形如
    `https://img.alicdn.com/bao/uploaded/https://img.alicdn.com/imgextra/...jpg`
    —— 前缀又接了一个完整 URL。取最后一个 http(s) 段即真实地址。
    """
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # 找最后一个 http:// 或 https:// 的位置，从那里截断
    idx = max(s.rfind("http://"), s.rfind("https://"))
    if idx > 0:
        s = s[idx:]
    # 协议相对地址补 https:
    if s.startswith("//"):
        s = "https:" + s
    return s
