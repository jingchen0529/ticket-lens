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


def test_frozen_windows_migrates_program_files_data_without_overwrite(monkeypatch, tmp_path):
    executable_dir = tmp_path / "Program Files" / "Daolue" / "backend"
    legacy = executable_dir / "data"
    (legacy / "cookies").mkdir(parents=True)
    (legacy / "daxi.sqlite3").write_bytes(b"legacy database")
    (legacy / "cookies" / "damai.json").write_text("legacy cookie", encoding="utf-8")
    (legacy / "cookies" / "maoyan.json").write_text("legacy cookie", encoding="utf-8")
    (legacy / "frontend_settings.yaml").write_text("legacy settings", encoding="utf-8")

    target = tmp_path / "LocalAppData" / "daxi"
    (target / "cookies").mkdir(parents=True)
    (target / "frontend_settings.yaml").write_text("current settings", encoding="utf-8")
    (target / "cookies" / "maoyan.json").write_text("current cookie", encoding="utf-8")

    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setattr(paths, "executable_dir", lambda: executable_dir)
    monkeypatch.setattr(paths, "_system_user_data_dir", lambda: target)
    monkeypatch.setattr(paths, "_is_writable", lambda _directory: False)
    paths.data_dir.cache_clear()

    try:
        assert paths.data_dir() == target
        assert (target / "daxi.sqlite3").read_bytes() == b"legacy database"
        assert (target / "cookies" / "damai.json").read_text(encoding="utf-8") == (
            "legacy cookie"
        )
        assert (target / "cookies" / "maoyan.json").read_text(encoding="utf-8") == (
            "current cookie"
        )
        assert (target / "frontend_settings.yaml").read_text(encoding="utf-8") == (
            "current settings"
        )
    finally:
        paths.data_dir.cache_clear()
