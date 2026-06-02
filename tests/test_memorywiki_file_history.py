from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from memory_system.models import SemanticMemory, SourceRef


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_file_history_finds_memory_mentions_without_reading_file_contents(
    tmp_path, memory_store_factory
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret_file = workspace / "src" / "app.py"
    secret_file.parent.mkdir()
    secret_file.write_text("OPENAI_API_KEY='sk-proj-secret-file'\n", encoding="utf-8")
    project_root = tmp_path / "memory"
    store = memory_store_factory(project_root)
    store.write_semantic_memory(
        SemanticMemory(
            id="app-entrypoint",
            scope="project",
            title="App entrypoint",
            content="src/app.py owns the startup flow.",
            concepts=["src/app.py"],
            source_refs=[SourceRef(kind="source", path="sources/app-note.md", identifier="abc12345")],
            confidence=0.8,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-27T09:00:00+08:00",
            updated_at="2026-05-27T09:00:00+08:00",
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "memorywiki_file_history.py",
            "--path",
            str(secret_file),
            "--workspace-root",
            str(workspace),
            "--project-root",
            str(project_root),
            "--scope",
            "project",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["path"]["relative"] == "src/app.py"
    assert payload["hits"][0]["id"] == "app-entrypoint"
    assert payload["hits"][0]["actions"][0]["tool"] == "memorywiki_read_memory"
    assert "sk-proj-secret-file" not in result.stdout


def test_file_history_rejects_symlink_target(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("outside", encoding="utf-8")
    link = workspace / "link.py"
    link.symlink_to(outside)

    result = subprocess.run(
        [
            sys.executable,
            "memorywiki_file_history.py",
            "--path",
            str(link),
            "--workspace-root",
            str(workspace),
            "--project-root",
            str(tmp_path / "memory"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "symlink" in result.stderr
