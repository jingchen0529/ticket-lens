"""第三方打码平台适配（国内优先，海外可选）。

支持：
- bingtop    冰拓 https://www.bingtop.com  （国内，适合水果滑块 1357/1359）
- chaojiying 超级鹰 https://www.chaojiying.com （国内，坐标/缺口 9900）
- yunma      云码 https://www.jfbym.com    （国内，通用滑块缺口）
- capsolver  https://www.capsolver.com     （海外，需外币）
- twocaptcha https://2captcha.com          （海外）

未配置凭证时不会调用。大麦水果滑块默认仍走本地打分，配置 provider 后可优先/回退调用打码。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _strip_data_url(b64_or_data: str) -> str:
    """去掉 data:image/...;base64, 前缀。"""
    if not b64_or_data:
        return ""
    s = b64_or_data.strip()
    if s.startswith("data:") and "," in s:
        return s.split(",", 1)[1]
    return s


def to_b64(raw: bytes | str) -> str:
    """bytes 或 data-url/纯 base64 → 纯 base64 字符串。"""
    if isinstance(raw, bytes):
        return base64.b64encode(raw).decode("ascii")
    return _strip_data_url(raw)


# 兼容旧内部名
_to_b64 = to_b64

# JPEG / PNG / GIF / WEBP 魔数
_IMAGE_MAGICS = (
    b"\xff\xd8\xff",  # jpeg
    b"\x89PNG\r\n\x1a\n",  # png
    b"GIF87a",
    b"GIF89a",
    b"RIFF",  # webp 需再看 WEBP
)


def is_valid_image_bytes(raw: bytes | None, *, min_size: int = 200) -> bool:
    """粗校验是否为可识别的图片二进制（避免把截图条/HTML 当主图烧点）。"""
    if not raw or len(raw) < min_size:
        return False
    if raw[:3] == b"\xff\xd8\xff":
        return True
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if raw[:4] == b"RIFF" and len(raw) >= 12 and raw[8:12] == b"WEBP":
        return True
    return False


def is_valid_image_b64(b64: str | None, *, min_size: int = 200) -> bool:
    if not b64:
        return False
    try:
        raw = base64.b64decode(_strip_data_url(b64), validate=False)
    except Exception:  # noqa: BLE001
        return False
    return is_valid_image_bytes(raw, min_size=min_size)


def image_meta(b64_or_bytes: bytes | str | None) -> dict[str, Any]:
    """调试用：长度 + 魔数，不打印整段 base64。"""
    if b64_or_bytes is None:
        return {"ok": False, "reason": "none"}
    if isinstance(b64_or_bytes, bytes):
        raw = b64_or_bytes
        b64_len = len(base64.b64encode(raw))
    else:
        s = _strip_data_url(b64_or_bytes)
        b64_len = len(s)
        try:
            raw = base64.b64decode(s, validate=False)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"b64:{exc}", "b64_len": b64_len}
    ok = is_valid_image_bytes(raw)
    return {
        "ok": ok,
        "raw_len": len(raw),
        "b64_len": b64_len,
        "magic": raw[:8].hex() if raw else "",
    }


def _parse_first_number(text: str | None) -> float | None:
    """从识别结果里抠第一个数字（支持 123 / 123.4 / 123,45 / 123|0）。

    拒绝明显非距离串（如冰拓失败占位 jz3sz / error），避免误抽其中的单个数字。
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    low = s.lower()
    if low in {"error", "fail", "failed", "null", "none", "n/a"} or re.search(
        r"(?:error|fail(?:ed)?|错误|失败)\s*[:：=]?\s*-?\d", low
    ):
        return None
    # 坐标形式 x,y 或 x|y → 取 x
    for sep in ("|", ",", "，", " "):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            break
    # 整段就是数字
    if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        try:
            return float(s)
        except ValueError:
            return None
    # 允许「距离:188」类；拒绝字母数字混杂无分隔的乱码
    if re.search(r"[A-Za-z]", s) and not re.search(r"[=:：]\s*-?\d", s):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


