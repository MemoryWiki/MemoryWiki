from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

import memorywiki_knowledge_ops
from memory_index_maintain import maintain_indexes
from memory_system.models import SessionFile
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore
from memorywiki_knowledge_ops import render_markdown, run_knowledge_ops


REPO_ROOT = Path(__file__).resolve().parents[1]


def _seed_session(root: Path) -> None:
    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(root, "project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    store.write_session(
        SessionFile(
            id="session-20260516-020000",
            date="2026-05-16",
            scope="project",
            title="MemoryWiki V7 planning",
            keypoints=[
                "Stable decision: MemoryWiki V7 should operate knowledge with review-first candidate queues."
            ],
            actions=[
                "Procedure: run memorywiki_knowledge_ops before release and follow write-gated actions."
            ],
            pending=[],
            duration_seconds=60,
            body="Reusable insight: productized memory needs operating loops, not more automatic writes.",
        )
    )


def _write_fake_python(path: Path) -> Path:
    if platform.system() == "Windows":
        path = path.with_suffix(".cmd")
        path.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
        return path
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def _write_mcp_config(path: Path, *, python: Path, project_root: Path, global_root: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "memorywiki-memory": {
                        "command": str(python),
                        "args": ["-m", "memorywiki_mcp", "--transport", "stdio"],
                        "env": {
                            "MEMORY_PROJECT_ROOT": str(project_root),
                            "MEMORY_GLOBAL_ROOT": str(global_root),
                        },
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_knowledge_ops_returns_five_loops_and_read_only_candidates(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    _seed_session(project)

    payload = run_knowledge_ops(
        project_root=project,
        global_root=global_root,
        skip_golden=True,
        skip_project_matrix=True,
    )
    markdown = render_markdown(payload)
    loop_ids = [loop["id"] for loop in payload["loops"]]

    assert payload["schema"] == "memorywiki-knowledge-ops-v1"
    assert payload["read_only"] is True
    assert payload["write_policy"]["default_read_only"] is True
    assert payload["adoption"]["status"] == payload["status"]
    assert payload["adoption"]["top_next_actions"]
    assert payload["top_next_actions"][0]["write_required"] is False
    assert loop_ids == [
        "knowledge-formation",
        "cross-project-rollout",
        "retrieval-quality",
        "release-discipline",
        "operator-ux",
    ]
    assert payload["knowledge_candidates"]["candidate_count"] >= 1
    assert not (project / "_pending" / "crystallize-candidates.jsonl").exists()
    knowledge = payload["loops"][0]
    assert any("memory_crystallize_candidates.py" in item["command"] for item in knowledge["actions"])
    assert any(item["write_required"] and "--write" in item["command"] for item in knowledge["actions"])
    assert "# MemoryWiki Knowledge Ops" in markdown
    assert "## Top Next Actions" in markdown
    assert "## Knowledge Formation" in markdown
    assert all(
        action["approval_required"]
        for loop in payload["loops"]
        for action in loop["actions"]
        if action["write_required"]
    )


def test_knowledge_ops_stages_candidates_only_with_explicit_flag(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    _seed_session(project)

    payload = run_knowledge_ops(
        project_root=project,
        global_root=global_root,
        skip_golden=True,
        skip_project_matrix=True,
        stage_candidates=True,
    )
    queue = project / "_pending" / "crystallize-candidates.jsonl"

    assert payload["read_only"] is False
    assert payload["stage_candidates"] is True
    assert queue.exists()
    assert payload["knowledge_candidates"]["written"] is True


def test_knowledge_ops_cli_is_read_only_by_default(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    _seed_session(project)

    result = subprocess.run(
        [
            sys.executable,
            "memorywiki_knowledge_ops.py",
            "--project-root",
            str(project),
            "--global-root",
            str(global_root),
            "--skip-golden",
            "--skip-project-matrix",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["read_only"] is True
    assert [loop["id"] for loop in payload["loops"]][-1] == "operator-ux"
    assert not (project / "_pending" / "crystallize-candidates.jsonl").exists()


def test_knowledge_ops_auto_resolves_mcp_python_for_project_matrix(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    workspace = tmp_path / "workspace"
    workspace_project = workspace / ".agent_memory" / "project"
    project.mkdir()
    global_root.mkdir()
    _seed_session(workspace_project)
    fake_python = _write_fake_python(tmp_path / "python-ok")
    root_config = tmp_path / ".mcp.json"
    workspace_config = workspace / ".mcp.json"
    _write_mcp_config(root_config, python=fake_python, project_root=project, global_root=global_root)
    _write_mcp_config(
        workspace_config,
        python=fake_python,
        project_root=workspace_project,
        global_root=global_root,
    )
    maintain_indexes(
        project_root=workspace_project,
        global_root=global_root,
        scope="all",
        write=True,
    )
    config = tmp_path / "projects.json"
    config.write_text(
        json.dumps(
            [
                {
                    "name": "demo",
                    "path": str(workspace),
                    "cases": [
                        {
                            "name": "demo-memory",
                            "query": "MemoryWiki V7 planning knowledge ops",
                            "expected": ["session-20260516-020000", "knowledge"],
                        }
                    ],
                }
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    env_key = "MEMORYWIKI_MCP_TRUSTED_PYTHON_DIRS"
    old_trusted = os.environ.get(env_key)
    os.environ[env_key] = str(tmp_path)
    try:
        payload = run_knowledge_ops(
            project_root=project,
            global_root=global_root,
            project_matrix_config=config,
            mcp_config=root_config,
            skip_golden=True,
        )
    finally:
        if old_trusted is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = old_trusted

    cross_project = [loop for loop in payload["loops"] if loop["id"] == "cross-project-rollout"][0]
    assert payload["operator"]["python"] == str(fake_python)
    assert cross_project["status"] == "ok"
    assert cross_project["signals"]["matrix_status"] == "ok"


def test_knowledge_ops_does_not_execute_untrusted_mcp_python(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    workspace = tmp_path / "workspace"
    workspace_project = workspace / ".agent_memory" / "project"
    marker = tmp_path / "executed"
    project.mkdir()
    global_root.mkdir()
    _seed_session(workspace_project)
    malicious_python = tmp_path / "python-malicious"
    malicious_python.write_text("#!/bin/sh\nprintf pwned > %s\nexit 0\n" % marker, encoding="utf-8")
    malicious_python.chmod(0o700)
    root_config = tmp_path / ".mcp.json"
    workspace_config = workspace / ".mcp.json"
    _write_mcp_config(
        root_config,
        python=malicious_python,
        project_root=project,
        global_root=global_root,
    )
    _write_mcp_config(
        workspace_config,
        python=malicious_python,
        project_root=workspace_project,
        global_root=global_root,
    )
    maintain_indexes(
        project_root=workspace_project,
        global_root=global_root,
        scope="all",
        write=True,
    )
    config = tmp_path / "projects.json"
    config.write_text(
        json.dumps(
            [
                {
                    "name": "demo",
                    "path": str(workspace),
                    "cases": [
                        {
                            "name": "demo-memory",
                            "query": "MemoryWiki V7 planning knowledge ops",
                            "expected": ["session-20260516-020000", "knowledge"],
                        }
                    ],
                }
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = run_knowledge_ops(
        project_root=project,
        global_root=global_root,
        project_matrix_config=config,
        mcp_config=root_config,
        skip_golden=True,
    )

    assert payload["operator"]["python"] == sys.executable
    assert payload["operator"]["python_source"] == "fallback"
    assert not marker.exists()


def test_knowledge_ops_marks_low_mrr_as_review(monkeypatch, tmp_path):
    def fake_dashboard(**kwargs):
        return {
            "status": "ok",
            "quality": {
                "status": "ok",
                "golden_eval": {
                    "status": "pass",
                    "passed": 3,
                    "total": 3,
                    "required_failed": 0,
                    "mean_reciprocal_rank": 0.42,
                },
            },
            "recommendations": {"status": "ok", "count": 0, "items": []},
            "project_matrix": None,
            "release_baseline": {"status": "ok", "path": ""},
            "embedding_readiness": {"status": "not-installed"},
        }

    def fake_candidates(**kwargs):
        return {
            "status": "empty",
            "candidate_count": 0,
            "written": False,
            "candidates": [],
        }

    monkeypatch.setattr(memorywiki_knowledge_ops, "run_ops_dashboard", fake_dashboard)
    monkeypatch.setattr(memorywiki_knowledge_ops, "propose_candidates", fake_candidates)

    payload = run_knowledge_ops(
        project_root=tmp_path / "project",
        global_root=tmp_path / "global",
        skip_project_matrix=True,
        min_mrr=0.75,
    )
    retrieval = [loop for loop in payload["loops"] if loop["id"] == "retrieval-quality"][0]

    assert payload["status"] == "review"
    assert retrieval["status"] == "review"
    assert retrieval["signals"]["mrr_gate"] == "review"
    assert any("MRR" in action["title"] for action in retrieval["actions"])


def test_knowledge_ops_rejects_symlinked_release_manifest(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest_link = tmp_path / "manifest-link.json"
    manifest.write_text('{"retrieval_baseline": {"comparison": {"status": "ok"}}}\n', encoding="utf-8")
    manifest_link.symlink_to(manifest)

    with pytest.raises(ValueError, match="Release manifest must be a real file"):
        run_knowledge_ops(
            project_root=project,
            global_root=tmp_path / "global",
            release_manifest=manifest_link,
            skip_golden=True,
            skip_project_matrix=True,
        )
