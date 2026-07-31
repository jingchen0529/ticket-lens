from __future__ import annotations

from app.core import paths


def test_frozen_macos_uses_user_data_dir_and_migrates_legacy(monkeypatch, tmp_path):
    executable_dir = tmp_path / "Daolue.app" / "Contents" / "Resources" / "backend"
    legacy = executable_dir / "data"
    legacy.mkdir(parents=True)
    (legacy / "frontend_settings.yaml").write_text("theme_color: '#eb4f9a'\n", encoding="utf-8")
    target = tmp_path / "Library" / "Application Support" / "daxi"

    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths, "executable_dir", lambda: executable_dir)
    monkeypatch.setattr(paths, "_system_user_data_dir", lambda: target)
    paths.data_dir.cache_clear()

    try:
        assert paths.data_dir() == target
        assert (target / "frontend_settings.yaml").read_text(encoding="utf-8") == (
            "theme_color: '#eb4f9a'\n"
        )
    finally:
        paths.data_dir.cache_clear()


def test_frozen_macos_does_not_overwrite_existing_user_data(monkeypatch, tmp_path):
    executable_dir = tmp_path / "Daolue.app" / "Contents" / "Resources" / "backend"
    legacy = executable_dir / "data"
    legacy.mkdir(parents=True)
    (legacy / "marker.txt").write_text("legacy", encoding="utf-8")
    target = tmp_path / "Library" / "Application Support" / "daxi"
    target.mkdir(parents=True)
    (target / "marker.txt").write_text("current", encoding="utf-8")

    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths, "executable_dir", lambda: executable_dir)
    monkeypatch.setattr(paths, "_system_user_data_dir", lambda: target)
    paths.data_dir.cache_clear()

    try:
        assert paths.data_dir() == target
        assert (target / "marker.txt").read_text(encoding="utf-8") == "current"
    finally:
        paths.data_dir.cache_clear()
