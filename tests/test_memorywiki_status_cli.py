from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env


def test_memorywiki_status_is_read_only_and_reports_pending_captures(tmp_path):
    project_root = tmp_path / "project-memory"
    pending = project_root / "_pending"
    pending.mkdir(parents=True)
    (pending / "session_captures.jsonl").write_text('{"event_type":"stop"}\n', encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "memorywiki_status.py",
            "--project-root",
            str(project_root),
            "--global-root",
            str(tmp_path / "global-memory"),
            "--scope",
            "all",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "warn"
    assert payload["pending_captures"]["project"]["count"] == 1
    assert payload["index"]["dry_run"] is True
    assert not (project_root / "retrieval").exists()


def test_mw_dispatches_status_and_capture(tmp_path):
    status = subprocess.run(
        [
            sys.executable,
            "mw_cli.py",
            "status",
            "--project-root",
            str(tmp_path / "project-memory"),
            "--global-root",
            str(tmp_path / "global-memory"),
            "--scope",
            "project",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(status.stdout)["index"]["scope"] == "project"

    source = tmp_path / "events.jsonl"
    source.write_text('{"type":"stop","summary":"done"}\n', encoding="utf-8")
    capture = subprocess.run(
        [
            sys.executable,
            "mw_cli.py",
            "capture-ingest",
            "--source",
            str(source),
            "--project-root",
            str(tmp_path / "project-memory"),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(capture.stdout)["captured"] == 1
