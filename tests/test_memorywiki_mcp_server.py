from __future__ import annotations

import builtins
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

from memorywiki_mcp.server import TOOL_NAMES, create_server, run_server, tool_specs, validate_backend


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_mcp_v1_exposes_seven_tools():
    assert TOOL_NAMES == (
        "memorywiki_recall",
        "memorywiki_read_memory",
        "memorywiki_index_maintain",
        "memorywiki_write_session",
        "memorywiki_crystallize",
        "memorywiki_ingest_source",
        "memorywiki_forget",
    )


def test_tool_specs_mark_read_and_write_capabilities():
    specs = tool_specs()

    assert set(specs) == set(TOOL_NAMES)
    assert specs["memorywiki_recall"]["read_only"] is True
    assert specs["memorywiki_read_memory"]["read_only"] is True
    assert specs["memorywiki_index_maintain"]["write_gated"] is True
    assert specs["memorywiki_write_session"]["write_gated"] is True
    assert specs["memorywiki_crystallize"]["write_gated"] == "when dry_run=false"
    assert specs["memorywiki_ingest_source"]["write_gated"] == "when dry_run=false"
    assert specs["memorywiki_forget"]["write_gated"] == "when dry_run=false"


def test_validate_backend_accepts_local_and_openai(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "local")
    assert validate_backend() == "local"
    monkeypatch.setenv("MEMORY_BACKEND", "openai")
    assert validate_backend() == "openai"


def test_validate_backend_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "surprise")

    with pytest.raises(ValueError, match="MEMORY_BACKEND"):
        validate_backend()


def test_create_server_fails_gracefully_when_mcp_extra_is_missing(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "mcp.server.fastmcp":
            raise ModuleNotFoundError("No module named 'mcp'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(RuntimeError, match="Install the MCP extra"):
        create_server()


def test_cli_handles_installed_or_missing_mcp_extra_cleanly():
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "memorywiki_mcp",
            "--transport",
            "stdio",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    if importlib.util.find_spec("mcp") is None:
        assert result.returncode == 2
        assert "Install the MCP extra" in result.stderr
    else:
        assert result.returncode == 0
        assert "Install the MCP extra" not in result.stderr


def test_streamable_http_refuses_non_loopback_host_before_server_start():
    with pytest.raises(ValueError, match="non-loopback"):
        run_server(transport="streamable-http", host="0.0.0.0")


def test_streamable_http_non_loopback_requires_explicit_unsafe_gate(monkeypatch):
    calls = []

    class FakeServer:
        def run(self, transport):
            calls.append(transport)

    monkeypatch.setenv("MEMORY_MCP_ALLOW_HTTP_NON_LOOPBACK", "true")
    monkeypatch.setattr("memorywiki_mcp.server.create_server", lambda: FakeServer())

    run_server(transport="streamable-http", host="0.0.0.0", port=9999)

    assert calls == ["streamable-http"]
