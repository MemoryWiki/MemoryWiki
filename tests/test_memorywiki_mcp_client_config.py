from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from memory_system.config import default_memory_timezone
from memorywiki_mcp.client_config import build_mcp_json, build_server_config


def test_client_config_defaults_to_read_only_stdio(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("# python shim\n", encoding="utf-8")

    config = build_server_config(repo_root=repo_root, python=python)

    assert config["command"] == str(python)
    assert config["args"] == ["-m", "memorywiki_mcp", "--transport", "stdio"]
    assert config["cwd"] == str(repo_root)
    assert config["env"]["PYTHONPATH"] == str(repo_root)
    assert config["env"]["MEMORY_BACKEND"] == "local"
    assert config["env"]["MEMORY_TIMEZONE"] == default_memory_timezone()
    assert "MEMORY_MCP_WRITE_ENABLED" not in config["env"]
    assert "MEMORY_GLOBAL_WRITE_ENABLED" not in config["env"]
    assert "MEMORY_MCP_ALLOW_ROOT_OVERRIDE" not in config["env"]


def test_client_config_can_explicitly_enable_write_gates(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    payload = build_mcp_json(
        repo_root=repo_root,
        python=Path("/usr/bin/python3.12"),
        write_enabled=True,
        global_write_enabled=True,
        allow_root_override=True,
    )
    env = payload["mcpServers"]["memorywiki-memory"]["env"]

    assert env["MEMORY_MCP_WRITE_ENABLED"] == "true"
    assert env["MEMORY_GLOBAL_WRITE_ENABLED"] == "true"
    assert env["MEMORY_MCP_ALLOW_ROOT_OVERRIDE"] == "true"


def test_client_config_output_rejects_symlink_target(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("keep me\n", encoding="utf-8")
    link = tmp_path / ".mcp.json"
    link.symlink_to(outside)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "memorywiki_mcp.client_config",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(link),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "symlink" in result.stderr
    assert outside.read_text(encoding="utf-8") == "keep me\n"
