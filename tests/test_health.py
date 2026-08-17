from __future__ import annotations

import os

from app.routers import shows


class _Repo:
    _db_path = "/tmp/daxi.sqlite3"

    @staticmethod
    def exists() -> bool:
        return True


def test_health_identifies_supervised_backend_instance(monkeypatch):
    monkeypatch.setattr(shows, "_repo", lambda: _Repo())
    monkeypatch.setenv("DAXI_DESKTOP_VERSION", "1.2.3")
    monkeypatch.setenv("DAXI_PARENT_PID", "1234")
    monkeypatch.setenv("DAXI_INSTANCE_ID", "instance-abc")

    result = shows.health()

    assert result["status"] == "ok"
    assert result["service_id"] == "com.daxi.backend"
    assert result["api_protocol"] == 2
    assert result["version"] == "1.2.3"
    assert result["backend_version"] == shows.__version__
    assert result["backend_build_id"]
    assert result["pid"] == os.getpid()
    assert result["parent_pid"] == 1234
    assert result["instance_id"] == "instance-abc"
    assert result["db_exists"] is True


def test_health_keeps_standalone_development_compatibility(monkeypatch):
    monkeypatch.setattr(shows, "_repo", lambda: _Repo())
    monkeypatch.delenv("DAXI_DESKTOP_VERSION", raising=False)
    monkeypatch.delenv("DAXI_PARENT_PID", raising=False)
    monkeypatch.delenv("DAXI_INSTANCE_ID", raising=False)

    result = shows.health()

    assert result["version"] == shows.__version__
    assert result["parent_pid"] is None
    assert result["instance_id"] == ""
