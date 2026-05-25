from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from memory_crystallize_candidates import propose_candidates
from memory_system.models import SessionFile
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def _seed(root: Path) -> None:
    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(root, "project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    store.write_session(
        SessionFile(
            id="session-20260516-010000",
            date="2026-05-16",
            scope="project",
            title="MemoryWiki V4.5 planning",
            keypoints=[
                "Stable decision: MemoryWiki V4.5 should run memory_health dry-run before release."
            ],
            actions=["Procedure: run release check after project matrix."],
            pending=[],
            duration_seconds=60,
            body="Reusable insight: health checks protect memory quality over time.",
        )
    )


def test_crystallize_candidates_propose_without_writing(tmp_path):
    root = tmp_path / "memory"
    _seed(root)

    payload = propose_candidates(root=root, limit=5, write=False)

    assert payload["status"] == "candidates"
    assert len(payload["candidates"]) >= 2
    assert {item["kind"] for item in payload["candidates"]} >= {"semantic", "procedure"}
    assert not (root / "_pending" / "crystallize-candidates.jsonl").exists()


def test_crystallize_candidates_read_only_does_not_create_missing_root(tmp_path):
    root = tmp_path / "missing-memory"

    payload = propose_candidates(root=root, limit=5, write=False)

    assert payload["status"] == "empty"
    assert payload["candidate_count"] == 0
    assert not root.exists()


def test_crystallize_candidates_write_queue_only_when_explicit(tmp_path):
    root = tmp_path / "memory"
    _seed(root)

    payload = propose_candidates(root=root, limit=3, write=True)
    queue = root / "_pending" / "crystallize-candidates.jsonl"
    rows = [json.loads(line) for line in queue.read_text(encoding="utf-8").splitlines()]

    assert payload["written"] is True
    assert len(rows) == len(payload["candidates"])
    assert rows[0]["source_kind"] == "session"


def test_crystallize_candidates_cli_outputs_json(tmp_path):
    root = tmp_path / "memory"
    _seed(root)

    result = subprocess.run(
        [
            sys.executable,
            "memory_crystallize_candidates.py",
            "--root",
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
    assert payload["status"] == "candidates"
