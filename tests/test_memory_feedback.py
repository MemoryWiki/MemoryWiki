from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from memory_system.models import SemanticMemory
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore

from memory_feedback import append_feedback


REPO_ROOT = Path(__file__).resolve().parents[1]


def _seed(root: Path) -> None:
    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(root, "project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    store.write_semantic_memory(
        SemanticMemory(
            id="feedback-target",
            scope="project",
            title="Feedback Target",
            content="Useful retrieval target about MemoryWiki feedback loops.",
            concepts=["memorywiki", "feedback"],
            source_refs=[],
            confidence=0.8,
            strength=0.8,
            last_accessed=None,
            created_at="2026-05-16T00:00:00+00:00",
            updated_at="2026-05-16T00:00:00+00:00",
        )
    )


def test_memory_feedback_appends_human_rating(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()

    row = append_feedback(
        root=root,
        query="memorywiki feedback",
        rating="useful",
        hit_scope="project",
        hit_source="semantic",
        hit_identifier="feedback-target",
        reason="top hit was correct",
        now="2026-05-16T00:00:00+00:00",
    )

    lines = (root / "retrieval_feedback.jsonl").read_text(encoding="utf-8").splitlines()
    assert row["event"] == "recall_feedback"
    assert json.loads(lines[0])["rating"] == "useful"


def test_memory_recall_can_write_explicit_trace_ledger(tmp_path):
    root = tmp_path / "memory"
    _seed(root)

    result = subprocess.run(
        [
            sys.executable,
            "memory_recall.py",
            "--project-root",
            str(root),
            "--scope",
            "project",
            "--query",
            "MemoryWiki feedback target",
            "--strategy",
            "live",
            "--trace-feedback-root",
            str(root),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    ledger_rows = [
        json.loads(line)
        for line in (root / "retrieval_feedback.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert payload["hits"][0]["identifier"] == "feedback-target"
    assert ledger_rows[0]["event"] == "recall_trace"
    assert ledger_rows[0]["query"] == "MemoryWiki feedback target"
    assert ledger_rows[0]["top_hits"][0]["identifier"] == "feedback-target"


def test_memory_feedback_cli_records_rating(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "memory_feedback.py",
            "--root",
            str(root),
            "--query",
            "memorywiki feedback",
            "--rating",
            "missing",
            "--reason",
            "expected semantic item was absent",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["rating"] == "missing"
    assert (root / "retrieval_feedback.jsonl").exists()
