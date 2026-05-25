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


def test_memorywiki_config_init_show_and_validate(tmp_path):
    config_path = tmp_path / ".memorywiki.toml"

    init = subprocess.run(
        [
            sys.executable,
            "-m",
            "memorywiki_config",
            "init",
            "--path",
            str(config_path),
            "--format",
            "json",
        ],
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(init.stdout)["created"] is True
    assert config_path.exists()
    template = config_path.read_text(encoding="utf-8")
    assert "CLI flags and environment variables override" in template
    assert "chat_write_enabled = false" in template
    assert "sanitize_on_write = true" in template

    show = subprocess.run(
        [sys.executable, "-m", "memorywiki_config", "show", "--format", "json"],
        cwd=tmp_path,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(show.stdout)
    assert payload["config_path"] == str(config_path)
    assert payload["project_storage_root"].endswith(".agent_memory/project")

    validate = subprocess.run(
        [sys.executable, "-m", "memorywiki_config", "validate", "--format", "json"],
        cwd=tmp_path,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(validate.stdout)["status"] == "ok"


def test_mw_config_alias_dispatches_to_config(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "mw_cli", "config", "show", "--format", "json"],
        cwd=tmp_path,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )
    assert "project_storage_root" in json.loads(result.stdout)


def test_mw_help_lists_operational_aliases(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "mw_cli", "--help"],
        cwd=tmp_path,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "mcp-contract" in result.stdout
    assert "crystallize" in result.stdout
    assert "release-check" in result.stdout
