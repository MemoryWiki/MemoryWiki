import hashlib
import json
import subprocess
import sys
from pathlib import Path

from conftest import make_memory_store as _store

from agent_leases import acquire_lease
from memory_system.models import SemanticMemory
from memory_system.retrieval_index import local_embedding_for_index, term_counts_for_index

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_semantic(root, scope, memory_id, content):
    store = _store(root, scope)
    store.write_semantic_memory(
        SemanticMemory(
            id=memory_id,
            scope=scope,
            title=memory_id.replace("-", " ").title(),
            content=content,
            concepts=["retrieval", "index"],
            source_refs=[],
            confidence=0.8,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-15T10:00:00+08:00",
            updated_at="2026-05-15T10:00:00+08:00",
        )
    )


def _run_maintain(*args):
    return subprocess.run(
        [sys.executable, "memory_index_maintain.py", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )


def test_index_maintain_dry_run_reports_project_and_global_missing_without_writing(tmp_path):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    _write_semantic(project_root, "project", "project-index", "project index dry run")
    _write_semantic(global_root, "global", "global-index", "global index dry run")

    result = _run_maintain(
        "--project-root",
        str(project_root),
        "--global-root",
        str(global_root),
        "--scope",
        "all",
        "--format",
        "json",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["dry_run"] is True
    assert payload["rebuild_needed"] is True
    assert {item["scope"] for item in payload["roots"]} == {"project", "global"}
    assert {item["status"] for item in payload["roots"]} == {"missing_index"}
    assert not (project_root / "retrieval" / "index.jsonl").exists()
    assert not (global_root / "retrieval" / "index.jsonl").exists()


def test_index_maintain_write_rebuilds_project_and_global_indexes(tmp_path):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    _write_semantic(project_root, "project", "project-write", "project write rebuild")
    _write_semantic(global_root, "global", "global-write", "global write rebuild")

    result = _run_maintain(
        "--project-root",
        str(project_root),
        "--global-root",
        str(global_root),
        "--scope",
        "all",
        "--write",
        "--format",
        "json",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["dry_run"] is False
    assert payload["rebuild_needed"] is True
    assert payload["rebuilt"] is True
    assert {item["status"] for item in payload["roots"]} == {"current"}
    assert {item["rebuilt"] for item in payload["roots"]} == {True}
    assert (project_root / "retrieval" / "index.jsonl").exists()
    assert (global_root / "retrieval" / "index.jsonl").exists()


def test_index_maintain_detects_tampered_index_rows(tmp_path):
    project_root = tmp_path / "project"
    _write_semantic(project_root, "project", "tamper-target", "original indexed text")
    subprocess.run(
        [
            sys.executable,
            "memory_index_build.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    index_path = project_root / "retrieval" / "index.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["text"] = "tampered text that should invalidate the row"
    index_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = _run_maintain(
        "--project-root",
        str(project_root),
        "--scope",
        "project",
        "--format",
        "json",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["roots"][0]["status"] == "tampered_index"
    assert payload["roots"][0]["needs_rebuild"] is True
    assert any("text hash changed" in warning for warning in payload["roots"][0]["warnings"])


def test_index_maintain_detects_tampered_embedding_vectors(tmp_path):
    project_root = tmp_path / "project"
    _write_semantic(project_root, "project", "vector-tamper-target", "original vector text")
    subprocess.run(
        [
            sys.executable,
            "memory_index_build.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    index_path = project_root / "retrieval" / "index.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["embedding_vector"] = {"99": 1.0}
    index_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = _run_maintain(
        "--project-root",
        str(project_root),
        "--scope",
        "project",
        "--format",
        "json",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["roots"][0]["status"] == "tampered_index"
    assert any("embedding vector changed" in warning for warning in payload["roots"][0]["warnings"])


def test_index_maintain_detects_self_consistent_poisoned_index_rows(tmp_path):
    project_root = tmp_path / "project"
    _write_semantic(project_root, "project", "poison-target", "canonical retrieval text")
    subprocess.run(
        [
            sys.executable,
            "memory_index_build.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    index_path = project_root / "retrieval" / "index.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["text"] = "POISON_SENTINEL_INDEX_ONLY"
    rows[0]["text_sha256"] = hashlib.sha256(rows[0]["text"].encode("utf-8")).hexdigest()
    weighted_text = " ".join([rows[0]["title"], rows[0]["text"], " ".join(rows[0]["concepts"])])
    rows[0]["term_counts"] = term_counts_for_index(weighted_text)
    rows[0]["embedding_vector"] = local_embedding_for_index(weighted_text)
    index_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = _run_maintain(
        "--project-root",
        str(project_root),
        "--scope",
        "project",
        "--format",
        "json",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["roots"][0]["status"] == "tampered_index"
    assert any(
        "canonical content changed" in warning.lower()
        for warning in payload["roots"][0]["warnings"]
    )


def test_index_maintain_write_uses_exclusive_retrieval_index_lease(tmp_path):
    project_root = tmp_path / "project"
    _write_semantic(project_root, "project", "leased-index", "lease protected rebuild")
    acquire_lease(
        root=project_root,
        agent="other-agent",
        task="already rebuilding retrieval index",
        kind="retrieval-index",
        ttl_seconds=60 * 60 * 24 * 365,
        exclusive=True,
        conflicts_on="kind",
        now="2026-05-15T10:00:00+08:00",
    )

    result = _run_maintain(
        "--project-root",
        str(project_root),
        "--scope",
        "project",
        "--write",
        "--format",
        "json",
    )

    assert result.returncode == 2
    assert "Active lease conflict" in result.stderr
    assert not (project_root / "retrieval" / "index.jsonl").exists()