class CaptchaProvider(ABC):
    name: str

    def __init__(self, *, timeout: float = 60.0) -> None:
        self.timeout = timeout

    @abstractmethod
    async def solve_image(self, image_b64: str, *, question: str = "") -> str | None:
        """识别图文验证码，返回文本答案。"""

    @abstractmethod
    async def solve_slider_gap(self, bg_b64: str, slice_b64: str = "") -> float | None:
        """识别滑块缺口 x 偏移（像素，相对背景图）。"""

    async def solve_fruit_offset(self, image_b64: str, ques_b64: str = "") -> float | None:
        """识别水果滑块目标位移（相对 imageData 逻辑宽，通常 0~320）。

        默认回退到 solve_slider_gap；国内平台可覆盖。
        """
        return await self.solve_slider_gap(image_b64, ques_b64)


class BingtopProvider(CaptchaProvider):
    """冰拓打码（国内，支付宝/微信充值）。

    水果滑块 / 拖拽式图像：
    - **1358**（推荐，2 点）：主图 + 标题双图
      captchaData=imageData，subCaptchaData=ques
      recognition=「目标图形右侧 → 图片左侧」距离（≈ image 逻辑 x1）
      拖滑块时必须 map：ui_x ≈ recognition - 24（见 map_bingtop_fruit_offset_to_ui）
    - 1357：主图 + 标题（旧专属 api2/type1357，语义接近）
    - 1359：单图拖动距离
    - 1318：单图缺口 x
    """

    name = "bingtop"
    upload_url = "https://www.bingtop.com/ocr/upload/"
    # 仅 1357 旧专属口；1358 走通用 /ocr/upload/
    type1357_url_https = "https://api2.bingtop.com/type1357/"
    # 必须双图的类型：缺 sub 或非图绝不上传，避免烧点
    DUAL_IMAGE_TYPES = frozenset({1357, 1358})

    def __init__(
        self,
        username: str,
        password: str,
        *,
        fruit_type: int = 1358,
        gap_type: int = 1318,
        dual_gap_type: int = 1316,
        timeout: float = 100.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.username = username
        self.password = password
        self.fruit_type = int(fruit_type)
        self.gap_type = int(gap_type)
        self.dual_gap_type = int(dual_gap_type)

    async def solve_image(self, image_b64: str, *, question: str = "") -> str | None:
        data = await self._upload(
            captcha_type=1001,
            captcha_data=_strip_data_url(image_b64),
            sub=_strip_data_url(question) if question and len(question) > 40 else (question or None),
        )
        return data

    async def solve_slider_gap(self, bg_b64: str, slice_b64: str = "") -> float | None:
        bg = _strip_data_url(bg_b64)
        sl = _strip_data_url(slice_b64) if slice_b64 else ""
        if sl:
            text = await self._upload(
                captcha_type=self.dual_gap_type,
                captcha_data=bg,
                sub=sl,
            )
        else:
            text = await self._upload(captcha_type=self.gap_type, captcha_data=bg)
        return _parse_first_number(text)

    async def solve_fruit_offset(self, image_b64: str, ques_b64: str = "") -> float | None:
        """水果 / 拖拽题：默认 1358 双图。

        必须用 newslidecaptcha 的 imageData + ques 解码后的真实图片 base64，
        禁止把 DOM 截图条当主图。
        """
        img = _strip_data_url(image_b64)
        ques = _strip_data_url(ques_b64) if ques_b64 else ""
        ctype = int(self.fruit_type)

        if ctype in self.DUAL_IMAGE_TYPES:
            if not img or not ques:
                logger.warning(
                    "bingtop type=%s needs captchaData+subCaptchaData; img_ok=%s sub_ok=%s meta=%s/%s",
                    ctype,
                    bool(img),
                    bool(ques),
                    image_meta(img),
                    image_meta(ques),
                )
                return None
            if not is_valid_image_b64(img) or not is_valid_image_b64(ques):
                logger.warning(
                    "bingtop type=%s refuse non-image payload meta_main=%s meta_sub=%s",
                    ctype,
                    image_meta(img),
                    image_meta(ques),
                )
                return None
            logger.info(
                "bingtop dual upload type=%s main=%s sub=%s",
                ctype,
                image_meta(img),
                image_meta(ques),
            )
            # 1358：通用 upload；1357：可先试专属口再通用
            if ctype == 1357:
                text = await self._upload_type1357(captcha_data=img, sub=ques)
                if text is not None:
                    return _parse_first_number(text)
            text = await self._upload(captcha_type=ctype, captcha_data=img, sub=ques)
            return _parse_first_number(text)

        # 单图类型（1359 等）
        if not is_valid_image_b64(img):
            logger.warning("bingtop type=%s refuse non-image main=%s", ctype, image_meta(img))
            return None
        text = await self._upload(
            captcha_type=ctype,
            captcha_data=img,
            sub=ques if ques and ctype != 1359 else None,
        )
        return _parse_first_number(text)

    async def _upload_type1357(self, *, captcha_data: str, sub: str) -> str | None:
        """旧 1357 专属接口（主图 + 标题）。"""
        if not self.username or not self.password or not captcha_data or not sub:
            return None
        form: dict[str, Any] = {
            "username": self.username,
            "password": self.password,
            "captchaData": captcha_data,
            "subCaptchaData": sub,
            "captchaType": 1357,
        }
        url = self.type1357_url_https
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, data=form)
                r.raise_for_status()
                body = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("bingtop type1357 request failed: %s", exc)
            return None
        return self._parse_recognition(body, captcha_type=1357, url=url)

    @staticmethod
    def _safe_response_meta(body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            return {"type": type(body).__name__}
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        return {
            "code": body.get("code"),
            "message": str(body.get("message") or "")[:120],
            "captchaId": data.get("captchaId"),
            "recognition_type": type(data.get("recognition")).__name__,
        }

    def _parse_recognition(self, body: Any, *, captcha_type: int, url: str) -> str | None:
        if not isinstance(body, dict):
            logger.warning(
                "bingtop non-json type=%s url=%s response=%s",
                captcha_type,
                url,
                self._safe_response_meta(body),
            )
            return None
        # 常见：{"code":0,"data":{"recognition":"188",...}}
        code = body.get("code")
        explicit_failure = body.get("success") is False or body.get("status") in (
            False,
            "false",
            "fail",
            "failed",
            "error",
        )
        bad_code = code not in (0, "0", None, 200, "200")
        if explicit_failure or bad_code:
            logger.warning(
                "bingtop error type=%s url=%s response=%s",
                captcha_type,
                url,
                self._safe_response_meta(body),
            )
            return None
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        rec = None
        if isinstance(data, dict):
            for key in ("recognition", "result", "distance", "x"):
                if key in data and data[key] is not None:
                    rec = data[key]
                    break
        if rec is None:
            rec = body.get("recognition") or body.get("result")
        if rec is None:
            logger.warning(
                "bingtop empty recognition type=%s url=%s response=%s",
                captcha_type,
                url,
                self._safe_response_meta(body),
            )
            return None
        if str(rec).strip().lower() in {"error", "fail", "failed", "null", "none"}:
            logger.warning(
                "bingtop recognition error type=%s url=%s response=%s",
                captcha_type,
                url,
                self._safe_response_meta(body),
            )
            return None
        if _parse_first_number(str(rec)) is None:
            logger.warning(
                "bingtop non-numeric recognition type=%s url=%s rec=%s",
                captcha_type,
                url,
                str(rec)[:40],
            )
            return None
        logger.info(
            "bingtop ok type=%s url=%s captchaId=%s recognition=%s",
            captcha_type,
            url,
            (data.get("captchaId") if isinstance(data, dict) else None),
            str(rec)[:40],
        )
        return str(rec)

    async def _upload(
        self,
        *,
        captcha_type: int,
        captcha_data: str,
        sub: str | None = None,
    ) -> str | None:
        if not self.username or not self.password or not captcha_data:
            return None
        if int(captcha_type) in self.DUAL_IMAGE_TYPES and not sub:
            logger.warning("bingtop type=%s missing subCaptchaData, skip upload", captcha_type)
            return None
        form: dict[str, Any] = {
            "username": self.username,
            "password": self.password,
            "captchaData": captcha_data,
            "captchaType": int(captcha_type),
        }
        if sub:
            form["subCaptchaData"] = sub

        url = self.upload_url
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, data=form)
                r.raise_for_status()
                body = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("bingtop request failed: %s", exc)
            return None
        return self._parse_recognition(body, captcha_type=int(captcha_type), url=url)


