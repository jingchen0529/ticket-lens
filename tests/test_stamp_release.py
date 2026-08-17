from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_stamp_release_updates_desktop_and_backend_identity(tmp_path):
    config = tmp_path / "tauri.conf.json"
    config.write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "plugins": {
                    "updater": {
                        "endpoints": [
                            "https://old.example/latest.json",
                            "https://backup.example/latest.json",
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    build_info = tmp_path / "build_info.py"
    script = Path(__file__).resolve().parents[1] / "scripts" / "stamp_release.py"

    subprocess.run(
        [
            sys.executable,
            str(script),
            "--version",
            "1.2.3",
            "--build-id",
            "abc123",
            "--updater-url",
            "https://releases.example/latest.json",
            "--config",
            str(config),
            "--build-info",
            str(build_info),
        ],
        check=True,
    )

    stamped = json.loads(config.read_text(encoding="utf-8"))
    assert stamped["version"] == "1.2.3"
    assert stamped["plugins"]["updater"]["endpoints"] == [
        "https://releases.example/latest.json",
        "https://backup.example/latest.json",
    ]
    source = build_info.read_text(encoding="utf-8")
    assert 'BACKEND_VERSION = \'1.2.3\'' in source
    assert 'BACKEND_BUILD_ID = \'abc123\'' in source
