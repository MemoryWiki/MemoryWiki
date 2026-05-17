from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from memory_system.models import SemanticMemory, SourceRef
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore

from memory_health import run_health


REPO_ROOT = Path(__file__).resolve().parents[1]


def _store(root: Path) -> ScopedMemoryStore:
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, "project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def test_memory_health_detects_quality_and_source_issues(tmp_path):
    root = tmp_path / "memory"
    store = _store(root)
    source = root / "sources" / "brief.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("original source\n", encoding="utf-8")
    store.write_core_memory("# Core Memory\n\n" + ("x" * 80))
    store.write_semantic_memory(
        SemanticMemory(
            id="low-confidence",
            scope="project",
            title="Shared title",
            content="Duplicated content",
            concepts=["memorywiki"],
            source_refs=[
                SourceRef(
                    kind="source",
                    path="sources/brief.md",
                    identifier="badsha",
                    excerpt=None,
                ),
                SourceRef(
                    kind="source",
                    path="sources/missing.md",
                    identifier="missing",
                    excerpt=None,
                ),
            ],
            confidence=0.2,
            strength=0.3,
            last_accessed=None,
            created_at="2026-05-16T00:00:00+00:00",
            updated_at="2026-05-16T00:00:00+00:00",
            update_log=["2026-05-16 Conflict: new source disagrees"],
        )
    )
    store.write_semantic_memory(
        SemanticMemory(
            id="duplicate",
            scope="project",
            title="Shared title",
            content="Duplicated content",
            concepts=["memorywiki"],
            source_refs=[],
            confidence=0.8,
            strength=0.8,
            last_accessed=None,
            created_at="2026-05-16T00:00:00+00:00",
            updated_at="2026-05-16T00:00:00+00:00",
        )
    )

    payload = run_health(
        project_root=root,
        global_root=tmp_path / "global",
        scope="project",
        hot_file_max_bytes=40,
    )
    codes = {issue["code"] for issue in payload["issues"]}

    assert payload["status"] == "warn"
    assert "low-confidence-memory" in codes
    assert "semantic-conflict-history" in codes
    assert "duplicate-memory" in codes
    assert "source-ref-tampered" in codes
    assert "source-ref-missing" in codes
    assert "hot-file-large" in codes


def test_memory_health_cli_outputs_json(tmp_path):
    root = tmp_path / "memory"
    _store(root).write_core_memory("# Core Memory\n\n- ok")

    result = subprocess.run(
        [
            sys.executable,
            "memory_health.py",
            "--project-root",
            str(root),
            "--scope",
            "project",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["roots"][0]["scope"] == "project"


def test_memory_health_marks_source_ref_path_escape_as_outside(tmp_path):
    root = tmp_path / "memory"
    store = _store(root)
    store.write_semantic_memory(
        SemanticMemory(
            id="escape",
            scope="project",
            title="Escape",
            content="bad source ref",
            concepts=[],
            source_refs=[
                SourceRef(
                    kind="source",
                    path="sources/../../outside.md",
                    identifier="outside",
                    excerpt=None,
                )
            ],
            confidence=0.8,
            strength=0.8,
            last_accessed=None,
            created_at="2026-05-16T00:00:00+00:00",
            updated_at="2026-05-16T00:00:00+00:00",
        )
    )

    payload = run_health(
        project_root=root,
        global_root=tmp_path / "global",
        scope="project",
    )

    assert {issue["code"] for issue in payload["issues"]} == {"source-ref-outside"}
