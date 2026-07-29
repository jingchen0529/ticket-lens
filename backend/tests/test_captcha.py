"""验证码轨迹与配置合并。"""

from unittest.mock import AsyncMock, patch

import pytest

from app.browser.captcha.base import CaptchaChallenge, CaptchaKind
from app.browser.captcha.human_track import distance_candidates, generate_slider_track
from app.core.config import (
    AppConfig,
    CaptchaConfig,
    PlatformCaptchaOverride,
    SourceEndpointConfig,
    SourcesConfig,
)
from app.crawlers.damai.captcha import DamaiCaptchaSolver
from app.crawlers.damai.fruit_slider import solve_fruit_slider
from app.crawlers.maoyan.captcha import MaoyanCaptchaSolver


def test_slider_track_sums_near_distance():
    dist = 260.0
    track = generate_slider_track(dist)
    assert len(track) > 10
    total_x = sum(dx for dx, _, _ in track)
    # 含 overshoot 回拉，合计应接近原距离
    assert abs(total_x - dist) < 1.0


def test_distance_candidates():
    xs = distance_candidates(200)
    assert len(xs) >= 3
    assert all(x > 0 for x in xs)


def test_captcha_for_merge():
    cfg = AppConfig(
        captcha=CaptchaConfig(provider="local_slider", api_key="global"),
        sources=SourcesConfig(
            damai=SourceEndpointConfig(
                captcha=PlatformCaptchaOverride(
                    provider="bingtop",
                    username="u1",
                    password="p1",
                    fruit_strategy="provider_first",
                    fruit_max_rounds=2,
                )
            ),
            maoyan=SourceEndpointConfig(),
        ),
    )
    d = cfg.captcha_for("damai")
    m = cfg.captcha_for("maoyan")
    assert d.provider == "bingtop"
    assert d.username == "u1"
    assert d.password == "p1"
    assert d.fruit_strategy == "provider_first"
    assert d.fruit_max_rounds == 2
    assert m.provider == "local_slider"
    assert m.api_key == "global"


def test_damai_solver_builds_provider():
    cfg = AppConfig(
        captcha=CaptchaConfig(
            provider="bingtop",
            username="demo",
            password="demo",
            fruit_strategy="provider_only",
            fruit_max_rounds=1,
        )
    )
    solver = DamaiCaptchaSolver(cfg)
    assert solver.provider is not None
    assert solver.provider.name == "bingtop"
    assert solver.fruit_strategy == "provider_only"
    assert solver.fruit_max_rounds == 1
    assert solver.max_auto_attempts == 1


def test_solvers_are_platform_specific():
    cfg = AppConfig()
    assert cfg.captcha.fruit_strategy == "provider_first"
    assert DamaiCaptchaSolver(cfg).platform == "damai"
    assert MaoyanCaptchaSolver(cfg).platform == "maoyan"


@pytest.mark.asyncio
async def test_default_fruit_strategy_calls_provider_before_local():
    page = AsyncMock()
    provider = object()
    with (
        patch(
            "app.crawlers.damai.fruit_slider.solve_by_provider_offset",
            AsyncMock(return_value=True),
        ) as provider_solve,
        patch(
            "app.crawlers.damai.fruit_slider._solve_fruit_slider_local",
            AsyncMock(side_effect=AssertionError("local must not consume the first puzzle")),
        ) as local_solve,
    ):
        assert await solve_fruit_slider(page, provider=provider) is True

    provider_solve.assert_awaited_once()
    local_solve.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_first_falls_back_to_free_local_solver():
    page = AsyncMock()
    provider = object()
    with (
        patch(
            "app.crawlers.damai.fruit_slider.solve_by_provider_offset",
            AsyncMock(return_value=False),
        ) as provider_solve,
        patch(
            "app.crawlers.damai.fruit_slider._solve_fruit_slider_local",
            AsyncMock(return_value=True),
        ) as local_solve,
    ):
        assert await solve_fruit_slider(page, provider=provider) is True

    provider_solve.assert_awaited_once()
    local_solve.assert_awaited_once()
    assert local_solve.await_args.kwargs["payload_hint"] is None


@pytest.mark.asyncio
async def test_fruit_failure_does_not_fall_through_to_nc():
    cfg = AppConfig(
        captcha=CaptchaConfig(
            provider="bingtop",
            username="demo",
            password="demo",
            fruit_strategy="provider_only",
            fruit_max_rounds=1,
        )
    )
    solver = DamaiCaptchaSolver(cfg)
    challenge = CaptchaChallenge(
        kind=CaptchaKind.SLIDER,
        reason="fruit",
        meta={"fruit": True},
    )
    page = AsyncMock()
    with (
        patch("app.crawlers.damai.captcha.wait_fruit_slider", AsyncMock(return_value=True)),
        patch("app.crawlers.damai.captcha.detect_fruit_slider", AsyncMock(return_value=True)),
        patch("app.crawlers.damai.captcha.solve_fruit_slider", AsyncMock(return_value=False)),
        patch(
            "app.crawlers.damai.captcha.try_slider_solve",
            AsyncMock(side_effect=AssertionError("must not run NC after fruit")),
        ),
    ):
        result = await solver.solve_auto(page, challenge)

    assert not result.ok
    assert result.method.startswith("fruit_slider:")


@pytest.mark.asyncio
async def test_ensure_cleared_does_not_retry_internal_type_error():
    solver = DamaiCaptchaSolver(AppConfig())
    challenge = CaptchaChallenge(
        kind=CaptchaKind.SLIDER,
        reason="fruit",
        meta={"fruit": True},
    )
    solver.detect = AsyncMock(return_value=challenge)  # type: ignore[method-assign]
    solver.solve_auto = AsyncMock(  # type: ignore[method-assign]
        side_effect=TypeError("solver implementation failed")
    )
    page = AsyncMock()
    page.url = "https://search.damai.cn/search.htm"

    with pytest.raises(TypeError, match="implementation failed"):
        await solver.ensure_cleared(page, payload_hint=object())

    solver.solve_auto.assert_awaited_once()
