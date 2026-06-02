from __future__ import annotations

import builtins
import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from memorywiki_mcp.server import (
    TOOL_NAMES,
    _allow_non_loopback_http,
    _is_loopback_host,
    create_server,
    run_server,
    tool_specs,
    validate_backend,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_mcp_v1_exposes_context_and_core_tools():
    assert TOOL_NAMES == (
        "memorywiki_recall",
        "memorywiki_context",
        "memorywiki_list",
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
    assert specs["memorywiki_context"]["read_only"] is True
    assert specs["memorywiki_context"]["write_gated"] == "refresh_index_if_needed"
    assert specs["memorywiki_list"]["read_only"] is True
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


def test_create_server_registers_stable_tool_contract(monkeypatch):
    registered = []

    class FakeFastMCP:
        def __init__(self, name, json_response):
            self.name = name
            self.json_response = json_response

        def tool(self):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn

            return decorator

    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)

    server = create_server()

    assert server.name == "MemoryWiki Memory"
    assert server.json_response is True
    assert tuple(registered) == TOOL_NAMES


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


def test_loopback_helper_accepts_localhost_and_loopback_ips():
    assert _is_loopback_host("localhost") is True
    assert _is_loopback_host("127.0.0.1") is True
    assert _is_loopback_host("::1") is True
    assert _is_loopback_host("0.0.0.0") is False
    assert _is_loopback_host("example.com") is False


def test_non_loopback_http_gate_is_opt_in(monkeypatch):
    monkeypatch.delenv("MEMORY_MCP_ALLOW_HTTP_NON_LOOPBACK", raising=False)
    assert _allow_non_loopback_http() is False
    monkeypatch.setenv("MEMORY_MCP_ALLOW_HTTP_NON_LOOPBACK", "true")
    assert _allow_non_loopback_http() is True


def test_streamable_http_non_loopback_requires_explicit_unsafe_gate(monkeypatch):
    calls = []

    class FakeServer:
        def run(self, transport):
            calls.append(transport)

    monkeypatch.setenv("MEMORY_MCP_ALLOW_HTTP_NON_LOOPBACK", "true")
    monkeypatch.setattr("memorywiki_mcp.server.create_server", lambda: FakeServer())

    run_server(transport="streamable-http", host="0.0.0.0", port=9999)

    assert calls == ["streamable-http"]
