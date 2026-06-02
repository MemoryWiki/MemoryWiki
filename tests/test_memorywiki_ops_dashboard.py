from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import make_memory_store as _store

from memory_review import write_golden_candidates_to_pending
from memory_system.models import SemanticMemory
from memorywiki_ops_dashboard import render_html, render_markdown, run_ops_dashboard

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_semantic(root: Path, memory_id: str, content: str) -> None:
    _store(root).write_semantic_memory(
        SemanticMemory(
            id=memory_id,
            scope="project",
            title=memory_id,
            content=content,
            concepts=["ops"],
            source_refs=[],
            confidence=0.8,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-16T10:00:00+08:00",
            updated_at="2026-05-16T10:00:00+08:00",
        )
    )


def test_ops_dashboard_summarizes_quality_project_matrix_and_actions(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    manifest = tmp_path / "manifest.json"
    config = tmp_path / "projects.json"
    workspace = tmp_path / "workspace"
    project.mkdir()
    (workspace / ".agent_memory" / "project").mkdir(parents=True)
    _write_semantic(project, "ops-target", "Ops dashboard target memory.")
    _write_semantic(
        workspace / ".agent_memory" / "project",
        "ops-target",
        "Ops dashboard target memory.",
    )
    write_golden_candidates_to_pending(
        project_root=project,
        global_root=global_root,
        proposals=[
            {
                "name": "ready-candidate",
                "query": "ready query",
                "expected": ["ops-target"],
                "status": "ready",
                "scope": "project",
            },
            {
                "name": "missing-candidate",
                "query": "missing query",
                "expected": [],
                "status": "needs-expected-target",
                "scope": "project",
            },
        ],
    )
    manifest.write_text(
        json.dumps(
            {
                "schema": "memorywiki-release-manifest-v1",
                "retrieval_baseline": {
                    "comparison": {"status": "ok", "regressions": []},
                    "current": {"case_count": 1, "mean_reciprocal_rank": 1.0},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config.write_text(
        json.dumps(
            [
                {
                    "name": "demo",
                    "path": str(workspace),
                    "required_cases_min": 1,
                    "required_cases_max": 3,
                    "cases": [
                        {
                            "name": "demo",
                            "query": "Ops dashboard target",
                            "expected": ["ops-target"],
                        }
                    ],
                }
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = run_ops_dashboard(
        project_root=project,
        global_root=global_root,
        project_matrix_config=config,
        release_manifest=manifest,
        period="daily",
        skip_golden=True,
    )
    markdown = render_markdown(payload)
    html = render_html(payload)

    assert payload["read_only"] is True
    assert payload["period"] == "daily"
    assert payload["status"] == "review"
    assert payload["quality"]["golden_candidates"]["ready_count"] == 1
    promote_command = payload["actions"]["golden_candidates"]["ready"][0]["command"]
    fill_command = payload["actions"]["golden_candidates"]["needs_expected"][0]["command"]
    assert "--project-root" in promote_command
    assert "--global-root" in promote_command
    assert "--promote-golden-candidate ready-candidate" in promote_command
    assert "--golden-case-registry" in promote_command
    assert "--fill-golden-candidate missing-candidate" in fill_command
    assert "--expected '<target>'" in fill_command
    write_action_lines = [line for line in markdown.splitlines() if "--write" in line]
    assert write_action_lines
    assert all("write approval required" in line for line in write_action_lines)
    assert str(project) in payload["actions"]["daily_command"]
    assert "--period weekly" in payload["actions"]["weekly_command"]
    assert payload["release_baseline"]["status"] == "ok"
    assert payload["embedding_readiness"]["status"] in {"available", "not-installed"}
    recommendation_categories = {
        item["category"] for item in payload["recommendations"]["items"]
    }
    assert "knowledge-formation" in recommendation_categories
    assert "cross-project-reliability" in recommendation_categories
    assert payload["recommendations"]["count"] >= 2
    assert any(
        item["write_required"] is True and "--write" in item["command"]
        for item in payload["recommendations"]["items"]
    )
    assert "# MemoryWiki Ops Dashboard" in markdown
    assert "Recommended Actions" in markdown
    assert "Golden Candidate Actions" in markdown
    assert "<html" in html
    assert "MemoryWiki Ops Dashboard" in html


def test_ops_dashboard_cli_is_read_only(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "memorywiki_ops_dashboard.py",
            "--project-root",
            str(project),
            "--global-root",
            str(tmp_path / "global"),
            "--skip-golden",
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
    assert "recommendations" in payload
    assert not (project / "_pending").exists()


def test_ops_dashboard_recommends_release_discipline_when_baseline_missing(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    payload = run_ops_dashboard(
        project_root=project,
        global_root=tmp_path / "global",
        skip_golden=True,
        skip_project_matrix=True,
    )
    recommendations = payload["recommendations"]["items"]

    assert payload["status"] == "review"
    assert any(item["category"] == "release-discipline" for item in recommendations)
    assert any("memorywiki_release_check.py" in item["command"] for item in recommendations)


def test_ops_dashboard_keeps_sentence_transformers_as_probe_only(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    payload = run_ops_dashboard(
        project_root=project,
        global_root=tmp_path / "global",
        skip_golden=True,
        skip_project_matrix=True,
    )
    embedding_actions = [
        item for item in payload["recommendations"]["items"]
        if item["category"] == "retrieval-quality"
    ]

    assert payload["embedding_readiness"]["provider"] == "sentence-transformers"
    assert all("pip install" not in item["command"] for item in embedding_actions)


def test_ops_dashboard_rejects_symlinked_release_manifest(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    real_manifest = tmp_path / "manifest.json"
    symlink_manifest = tmp_path / "manifest-link.json"
    real_manifest.write_text('{"retrieval_baseline": {"comparison": {"status": "ok"}}}\n', encoding="utf-8")
    symlink_manifest.symlink_to(real_manifest)

    with pytest.raises(ValueError, match="Release manifest must be a real file"):
        run_ops_dashboard(
            project_root=project,
            global_root=tmp_path / "global",
            release_manifest=symlink_manifest,
            skip_golden=True,
        )


def test_ops_dashboard_rejects_broken_symlink_release_manifest(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    symlink_manifest = tmp_path / "broken-manifest-link.json"
    symlink_manifest.symlink_to(tmp_path / "missing.json")

    with pytest.raises(ValueError, match="Release manifest must be a real file"):
        run_ops_dashboard(
            project_root=project,
            global_root=tmp_path / "global",
            release_manifest=symlink_manifest,
            skip_golden=True,
        )
