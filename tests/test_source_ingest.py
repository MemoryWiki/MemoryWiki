import json
import subprocess
import sys
from pathlib import Path

from memory_system.models import SemanticMemory
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore


REPO_ROOT = Path(__file__).resolve().parents[1]


def _store(root):
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope="project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def test_source_ingest_creates_semantic_memory_without_editing_source(tmp_path):
    root = tmp_path / "memory"
    store = _store(root)
    source = store.paths.sources_dir / "karpathy.md"
    source.parent.mkdir(parents=True)
    source.write_text("sources are read-only and wiki is writable\n", encoding="utf-8")
    store.write_semantic_memory(
        SemanticMemory(
            id="unrelated",
            scope="project",
            title="Unrelated",
            content="Leave this page alone.",
            concepts=["other"],
            source_refs=[],
            confidence=0.5,
            strength=0.5,
            last_accessed=None,
            created_at="2026-05-14T10:00:00+08:00",
            updated_at="2026-05-14T10:00:00+08:00",
        )
    )
    unrelated_before = store.paths.semantic_file("unrelated").read_text(encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "source_ingest.py",
            "--root",
            str(root),
            "--source",
            "karpathy.md",
            "--id",
            "karpathy-wiki-method",
            "--title",
            "Karpathy wiki method",
            "--summary",
            "Keep raw sources read-only and update only affected wiki pages.",
            "--concept",
            "sources",
            "--concept",
            "incremental",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    loaded = store.read_semantic_memory("karpathy-wiki-method")

    assert payload["affected_paths"] == ["semantic/karpathy-wiki-method.md"]
    assert source.read_text(encoding="utf-8") == "sources are read-only and wiki is writable\n"
    assert loaded.content == "Keep raw sources read-only and update only affected wiki pages."
    assert loaded.source_refs[0].kind == "source"
    assert loaded.source_refs[0].path == "sources/karpathy.md"
    assert store.paths.source_ingest_log.exists()
    assert store.paths.semantic_file("unrelated").read_text(encoding="utf-8") == unrelated_before
    assert "| Sources | 1 files | sources/ |" in store.read_index()


def test_source_ingest_rejects_symlinked_source(tmp_path):
    root = tmp_path / "memory"
    store = _store(root)
    outside = tmp_path / "outside.md"
    outside.write_text("do not ingest through symlink\n", encoding="utf-8")
    source = store.paths.sources_dir / "link.md"
    source.parent.mkdir(parents=True)
    source.symlink_to(outside)

    result = subprocess.run(
        [
            sys.executable,
            "source_ingest.py",
            "--root",
            str(root),
            "--source",
            "link.md",
            "--id",
            "bad-source",
            "--title",
            "Bad Source",
            "--summary",
            "Should fail.",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert not store.paths.semantic_file("bad-source").exists()


def test_source_ingest_dry_run_does_not_create_missing_root(tmp_path):
    root = tmp_path / "missing-memory"

    result = subprocess.run(
        [
            sys.executable,
            "source_ingest.py",
            "--root",
            str(root),
            "--source",
            "note.md",
            "--id",
            "dry-run-source",
            "--title",
            "Dry Run Source",
            "--summary",
            "Should not create a root.",
            "--dry-run",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "must exist" in result.stderr
    assert not root.exists()


def test_source_ingest_rejects_symlinked_source_parent(tmp_path):
    root = tmp_path / "memory"
    store = _store(root)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "paper.md").write_text("do not ingest through parent symlink\n", encoding="utf-8")
    source_parent = store.paths.sources_dir / "linked"
    source_parent.parent.mkdir(parents=True)
    source_parent.symlink_to(outside_dir, target_is_directory=True)

    result = subprocess.run(
        [
            sys.executable,
            "source_ingest.py",
            "--root",
            str(root),
            "--source",
            "linked/paper.md",
            "--id",
            "bad-source-parent",
            "--title",
            "Bad Source Parent",
            "--summary",
            "Should fail.",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert not store.paths.semantic_file("bad-source-parent").exists()


def test_source_ingest_rejects_source_traversal(tmp_path):
    root = tmp_path / "memory"
    store = _store(root)
    store.paths.sources_dir.mkdir(parents=True)
    (root / "MEMORY.md").write_text("outside sources\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "source_ingest.py",
            "--root",
            str(root),
            "--source",
            "../MEMORY.md",
            "--id",
            "escape",
            "--title",
            "Escape",
            "--summary",
            "Should fail.",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "below sources" in result.stderr
    assert not store.paths.semantic_file("escape").exists()


def test_source_ingest_conflict_appends_update_log_not_overwrite(tmp_path):
    root = tmp_path / "memory"
    store = _store(root)
    store.write_semantic_memory(
        SemanticMemory(
            id="policy-status",
            scope="project",
            title="Policy status",
            content="February source said the policy was paused.",
            concepts=["policy"],
            source_refs=[],
            confidence=0.7,
            strength=0.6,
            last_accessed=None,
            created_at="2026-02-01T10:00:00+08:00",
            updated_at="2026-02-01T10:00:00+08:00",
        )
    )
    source = store.paths.sources_dir / "may-update.md"
    source.parent.mkdir(parents=True)
    source.write_text("May update says the policy restarted.\n", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "source_ingest.py",
            "--root",
            str(root),
            "--source",
            "may-update.md",
            "--conflict-with",
            "policy-status",
            "--conflict-note",
            "May source says the policy restarted.",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    loaded = store.read_semantic_memory("policy-status")
    text = store.paths.semantic_file("policy-status").read_text(encoding="utf-8")

    assert loaded.content == "February source said the policy was paused."
    assert "Conflict: May source says the policy restarted." in loaded.update_log[0]
    assert "## Update Log" in text
    assert "February source said the policy was paused." in text
