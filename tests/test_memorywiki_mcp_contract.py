from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from memorywiki_mcp.server import TOOL_NAMES
from memorywiki_mcp_contract import build_contract, verify_contract, write_contract

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_mcp_contract_records_all_tools_and_write_gates():
    payload = build_contract(now="2026-05-16T00:00:00+00:00")
    tools = {tool["name"]: tool for tool in payload["tools"]}

    assert payload["schema"] == "memorywiki-mcp-contract-v1"
    assert payload["invocation"]["argument"] == "input"
    assert tuple(tools) == TOOL_NAMES
    assert tools["memorywiki_recall"]["input_schema"]["properties"]["query"]["type"] == "string"
    assert tools["memorywiki_write_session"]["write_gated"] is True
    assert tools["memorywiki_ingest_source"]["defaults"]["dry_run"] is True
    assert len(payload["contract_sha256"]) == 64


def test_mcp_contract_verify_detects_drift(tmp_path):
    path = write_contract(tmp_path / "contract.json", now="2026-05-16T00:00:00+00:00")

    assert verify_contract(path)["status"] == "ok"

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tools"][0]["description"] = "drifted"
    path.write_text(json.dumps(payload), encoding="utf-8")

    verify = verify_contract(path)

    assert verify["status"] == "fail"
    assert any(check["target"] == "contract_sha256" for check in verify["checks"])


def test_mcp_contract_cli_writes_and_verifies(tmp_path):
    path = tmp_path / "memorywiki-mcp-contract.json"
    write = subprocess.run(
        [
            sys.executable,
            "memorywiki_mcp_contract.py",
            "--out",
            str(path),
            "--now",
            "2026-05-16T00:00:00+00:00",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    verify = subprocess.run(
        [
            sys.executable,
            "memorywiki_mcp_contract.py",
            "--verify",
            str(path),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(write.stdout)["contract_path"] == str(path)
    assert json.loads(verify.stdout)["status"] == "ok"


def test_mcp_contract_rejects_symlinked_output_parent(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    import pytest

    with pytest.raises(ValueError, match="symlink"):
        write_contract(linked / "contract.json")
