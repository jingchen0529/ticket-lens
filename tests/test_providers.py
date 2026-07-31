"""国内打码适配与位移映射（离线，不发真实请求）。"""

from app.browser.captcha.providers import (
    _parse_first_number,
    create_provider,
    map_image_offset_to_ui,
    to_b64,
)


def test_parse_first_number():
    assert _parse_first_number("128") == 128.0
    assert _parse_first_number("128,45") == 128.0
    assert _parse_first_number("90|12") == 90.0
    assert _parse_first_number("x=56.5") == 56.5
    assert _parse_first_number("error:300") is None
    assert _parse_first_number("错误:300") is None
    assert _parse_first_number("") is None
    assert _parse_first_number(None) is None


def test_map_image_offset_to_ui_linear():
    # image 320 → ui max 280, offset 160 → 140
    ui = map_image_offset_to_ui(160, max_slide=280, image_width=320, mode="linear")
    assert abs(ui - 140.0) < 0.1


def test_map_image_offset_auto_clamps_ui_scale():
    # 已是 UI 尺度
    ui = map_image_offset_to_ui(120, max_slide=280, image_width=320, mode="auto")
    assert abs(ui - 120.0) < 0.1
    # 明显是图像坐标
    ui2 = map_image_offset_to_ui(320, max_slide=280, image_width=320, mode="auto")
    assert abs(ui2 - 280.0) < 0.1


def test_map_bingtop_fruit_offset():
    from app.browser.captcha.providers import map_bingtop_fruit_offset_to_ui

    # 1358 默认按目标右缘换算：76 - 24px 滑块前缘。
    ui = map_bingtop_fruit_offset_to_ui(76, max_slide=272)
    assert abs(ui - 52.0) < 0.1
    # raw 只保留给诊断对照，不能作为 1358 默认拖动值。
    raw = map_bingtop_fruit_offset_to_ui(76, max_slide=272, style="raw")
    assert abs(raw - 76.0) < 0.1
    ui2 = map_image_offset_to_ui(76, max_slide=272, image_width=320, mode="fruit_right_edge")
    assert abs(ui2 - 52.0) < 0.1
    # 非 320 源图只缩放图像坐标，不缩放固定的滑块前缘。
    ui3 = map_bingtop_fruit_offset_to_ui(152, max_slide=272, image_width=640)
    assert abs(ui3 - 52.0) < 0.1
    # 响应式布局只缩放源图坐标；scratch-captcha 的协议前缘仍固定为 24px。
    responsive = map_bingtop_fruit_offset_to_ui(
        152,
        max_slide=204,
        image_width=640,
        ui_width=240,
    )
    assert abs(responsive - 33.0) < 0.1
    ui4 = map_bingtop_fruit_offset_to_ui(320, max_slide=272)
    assert abs(ui4 - 272.0) < 0.1
    # 露出余量：ui = raw - 24 + margin（live 探针发现贴边易 code=300）
    with_margin = map_bingtop_fruit_offset_to_ui(119, max_slide=272, margin=8.0)
    assert abs(with_margin - 103.0) < 0.1


def test_to_b64_strips_data_url():
    raw = to_b64("data:image/png;base64,abc123")
    assert raw == "abc123"
    assert to_b64(b"hi")  # base64 of hi


def test_create_provider_local_none():
    assert create_provider("local_slider", "") is None
    assert create_provider("none", "x") is None


def test_create_provider_bingtop_needs_creds():
    assert create_provider("bingtop", "") is None
    p = create_provider("bingtop", username="u", password="p")
    assert p is not None
    assert p.name == "bingtop"


def test_create_provider_chaojiying():
    p = create_provider("chaojiying", api_key="sid", username="u", password="p")
    assert p is not None
    assert p.name == "chaojiying"


def test_create_provider_yunma():
    p = create_provider("yunma", "token-xxx")
    assert p is not None
    assert p.name == "yunma"
