"""验证码轨迹与配置合并。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser.captcha import base as captcha_base
from app.browser.captcha.base import CaptchaChallenge, CaptchaKind, CaptchaSolveResult
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
    assert cfg.captcha.fruit_max_rounds == 3
    assert DamaiCaptchaSolver(cfg).platform == "damai"
    assert MaoyanCaptchaSolver(cfg).platform == "maoyan"


@pytest.mark.asyncio
async def test_manual_solver_publishes_and_clears_intervention_status(monkeypatch):
    import app.services.crawl_jobs as crawl_jobs

    class DummySolver(captcha_base.CaptchaSolver):
        platform = "dummy"

        async def detect(self, page):
            return None

        async def solve_auto(self, page, challenge):
            raise AssertionError("manual test must not call auto solver")

    record = SimpleNamespace(
        set_manual_captcha=MagicMock(),
        clear_manual_captcha=MagicMock(),
    )
    monkeypatch.setattr(
        crawl_jobs,
        "get_job_manager",
        lambda: SimpleNamespace(active=record),
    )
    monkeypatch.setattr(captcha_base.asyncio, "sleep", AsyncMock())
    solver = DummySolver(
        SimpleNamespace(
            captcha=SimpleNamespace(
                manual_wait_seconds=1,
                fruit_max_rounds=3,
            ),
            browser=SimpleNamespace(headless=False),
        )
    )
    solver.provider = SimpleNamespace(name="bingtop")
    solver._confirm_cleared = AsyncMock(return_value=True)  # type: ignore[method-assign]

    result = await solver.solve_manual(
        object(),
        CaptchaChallenge(kind=CaptchaKind.SLIDER),
    )

    assert result.ok is True
    record.set_manual_captcha.assert_called_once()
    assert "连续 3 次" in record.set_manual_captcha.call_args.kwargs["reason"]
    assert record.set_manual_captcha.call_args.kwargs["provider"] == "bingtop"
    solver._confirm_cleared.assert_awaited_once()  # type: ignore[attr-defined]
    record.clear_manual_captcha.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://search.damai.cn/search.htm", True),
        ("https://detail.damai.cn/item.htm?id=1", True),
        ("https://login.taobao.com/member/login.jhtml", False),
        ("https://damai.cn.evil.example/", False),
    ],
)
async def test_damai_captcha_success_requires_damai_domain(url, expected):
    solver = DamaiCaptchaSolver(AppConfig())
    solver.detect = AsyncMock(return_value=None)  # type: ignore[method-assign]
    page = SimpleNamespace(url=url)
    result = CaptchaSolveResult(ok=True, method="manual", message="cleared")

    assert await solver._confirm_cleared(page, result) is expected


@pytest.mark.asyncio
async def test_damai_no_captcha_on_taobao_is_not_skipped_as_success():
    solver = DamaiCaptchaSolver(AppConfig())
    solver.detect = AsyncMock(return_value=None)  # type: ignore[method-assign]
    page = SimpleNamespace(url="https://www.taobao.com/")

    result = await solver.ensure_cleared(page)

    assert result.ok is False
    assert result.method == "unexpected_page"
    solver.detect.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_damai_manual_captcha_aborts_immediately_after_cross_domain_navigation():
    solver = DamaiCaptchaSolver(AppConfig())
    page = SimpleNamespace(url="https://login.taobao.com/member/login.jhtml")

    result = await solver.solve_manual(
        page,
        CaptchaChallenge(kind=CaptchaKind.SLIDER),
    )

    assert result.ok is False
    assert result.method == "unexpected_page"


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
