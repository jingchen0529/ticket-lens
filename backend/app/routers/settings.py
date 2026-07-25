"""系统设置路由：冰拓账号、主题配色等前端配置持久化。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings")


class BingtuoCredentials(BaseModel):
    """冰拓验证码平台账号密码。"""
    username: str = ""
    password: str = ""


class SettingsData(BaseModel):
    """前端可配置的系统设置。"""
    bingtuo: BingtuoCredentials = BingtuoCredentials()
    theme_color: str = "#eb4f9a"
    fruit_captcha_type: int = 1358
    # 过码模式：auto=自动过码（先本地/打码，失败人工兜底）| manual=手动过码（直接弹窗人工拖滑块）
    captcha_mode: str = "auto"


def _settings_path() -> Path:
    """本地设置持久化路径（用户目录）。"""
    from app.core import paths
    return paths.data_dir() / "frontend_settings.yaml"


def _load_settings() -> SettingsData:
    """从磁盘加载前端设置。"""
    path = _settings_path()
    if not path.exists():
        return SettingsData()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return SettingsData.model_validate(data)
    except Exception:
        return SettingsData()


def _save_settings(settings: SettingsData) -> None:
    """保存设置到磁盘。"""
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(settings.model_dump(), f, allow_unicode=True, default_flow_style=False)


@router.get("")
def get_settings() -> dict:
    """获取当前系统设置。"""
    settings = _load_settings()
    return settings.model_dump()


@router.post("")
def update_settings(req: SettingsData) -> dict:
    """更新系统设置并持久化到磁盘。"""
    try:
        _save_settings(req)

        # 同步更新 config.yaml 中的冰拓配置（供后端采集引擎使用）
        from app.core.config import load_config
        from app.core import paths

        cfg_path = paths.config_path()
        if cfg_path.exists():
            with cfg_path.open("r", encoding="utf-8") as f:
                cfg_data = yaml.safe_load(f) or {}
        else:
            cfg_data = {}

        # 更新冰拓凭据到 captcha.username 和 captcha.password
        if "captcha" not in cfg_data:
            cfg_data["captcha"] = {}

        cfg_data["captcha"]["username"] = req.bingtuo.username
        cfg_data["captcha"]["password"] = req.bingtuo.password

        # 如果填了冰拓账号，自动切换 provider 为 bingtop
        if req.bingtuo.username and req.bingtuo.password:
            cfg_data["captcha"]["provider"] = "bingtop"

        # 同步水果滑块类型
        cfg_data["captcha"]["fruit_captcha_type"] = req.fruit_captcha_type

        # 过码模式：manual=手动过码（关闭自动，直接人工拖滑块）；auto=自动过码
        cfg_data["captcha"]["auto"] = req.captcha_mode != "manual"

        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        with cfg_path.open("w", encoding="utf-8") as f:
            yaml.dump(cfg_data, f, allow_unicode=True, default_flow_style=False)

        return {"success": True, "settings": req.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存设置失败: {str(e)}")


@router.get("/bingtuo")
def get_bingtuo_credentials() -> dict:
    """单独获取冰拓账号配置（敏感信息，密码脱敏）。"""
    settings = _load_settings()
    return {
        "username": settings.bingtuo.username,
        "password": "••••••••" if settings.bingtuo.password else "",
        "has_password": bool(settings.bingtuo.password)
    }


@router.get("/bingtuo/balance")
async def get_bingtuo_balance() -> dict:
    """查询冰拓剩余打码点数。

    调冰拓官方接口 POST /ocr/check_points/（username+password → data.points）。
    未配置账号时返回 configured=False，供前端提示先填账号。
    """
    import httpx

    settings = _load_settings()
    username = settings.bingtuo.username
    password = settings.bingtuo.password
    if not username or not password:
        return {"configured": False, "points": None, "error": "未配置冰拓账号"}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://www.bingtop.com/ocr/check_points/",
                data={"username": username, "password": password},
            )
            resp.raise_for_status()
            body = resp.json()
    except Exception as e:  # noqa: BLE001
        return {"configured": True, "points": None, "error": f"查询失败: {e}"}

    if not isinstance(body, dict) or body.get("code") not in (0, "0"):
        msg = (body or {}).get("message") if isinstance(body, dict) else ""
        return {"configured": True, "points": None, "error": msg or "冰拓返回异常"}

    data = body.get("data") or {}
    return {"configured": True, "points": data.get("points"), "error": ""}
