from __future__ import annotations

import json
import os
import platform
from pathlib import Path
import stat

import pytest

from memorywiki_mcp_doctor import _check_python, run_doctor
from memorywiki_mcp.client_config import build_mcp_json


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_mcp_doctor_reports_ok_for_read_only_config(tmp_path):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    project_root.mkdir(parents=True)
    global_root.mkdir(parents=True)
    config_path = tmp_path / ".mcp.json"
    config_path.write_text(
        json.dumps(
            build_mcp_json(
                repo_root=REPO_ROOT,
                python="/usr/bin/python3.12",
                project_root=project_root,
                global_root=global_root,
            )
        ),
        encoding="utf-8",
    )

    payload = run_doctor(
        repo_root=REPO_ROOT,
        python="/usr/bin/python3.12",
        project_root=project_root,
        global_root=global_root,
        config_path=config_path,
    )

    assert payload["status"] in {"ok", "warn"}
    assert payload["checks"]["mcp_config"]["status"] == "ok"
    assert payload["checks"]["write_gates"]["status"] == "ok"
    assert payload["checks"]["roots"]["status"] == "ok"
    assert payload["checks"]["index"]["status"] == "warn"


def test_mcp_doctor_resolves_python_command_from_path(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    bin_dir = tmp_path / "bin"
    project_root.mkdir(parents=True)
    global_root.mkdir(parents=True)
    bin_dir.mkdir()
    fake_python = bin_dir / ("python3.cmd" if platform.system() == "Windows" else "python3")
    if platform.system() == "Windows":
        fake_python.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
    else:
        fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.getenv("PATH", ""))
    config_path = tmp_path / ".mcp.json"
    config_path.write_text(
        json.dumps(
            build_mcp_json(
                repo_root=REPO_ROOT,
                python="python3",
                project_root=project_root,
                global_root=global_root,
            )
        ),
        encoding="utf-8",
    )

    payload = run_doctor(
        repo_root=REPO_ROOT,
        python="python3",
        project_root=project_root,
        global_root=global_root,
        config_path=config_path,
    )

    assert payload["checks"]["python"]["status"] == "ok"


def test_mcp_doctor_times_out_hanging_python_check(tmp_path):
    if platform.system() == "Windows":
        pytest.skip("POSIX shell sleep probe")
    slow_python = tmp_path / "slow-python"
    slow_python.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    slow_python.chmod(slow_python.stat().st_mode | stat.S_IXUSR)

    result = _check_python(str(slow_python), REPO_ROOT, timeout_seconds=0.2)

    assert result["status"] == "warn"
    assert "timed out" in "\n".join(result["messages"])


def test_mcp_doctor_warns_when_config_enables_write_gates(tmp_path):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    project_root.mkdir(parents=True)
    global_root.mkdir(parents=True)
    config_path = tmp_path / ".mcp.json"
    config_path.write_text(
        json.dumps(
            build_mcp_json(
                repo_root=REPO_ROOT,
                python="/usr/bin/python3.12",
                project_root=project_root,
                global_root=global_root,
                write_enabled=True,
                global_write_enabled=True,
            )
        ),
        encoding="utf-8",
    )

    payload = run_doctor(
        repo_root=REPO_ROOT,
        python="/usr/bin/python3.12",
        project_root=project_root,
        global_root=global_root,
        config_path=config_path,
    )

    assert payload["checks"]["write_gates"]["status"] == "warn"
    assert "MEMORY_MCP_WRITE_ENABLED" in "\n".join(payload["checks"]["write_gates"]["messages"])


def test_mcp_doctor_fails_on_broken_symlinked_config(tmp_path):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    project_root.mkdir(parents=True)
    global_root.mkdir(parents=True)
    config_path = tmp_path / ".mcp.json"
    config_path.symlink_to(tmp_path / "missing.json")

    payload = run_doctor(
        repo_root=REPO_ROOT,
        python="/usr/bin/python3.12",
        project_root=project_root,
        global_root=global_root,
        config_path=config_path,
    )

    assert payload["status"] == "fail"
    assert payload["checks"]["mcp_config"]["status"] == "fail"
    assert "symlink" in "\n".join(payload["checks"]["mcp_config"]["messages"])


def test_mcp_doctor_fails_on_symlinked_project_root(tmp_path):
    real = tmp_path / "real-project"
    real.mkdir()
    link = tmp_path / "link-project"
    link.symlink_to(real, target_is_directory=True)
    global_root = tmp_path / "global"
    global_root.mkdir()

    payload = run_doctor(
        repo_root=REPO_ROOT,
        python="/usr/bin/python3.12",
        project_root=link,
        global_root=global_root,
        config_path=tmp_path / "missing.json",
    )

    assert payload["status"] == "fail"
    assert payload["checks"]["roots"]["status"] == "fail"
