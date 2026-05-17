from __future__ import annotations

import json
from pathlib import Path

import pytest

from memorywiki_operator_env import resolve_mcp_python


def test_resolve_mcp_python_uses_trusted_memorywiki_memory_command(tmp_path, monkeypatch):
    python = tmp_path / "python3.12"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "memorywiki-memory": {
                        "command": str(python),
                        "args": ["-m", "memorywiki_mcp"],
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMORYWIKI_MCP_TRUSTED_PYTHON_DIRS", str(tmp_path))

    payload = resolve_mcp_python(mcp_config=config, fallback="/usr/bin/python3")

    assert payload["python"] == str(python)
    assert payload["source"] == "mcp-config"
    assert payload["warning"] == ""


def test_resolve_mcp_python_does_not_trust_project_controlled_command(tmp_path):
    malicious = tmp_path / "python-malicious"
    malicious.write_text("#!/bin/sh\nprintf pwned > %s\n" % (tmp_path / "marker"), encoding="utf-8")
    malicious.chmod(0o700)
    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps({"mcpServers": {"memorywiki-memory": {"command": str(malicious)}}}) + "\n",
        encoding="utf-8",
    )

    payload = resolve_mcp_python(mcp_config=config, fallback="/usr/bin/python3")

    assert payload["python"] == "/usr/bin/python3"
    assert payload["source"] == "fallback"
    assert "not in a trusted" in payload["warning"]
    assert not (tmp_path / "marker").exists()


def test_resolve_mcp_python_rejects_parent_traversal_from_trusted_dir(tmp_path, monkeypatch):
    trusted = tmp_path / "trusted"
    evil = tmp_path / "evil"
    trusted.mkdir()
    evil.mkdir()
    malicious = evil / "python-malicious"
    malicious.write_text("#!/bin/sh\nprintf pwned > %s\n" % (tmp_path / "marker"), encoding="utf-8")
    malicious.chmod(0o700)
    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "memorywiki-memory": {
                        "command": str(trusted / ".." / "evil" / "python-malicious")
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMORYWIKI_MCP_TRUSTED_PYTHON_DIRS", str(trusted))

    payload = resolve_mcp_python(mcp_config=config, fallback="/usr/bin/python3")

    assert payload["python"] == "/usr/bin/python3"
    assert payload["source"] == "fallback"
    assert "parent-directory traversal" in payload["warning"]
    assert not (tmp_path / "marker").exists()


def test_resolve_mcp_python_rejects_symlink_out_of_trusted_dir(tmp_path, monkeypatch):
    trusted = tmp_path / "trusted"
    evil = tmp_path / "evil"
    trusted.mkdir()
    evil.mkdir()
    malicious = evil / "python-malicious"
    malicious.write_text("#!/bin/sh\nprintf pwned > %s\n" % (tmp_path / "marker"), encoding="utf-8")
    malicious.chmod(0o700)
    linked = trusted / "python-linked"
    linked.symlink_to(malicious)
    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps({"mcpServers": {"memorywiki-memory": {"command": str(linked)}}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMORYWIKI_MCP_TRUSTED_PYTHON_DIRS", str(trusted))

    payload = resolve_mcp_python(mcp_config=config, fallback="/usr/bin/python3")

    assert payload["python"] == "/usr/bin/python3"
    assert payload["source"] == "fallback"
    assert "not in a trusted" in payload["warning"]
    assert not (tmp_path / "marker").exists()


def test_resolve_mcp_python_rejects_symlinked_config(tmp_path):
    real = tmp_path / "real.json"
    link = tmp_path / ".mcp.json"
    real.write_text("{}", encoding="utf-8")
    link.symlink_to(real)

    with pytest.raises(ValueError, match="MCP config must be a real file"):
        resolve_mcp_python(mcp_config=link, fallback="/usr/bin/python3")


def test_resolve_mcp_python_rejects_broken_symlink_config(tmp_path):
    link = tmp_path / ".mcp.json"
    link.symlink_to(tmp_path / "missing.json")

    with pytest.raises(ValueError, match="MCP config must be a real file"):
        resolve_mcp_python(mcp_config=link, fallback="/usr/bin/python3")


def test_resolve_mcp_python_falls_back_for_non_python_command(tmp_path):
    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps({"mcpServers": {"memorywiki-memory": {"command": "/bin/sh"}}}) + "\n",
        encoding="utf-8",
    )

    payload = resolve_mcp_python(mcp_config=config, fallback="/usr/bin/python3")

    assert payload["python"] == "/usr/bin/python3"
    assert payload["source"] == "fallback"
    assert "not a Python executable" in payload["warning"]
