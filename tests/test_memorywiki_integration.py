from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from memory_system.models import SemanticMemory
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd or REPO_ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )


def test_cli_memory_lifecycle_from_session_to_forget(tmp_path):
    project_root = tmp_path / "project-memory"

    _run(
        [
            "-m",
            "session_summary",
            "--save",
            "--project-root",
            str(project_root),
            "--summary",
            "Integration lifecycle keeps agent memory auditable.",
            "--keypoint",
            "stable lifecycle test",
            "--action",
            "saved session",
            "--format",
            "json",
        ]
    )
    _run(
        [
            "-m",
            "memory_crystallize",
            "--root",
            str(project_root),
            "--kind",
            "semantic",
            "--id",
            "integration-lifecycle",
            "--title",
            "Integration Lifecycle",
            "--answer",
            "MemoryWiki lifecycle test covers session, semantic recall, and forget.",
            "--concept",
            "integration",
            "--format",
            "json",
        ]
    )
    _run(
        [
            "-m",
            "memory_index_maintain",
            "--project-root",
            str(project_root),
            "--scope",
            "project",
            "--write",
            "--format",
            "json",
        ]
    )
    recall = _run(
        [
            "-m",
            "memory_recall",
            "--project-root",
            str(project_root),
            "--scope",
            "project",
            "--query",
            "semantic recall lifecycle",
            "--strategy",
            "hybrid",
            "--format",
            "json",
        ]
    )
    payload = json.loads(recall.stdout)
    assert any(hit["identifier"] == "integration-lifecycle" for hit in payload["hits"])

    _run(
        [
            "-m",
            "memory_forget",
            "--root",
            str(project_root),
            "--scope",
            "project",
            "--kind",
            "semantic",
            "--id",
            "integration-lifecycle",
            "--reason",
            "integration cleanup",
            "--apply",
            "--format",
            "json",
        ]
    )
    assert not (project_root / "semantic" / "integration-lifecycle.md").exists()
    assert (project_root / "audit.jsonl").exists()


def test_cross_project_recall_reads_project_and_global_layers(tmp_path):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    for root, scope, memory_id, content in (
        (project_root, "project", "local-setup", "Project local setup uses mw recall."),
        (global_root, "global", "global-pattern", "Global reusable pattern spans projects."),
    ):
        store = ScopedMemoryStore(
            MemoryScopePaths.from_root(root, scope=scope),
            sanitize_on_write=True,
            secure_permissions=False,
        )
        store.write_semantic_memory(
            SemanticMemory(
                id=memory_id,
                scope=scope,
                title=memory_id.replace("-", " ").title(),
                content=content,
                concepts=["integration"],
                source_refs=[],
                confidence=0.8,
                strength=0.7,
                last_accessed=None,
                created_at="2026-05-24T10:00:00+00:00",
                updated_at="2026-05-24T10:00:00+00:00",
            )
        )

    recall = _run(
        [
            "-m",
            "mw_cli",
            "recall",
            "--project-root",
            str(project_root),
            "--global-root",
            str(global_root),
            "--scope",
            "all",
            "--query",
            "project global pattern",
            "--format",
            "json",
        ]
    )
    identifiers = {hit["identifier"] for hit in json.loads(recall.stdout)["hits"]}
    assert {"local-setup", "global-pattern"} <= identifiers
