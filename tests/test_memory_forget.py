import json
import subprocess
import sys
from pathlib import Path

from memory_system.models import SemanticMemory
from memory_system.paths import MemoryScopePaths
from memory_system.retrieval_index import build_and_write_index
from memory_system.store import ScopedMemoryStore


REPO_ROOT = Path(__file__).resolve().parents[1]


def _store(root):
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope="project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def _write_semantic(store, memory_id="old-memory"):
    store.write_semantic_memory(
        SemanticMemory(
            id=memory_id,
            scope="project",
            title="Old memory",
            content="Forget this safely.",
            concepts=["cleanup"],
            source_refs=[],
            confidence=0.5,
            strength=0.4,
            last_accessed=None,
            created_at="2026-05-10T10:20:00+01:00",
            updated_at="2026-05-10T10:20:00+01:00",
        )
    )


def test_forget_is_dry_run_by_default_and_keeps_target(tmp_path):
    project_root = tmp_path / "project"
    store = _store(project_root)
    _write_semantic(store)

    result = subprocess.run(
        [
            sys.executable,
            "memory_forget.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
            "--kind",
            "semantic",
            "--id",
            "old-memory",
            "--reason",
            "cleanup",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["dry_run"] is True
    assert payload["deleted"] is False
    assert store.read_semantic_memory("old-memory") is not None
    assert not store.paths.audit_log.exists()


def test_forget_dry_run_does_not_create_missing_root(tmp_path):
    project_root = tmp_path / "missing-project"

    result = subprocess.run(
        [
            sys.executable,
            "memory_forget.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
            "--kind",
            "semantic",
            "--id",
            "old-memory",
            "--reason",
            "cleanup",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["dry_run"] is True
    assert payload["existed"] is False
    assert payload["deleted"] is False
    assert not project_root.exists()


def test_forget_apply_requires_reason(tmp_path):
    project_root = tmp_path / "project"
    store = _store(project_root)
    _write_semantic(store)

    result = subprocess.run(
        [
            sys.executable,
            "memory_forget.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
            "--kind",
            "semantic",
            "--id",
            "old-memory",
            "--apply",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert store.read_semantic_memory("old-memory") is not None


def test_forget_apply_deletes_target_and_records_audit(tmp_path):
    project_root = tmp_path / "project"
    store = _store(project_root)
    _write_semantic(store)

    result = subprocess.run(
        [
            sys.executable,
            "memory_forget.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
            "--kind",
            "semantic",
            "--id",
            "old-memory",
            "--reason",
            "requested cleanup",
            "--apply",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    audit = store.read_audit()

    assert payload["deleted"] is True
    assert store.read_semantic_memory("old-memory") is None
    assert audit[-1].action == "forget"
    assert audit[-1].target_kind == "semantic"
    assert audit[-1].dry_run is False


def test_forget_apply_removes_forgotten_text_from_generated_indexes(tmp_path):
    project_root = tmp_path / "project"
    store = _store(project_root)
    sentinel = "SYNTHETIC_FORGET_SENTINEL_12345"
    _write_semantic(store, memory_id="forgotten-secret")
    item = store.read_semantic_memory("forgotten-secret")
    item.content = "Forget generated sidecars %s." % sentinel
    store.write_semantic_memory(item)
    store.refresh_index()
    build_and_write_index(store, "project")

    result = subprocess.run(
        [
            sys.executable,
            "memory_forget.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
            "--kind",
            "semantic",
            "--id",
            "forgotten-secret",
            "--reason",
            "privacy deletion completeness",
            "--apply",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["deleted"] is True
    for path in (store.paths.index, store.paths.retrieval_index):
        if path.exists():
            assert sentinel not in path.read_text(encoding="utf-8")


def test_forget_rejects_path_traversal_id(tmp_path):
    project_root = tmp_path / "project"
    _store(project_root)

    result = subprocess.run(
        [
            sys.executable,
            "memory_forget.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
            "--kind",
            "semantic",
            "--id",
            "../outside",
            "--reason",
            "bad id",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert not (tmp_path / "outside.md").exists()
