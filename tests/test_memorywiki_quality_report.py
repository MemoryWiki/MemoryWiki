from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from memory_feedback import append_feedback
from memory_review import write_golden_candidates_to_pending
from memory_system.models import SemanticMemory
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore
from memorywiki_quality_report import run_quality_report
from retrieval_golden_eval import RetrievalCase

REPO_ROOT = Path(__file__).resolve().parents[1]


def _store(root: Path) -> ScopedMemoryStore:
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, "project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def test_quality_report_aggregates_health_feedback_freshness_and_golden_eval(tmp_path):
    project = tmp_path / "project"
    _store(project).write_semantic_memory(
        SemanticMemory(
            id="quality-target",
            scope="project",
            title="Quality Target",
            content="MemoryWiki quality report retrieves this target.",
            concepts=["memorywiki", "quality"],
            source_refs=[],
            confidence=0.2,
            strength=0.2,
            last_accessed=None,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
    )
    append_feedback(
        root=project,
        query="MemoryWiki quality report target",
        rating="missing",
        reason="expected item was absent",
        now="2026-05-16T02:00:01+00:00",
    )

    payload = run_quality_report(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
        review_due_days=30,
        now=datetime(2026, 5, 16, tzinfo=timezone.utc),
        golden_cases=[
            RetrievalCase(
                name="quality-target",
                query="MemoryWiki quality report retrieves target",
                expected=["quality-target"],
            )
        ],
        golden_strategy="live",
    )

    assert payload["status"] == "review"
    assert payload["health"]["by_code"]["low-confidence-memory"] == 1
    assert payload["feedback"]["ratings"]["missing"] == 1
    assert payload["freshness"]["review_due_count"] == 1
    assert payload["freshness"]["review_due"][0]["target"] == "semantic/quality-target.md"
    assert payload["review"]["review_inbox_count"] >= 1
    assert payload["golden_eval"]["status"] == "pass"
    assert payload["index"]["rebuild_needed"] is True
    assert payload["golden_candidates"]["candidate_count"] == 0


def test_quality_report_cli_is_read_only_when_golden_is_skipped(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "memorywiki_quality_report.py",
            "--project-root",
            str(project),
            "--scope",
            "project",
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
    assert payload["golden_eval"]["status"] == "skipped"
    assert not (project / "_pending").exists()


def test_quality_report_includes_golden_candidate_backlog(tmp_path):
    project = tmp_path / "project"
    write_golden_candidates_to_pending(
        project_root=project,
        global_root=tmp_path / "global",
        proposals=[
            {
                "name": "ready",
                "query": "ready query",
                "expected": ["target"],
                "status": "ready",
                "scope": "project",
            },
            {
                "name": "missing",
                "query": "missing query",
                "expected": [],
                "status": "needs-expected-target",
                "scope": "project",
            },
        ],
    )

    payload = run_quality_report(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
        skip_golden=True,
    )

    assert payload["status"] == "review"
    assert payload["golden_candidates"]["candidate_count"] == 2
    assert payload["golden_candidates"]["ready_count"] == 1
    assert payload["golden_candidates"]["needs_expected_count"] == 1
