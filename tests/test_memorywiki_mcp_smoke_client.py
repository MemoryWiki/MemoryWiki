from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from memorywiki_mcp import smoke_client
from memorywiki_mcp.server import TOOL_NAMES


class FakeSession:
    def __init__(self, tools: tuple[str, ...] = TOOL_NAMES):
        self._tools = tools
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in self._tools])

    async def call_tool(self, name: str, payload: dict):
        self.calls.append((name, payload))
        if name == "memorywiki_write_session":
            return SimpleNamespace(isError=True, structuredContent={"error": "write disabled"})
        return SimpleNamespace(isError=False, structuredContent={"tool": name, "ok": True})


def test_structured_prefers_structured_content():
    result = SimpleNamespace(structuredContent={"ok": True}, content=[])

    assert smoke_client._structured(result) == {"ok": True}


def test_structured_falls_back_to_text_content():
    result = SimpleNamespace(
        structuredContent=None,
        content=[SimpleNamespace(text=json.dumps({"ok": True}))],
    )

    assert smoke_client._structured(result) == {"ok": True}


def test_readonly_smoke_lists_tools_runs_recall_and_checks_denied_write():
    session = FakeSession()

    payload = asyncio.run(smoke_client._call_readonly(session, "launch readiness"))

    assert payload["tools"] == list(TOOL_NAMES)
    assert payload["index"]["tool"] == "memorywiki_index_maintain"
    assert payload["recall"]["tool"] == "memorywiki_recall"
    assert payload["default_write_denied"] is True
    assert [name for name, _ in session.calls] == [
        "memorywiki_index_maintain",
        "memorywiki_recall",
        "memorywiki_write_session",
    ]
    recall_payload = session.calls[1][1]["input"]
    assert recall_payload["query"] == "launch readiness"
    assert recall_payload["strategy"] == "hybrid"
    assert recall_payload["token_budget"] == 800


def test_readonly_smoke_fails_when_tool_contract_is_missing():
    session = FakeSession(tuple(TOOL_NAMES[:-1]))

    with pytest.raises(RuntimeError, match="Missing MemoryWiki MCP tools"):
        asyncio.run(smoke_client._call_readonly(session, "contract check"))


def test_main_reports_smoke_errors_without_traceback(monkeypatch, capsys, tmp_path):
    async def broken_run_smoke(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(smoke_client, "run_smoke", broken_run_smoke)

    result = smoke_client.main(
        [
            "--repo-root",
            str(Path(tmp_path)),
            "--project-root",
            str(Path(tmp_path) / "project"),
            "--global-root",
            str(Path(tmp_path) / "global"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "boom" in captured.err
    assert "Traceback" not in captured.err