class ChaojiyingProvider(CaptchaProvider):
    """超级鹰（国内）。

    常用类型：
    - 9900：滑块/缺口/色块定位
    - 9101：醒目提示单坐标
    - 1004：英文数字
    """

    name = "chaojiying"
    upload_url = "https://upload.chaojiying.net/Upload/Processing.php"

    def __init__(
        self,
        username: str,
        password: str,
        soft_id: str,
        *,
        fruit_type: int = 9900,
        gap_type: int = 9900,
        image_type: int = 1004,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.username = username
        self.password = password
        self.soft_id = soft_id
        self.fruit_type = int(fruit_type)
        self.gap_type = int(gap_type)
        self.image_type = int(image_type)

    async def solve_image(self, image_b64: str, *, question: str = "") -> str | None:
        return await self._upload(_strip_data_url(image_b64), self.image_type)

    async def solve_slider_gap(self, bg_b64: str, slice_b64: str = "") -> float | None:
        # 超级鹰通常单图；有 gap 时拼图优先传背景
        text = await self._upload(_strip_data_url(bg_b64), self.gap_type)
        return _parse_first_number(text)

    async def solve_fruit_offset(self, image_b64: str, ques_b64: str = "") -> float | None:
        text = await self._upload(_strip_data_url(image_b64), self.fruit_type)
        return _parse_first_number(text)

    async def _upload(self, image_b64: str, codetype: int) -> str | None:
        if not self.username or not self.password or not image_b64:
            return None
        form = {
            "user": self.username,
            "pass": self.password,
            "softid": self.soft_id,
            "codetype": codetype,
            "file_base64": image_b64,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(self.upload_url, data=form)
                r.raise_for_status()
                body = r.json()
            # err_no == 0 成功；pic_str 为结果
            if body.get("err_no") not in (0, "0", None) and not body.get("pic_str"):
                logger.warning("chaojiying error: %s", body)
                return None
            pic = body.get("pic_str")
            if not pic:
                logger.warning("chaojiying empty: %s", body)
                return None
            logger.info("chaojiying ok type=%s pic_str=%s", codetype, str(pic)[:40])
            return str(pic)
        except Exception as exc:  # noqa: BLE001
            logger.warning("chaojiying request failed: %s", exc)
            return None


class YunmaProvider(CaptchaProvider):
    """云码 jfbym（国内 token 计费）。

    滑块类型：
    - 20111 双图滑块
    - 22222 / 20110 单图滑块
    """

    name = "yunma"
    api_url = "http://api.jfbym.com/api/YmServer/customApi"

    def __init__(
        self,
        token: str,
        *,
        dual_type: str = "20111",
        single_type: str = "22222",
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.token = token
        self.dual_type = dual_type
        self.single_type = single_type

    async def solve_image(self, image_b64: str, *, question: str = "") -> str | None:
        data = await self._post(
            {
                "token": self.token,
                "type": "10110",  # 通用数英，具体以控制台为准
                "image": _strip_data_url(image_b64),
            }
        )
        return data

    async def solve_slider_gap(self, bg_b64: str, slice_b64: str = "") -> float | None:
        bg = _strip_data_url(bg_b64)
        sl = _strip_data_url(slice_b64) if slice_b64 else ""
        if sl:
            text = await self._post(
                {
                    "token": self.token,
                    "type": self.dual_type,
                    "slide_image": sl,
                    "background_image": bg,
                }
            )
        else:
            text = await self._post(
                {
                    "token": self.token,
                    "type": self.single_type,
                    "image": bg,
                }
            )
        return _parse_first_number(text)

    async def solve_fruit_offset(self, image_b64: str, ques_b64: str = "") -> float | None:
        # 云码无专用水果类型：用单图滑块尝试（成功率有限，建议冰拓）
        text = await self._post(
            {
                "token": self.token,
                "type": self.single_type,
                "image": _strip_data_url(image_b64),
            }
        )
        return _parse_first_number(text)

    async def _post(self, payload: dict[str, Any]) -> str | None:
        if not self.token:
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(self.api_url, json=payload)
                r.raise_for_status()
                body = r.json()
            # 兼容多层 data
            code = body.get("code")
            data = body.get("data")
            if isinstance(data, dict):
                if data.get("code") not in (None, 10000, "10000") and code not in (10000, "10000", 0, "0"):
                    # 有的返回 data.code=10000
                    if data.get("code") != 10000:
                        logger.warning("yunma error: %s", body)
                        return None
                result = data.get("data")
                if result is not None:
                    logger.info("yunma ok result=%s", str(result)[:40])
                    return str(result)
            if code in (10000, "10000", 0, "0") and data is not None and not isinstance(data, dict):
                return str(data)
            logger.warning("yunma unexpected: %s", body)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("yunma request failed: %s", exc)
            return None


class CapSolverProvider(CaptchaProvider):
    name = "capsolver"
    create_url = "https://api.capsolver.com/createTask"
    result_url = "https://api.capsolver.com/getTaskResult"

    def __init__(self, api_key: str, *, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.api_key = api_key

    async def solve_image(self, image_b64: str, *, question: str = "") -> str | None:
        task: dict[str, Any] = {
            "type": "ImageToTextTask",
            "body": _strip_data_url(image_b64),
        }
        if question:
            task["websiteURL"] = question
        return await self._poll_text(task)

    async def solve_slider_gap(self, bg_b64: str, slice_b64: str = "") -> float | None:
        task = {
            "type": "VisionEngine",
            "module": "slider",
            "image": _strip_data_url(bg_b64),
            "imageBackground": _strip_data_url(slice_b64) if slice_b64 else _strip_data_url(bg_b64),
        }
        data = await self._create_and_poll(task)
        if not data:
            return None
        for key in ("distance", "x", "gap", "offset"):
            if key in data and data[key] is not None:
                try:
                    return float(data[key])
                except (TypeError, ValueError):
                    pass
        return _parse_first_number(str(data.get("text") or data.get("answer") or ""))

    async def _poll_text(self, task: dict[str, Any]) -> str | None:
        data = await self._create_and_poll(task)
        if not data:
            return None
        return str(data.get("text") or data.get("answer") or "") or None

    async def _create_and_poll(self, task: dict[str, Any]) -> dict[str, Any] | None:
        payload = {"clientKey": self.api_key, "task": task}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(self.create_url, json=payload)
            r.raise_for_status()
            body = r.json()
            if body.get("errorId"):
                logger.warning("capsolver create error: %s", body)
                return None
            task_id = body.get("taskId")
            if not task_id:
                return body.get("solution") or body

            deadline = asyncio.get_event_loop().time() + self.timeout
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(2)
                rr = await client.post(
                    self.result_url,
                    json={"clientKey": self.api_key, "taskId": task_id},
                )
                rr.raise_for_status()
                res = rr.json()
                if res.get("status") == "ready":
                    return res.get("solution") or {}
                if res.get("status") == "failed" or res.get("errorId"):
                    logger.warning("capsolver failed: %s", res)
                    return None
        return None


class TwoCaptchaProvider(CaptchaProvider):
    name = "twocaptcha"
    in_url = "https://2captcha.com/in.php"
    res_url = "https://2captcha.com/res.php"

    def __init__(self, api_key: str, *, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.api_key = api_key

    async def solve_image(self, image_b64: str, *, question: str = "") -> str | None:
        async with httpx.AsyncClient(timeout=30) as client:
            data: dict[str, Any] = {
                "key": self.api_key,
                "method": "base64",
                "body": _strip_data_url(image_b64),
                "json": 1,
            }
            if question:
                data["textinstructions"] = question
            r = await client.post(self.in_url, data=data)
            body = r.json()
            if body.get("status") != 1:
                logger.warning("2captcha in error: %s", body)
                return None
            req_id = body.get("request")
            deadline = asyncio.get_event_loop().time() + self.timeout
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(3)
                rr = await client.get(
                    self.res_url,
                    params={"key": self.api_key, "action": "get", "id": req_id, "json": 1},
                )
                res = rr.json()
                if res.get("status") == 1:
                    return str(res.get("request") or "")
                if res.get("request") not in ("CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"):
                    logger.warning("2captcha res error: %s", res)
                    return None
        return None

    async def solve_slider_gap(self, bg_b64: str, slice_b64: str = "") -> float | None:
        logger.debug("2captcha slider gap not implemented, use local_slider")
        return None


def map_image_offset_to_ui(
    image_offset: float,
    *,
    max_slide: float,
    image_width: float = 320.0,
    mode: str = "linear",
) -> float:
    """把打码返回的图像坐标映射到 UI 拖动距离。

    - linear: ui = offset / image_width * max_slide
    - clamp: 若 offset 已在 max_slide 量级则直接使用
    - fruit_right_edge: 冰拓 1358/1357（目标右缘→图左距离）→ ui_x ≈ raw - 24
    """
    if image_offset is None:
        return 0.0
    off = float(image_offset)
    if off < 0:
        off = 0.0
    if mode in ("fruit_right_edge", "bingtop_1358", "bingtop_fruit"):
        return map_bingtop_fruit_offset_to_ui(
            off, max_slide=max_slide, image_width=image_width
        )
    # 返回值已经很像 UI 距离（≤ max_slide * 1.15）
    if mode == "auto" or mode == "clamp":
        if 0 < off <= max_slide * 1.15:
            return min(max_slide, max(0.0, off))
        if image_width > 1 and off > max_slide * 1.15:
            return min(max_slide, max(0.0, off / image_width * max_slide))
    return min(max_slide, max(0.0, off / max(image_width, 1.0) * max_slide))


def map_bingtop_fruit_offset_to_ui(
    image_offset: float,
    *,
    max_slide: float,
    image_width: float = 320.0,
    ui_width: float = 320.0,
    edge_pad: float = 24.0,
    margin: float = 0.0,
    style: str = "right_edge",
) -> float:
    """冰拓 1358/1357 recognition → UI 拖动距离。

    style:
      - right_edge（默认）：按「目标右缘 x1」→ ui = raw - 24

    edge_pad 是 scratch-captcha 的固定协议前缘，不应从 DOM button 宽度推导。
      - raw：仅用于诊断，直接把 recognition 当作 UI 位移
    """
    off = float(image_offset)
    if off < 0:
        off = 0.0
    source_width = float(image_width) if image_width > 1 else 320.0
    display_width = float(ui_width) if ui_width > 1 else 320.0
    display_x = off * display_width / source_width
    if style == "right_edge":
        ui = display_x - float(edge_pad) + float(margin)
    else:
        ui = display_x
    return float(min(max_slide, max(0.0, ui)))


def create_provider(
    name: str,
    api_key: str = "",
    *,
    username: str = "",
    password: str = "",
    soft_id: str = "",
    fruit_type: int | None = None,
    extra: dict[str, Any] | None = None,
) -> CaptchaProvider | None:
    """按名称构造打码适配器。凭证不全时返回 None。"""
    name = (name or "").lower().strip()
    extra = extra or {}

    if name in ("", "none", "local", "local_slider"):
        return None

    if name in ("bingtop", "冰拓", "bing"):
        user = username or api_key  # 允许 api_key 填 username
        pwd = password or str(extra.get("password") or "")
        if not user or not pwd:
            logger.warning("bingtop needs username + password")
            return None
        kwargs: dict[str, Any] = {}
        if fruit_type is not None:
            kwargs["fruit_type"] = fruit_type
        if "gap_type" in extra:
            kwargs["gap_type"] = extra["gap_type"]
        return BingtopProvider(user, pwd, **kwargs)

    if name in ("chaojiying", "超级鹰", "cjy"):
        user = username or str(extra.get("username") or "")
        pwd = password or str(extra.get("password") or "")
        sid = soft_id or api_key or str(extra.get("soft_id") or "")
        if not user or not pwd or not sid:
            logger.warning("chaojiying needs username + password + soft_id")
            return None
        kwargs = {}
        if fruit_type is not None:
            kwargs["fruit_type"] = fruit_type
        return ChaojiyingProvider(user, pwd, sid, **kwargs)

    if name in ("yunma", "jfbym", "云码"):
        token = api_key or str(extra.get("token") or "")
        if not token:
            logger.warning("yunma needs api_key(token)")
            return None
        return YunmaProvider(token)

    if name in ("capsolver", "cap-solver"):
        if not api_key:
            return None
        return CapSolverProvider(api_key)

    if name in ("twocaptcha", "2captcha", "two_captcha"):
        if not api_key:
            return None
        return TwoCaptchaProvider(api_key)

    logger.warning("unknown captcha provider: %s", name)
    return None
