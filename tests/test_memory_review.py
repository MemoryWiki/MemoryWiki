from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from memory_crystallize_candidates import propose_candidates
from memory_feedback import append_feedback
from memory_system.models import SemanticMemory, SessionFile
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore

from memory_review import (
    apply_candidate,
    fill_golden_candidate_expected,
    promote_golden_candidate,
    render_human,
    reject_golden_candidate,
    run_review,
    summarize_golden_candidate_backlog,
    write_golden_candidates_to_pending,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _store(root: Path) -> ScopedMemoryStore:
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, "project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def _seed_candidate(root: Path) -> str:
    store = _store(root)
    store.write_session(
        SessionFile(
            id="session-20260516-020000",
            date="2026-05-16",
            scope="project",
            title="Review candidate seed",
            keypoints=["Stable decision: MemoryWiki review applies candidates one at a time."],
            actions=["Procedure: run memory_review before applying candidates."],
            pending=[],
            duration_seconds=30,
            body="Reusable insight: pending queues should not auto-promote memory.",
        )
    )
    payload = propose_candidates(
        root=root,
        limit=5,
        write=True,
        now="2026-05-16T02:00:00+00:00",
    )
    return payload["candidates"][0]["id"]


def test_memory_review_summarizes_health_feedback_and_pending_candidates(tmp_path):
    project = tmp_path / "project"
    candidate_id = _seed_candidate(project)
    append_feedback(
        root=project,
        query="MemoryWiki review workbench",
        rating="useful",
        hit_scope="project",
        hit_source="semantic",
        hit_identifier="memorywiki-review-workbench",
        reason="expected hit was top result",
        now="2026-05-16T02:00:01+00:00",
    )

    payload = run_review(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
    )

    assert payload["status"] == "review"
    assert payload["pending_candidate_count"] >= 1
    assert payload["pending_candidates"][0]["id"] == candidate_id
    assert payload["feedback_count"] == 1
    assert payload["golden_proposals"][0]["expected"] == ["memorywiki-review-workbench"]
    assert payload["apply"] is None


def test_memory_review_builds_unified_review_inbox(tmp_path):
    project = tmp_path / "project"
    candidate_id = _seed_candidate(project)
    _store(project).write_semantic_memory(
        SemanticMemory(
            id="weak",
            scope="project",
            title="Weak",
            content="weak memory",
            concepts=[],
            source_refs=[],
            confidence=0.1,
            strength=0.1,
            last_accessed=None,
            created_at="2026-05-16T00:00:00+00:00",
            updated_at="2026-05-16T00:00:00+00:00",
        )
    )
    append_feedback(
        root=project,
        query="missing recall target",
        rating="missing",
        reason="expected item was absent",
        now="2026-05-16T02:00:01+00:00",
    )

    payload = run_review(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
    )

    categories = {item["category"] for item in payload["review_inbox"]}
    assert payload["review_inbox_count"] == len(payload["review_inbox"])
    assert {
        "health",
        "feedback",
        "crystallize-candidate",
        "golden-eval",
        "health-repair",
    }.issubset(categories)
    assert any(
        item["category"] == "crystallize-candidate" and item["target"] == candidate_id
        for item in payload["review_inbox"]
    )
    assert payload["review_inbox"][0]["severity"] in {"warn", "info"}


def test_memory_review_feedback_missing_creates_incomplete_golden_proposal(tmp_path):
    project = tmp_path / "project"
    _store(project).write_core_memory("# Core Memory\n\n- ok")
    append_feedback(
        root=project,
        query="missing recall target",
        rating="missing",
        reason="expected item was absent",
        now="2026-05-16T02:00:01+00:00",
    )

    payload = run_review(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
    )

    assert payload["golden_proposals"][0]["status"] == "needs-expected-target"
    assert payload["golden_proposals"][0]["expected"] == []


def test_memory_review_writes_golden_eval_candidates_only_when_explicit(tmp_path):
    project = tmp_path / "project"
    _store(project).write_core_memory("# Core Memory\n\n- ok")
    append_feedback(
        root=project,
        query="MemoryWiki review workbench",
        rating="useful",
        hit_scope="project",
        hit_source="semantic",
        hit_identifier="memorywiki-review-workbench",
        reason="expected hit was top result",
        now="2026-05-16T02:00:01+00:00",
    )

    dry_payload = run_review(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
    )
    pending_path = project / "_pending" / "golden_eval_candidates.jsonl"

    assert dry_payload["golden_candidate_write"]["written"] == 0
    assert not pending_path.exists()

    write_payload = run_review(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
        write_golden_candidates=True,
    )
    rows = [json.loads(line) for line in pending_path.read_text(encoding="utf-8").splitlines()]

    assert write_payload["golden_candidate_write"]["written"] == 1
    assert rows[0]["event"] == "golden_eval_candidate"
    assert rows[0]["query"] == "MemoryWiki review workbench"
    assert rows[0]["expected"] == ["memorywiki-review-workbench"]
    assert rows[0]["hit_scope"] == "project"
    assert rows[0]["hit_source"] == "semantic"

    second_payload = run_review(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
        write_golden_candidates=True,
    )

    assert second_payload["golden_candidate_write"]["written"] == 0


def test_memory_review_promotes_ready_golden_candidate_to_registry_only_when_explicit(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    registry = tmp_path / "golden.json"
    write_golden_candidates_to_pending(
        project_root=project,
        global_root=global_root,
        proposals=[
            {
                "name": "feedback-useful-abc",
                "query": "MemoryWiki review workbench",
                "expected": ["memorywiki-review-workbench"],
                "status": "ready",
                "scope": "project",
                "reason": "explicit user feedback",
            }
        ],
        now="2026-05-16T03:00:00+00:00",
    )

    dry_payload = promote_golden_candidate(
        project_root=project,
        global_root=global_root,
        scope="project",
        candidate_name="feedback-useful-abc",
        registry_path=registry,
        target_scope="project",
        write=False,
        now="2026-05-16T03:01:00+00:00",
    )

    assert dry_payload["dry_run"] is True
    assert dry_payload["would_write"] == str(registry)
    assert not registry.exists()

    write_payload = promote_golden_candidate(
        project_root=project,
        global_root=global_root,
        scope="project",
        candidate_name="feedback-useful-abc",
        registry_path=registry,
        target_scope="project",
        write=True,
        now="2026-05-16T03:02:00+00:00",
    )
    registry_payload = json.loads(registry.read_text(encoding="utf-8"))
    pending_rows = [
        json.loads(line)
        for line in (project / "_pending" / "golden_eval_candidates.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert write_payload["dry_run"] is False
    project_key = str(project.resolve())
    assert registry_payload["projects"][project_key][0]["name"] == "feedback-useful-abc"
    assert registry_payload["projects"][project_key][0]["expected"] == ["memorywiki-review-workbench"]
    assert pending_rows[-1]["event"] == "golden_eval_candidate_promoted"
    assert pending_rows[-1]["name"] == "feedback-useful-abc"


def test_memory_review_refuses_to_promote_incomplete_golden_candidate(tmp_path):
    project = tmp_path / "project"
    write_golden_candidates_to_pending(
        project_root=project,
        global_root=tmp_path / "global",
        proposals=[
            {
                "name": "feedback-missing",
                "query": "missing target",
                "expected": [],
                "status": "needs-expected-target",
                "scope": "project",
            }
        ],
        now="2026-05-16T03:00:00+00:00",
    )

    with pytest.raises(ValueError, match="not ready"):
        promote_golden_candidate(
            project_root=project,
            global_root=tmp_path / "global",
            scope="project",
            candidate_name="feedback-missing",
            registry_path=tmp_path / "golden.json",
            target_scope="project",
            write=True,
        )


def test_memory_review_can_fill_expected_target_for_pending_golden_candidate(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    write_golden_candidates_to_pending(
        project_root=project,
        global_root=global_root,
        proposals=[
            {
                "name": "feedback-missing",
                "query": "missing target",
                "expected": [],
                "status": "needs-expected-target",
                "scope": "project",
                "reason": "user marked missing",
            }
        ],
        now="2026-05-16T03:00:00+00:00",
    )

    dry_payload = fill_golden_candidate_expected(
        project_root=project,
        global_root=global_root,
        scope="project",
        candidate_name="feedback-missing",
        expected=["filled-target"],
        reason="manual expected target",
        write=False,
        now="2026-05-16T03:01:00+00:00",
    )
    write_payload = fill_golden_candidate_expected(
        project_root=project,
        global_root=global_root,
        scope="project",
        candidate_name="feedback-missing",
        expected=["filled-target"],
        reason="manual expected target",
        write=True,
        now="2026-05-16T03:02:00+00:00",
    )
    pending_rows = [
        json.loads(line)
        for line in (project / "_pending" / "golden_eval_candidates.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    audit_rows = [
        json.loads(line)
        for line in (project / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    backlog = summarize_golden_candidate_backlog(
        project_root=project,
        global_root=global_root,
        scope="project",
    )

    assert dry_payload["dry_run"] is True
    assert dry_payload["candidate"]["expected"] == ["filled-target"]
    assert write_payload["dry_run"] is False
    assert pending_rows[-1]["event"] == "golden_eval_candidate"
    assert pending_rows[-1]["status"] == "ready"
    assert pending_rows[-1]["expected"] == ["filled-target"]
    assert audit_rows[-1]["action"] == "fill_golden_eval_candidate"
    assert backlog["ready_count"] == 1
    assert backlog["needs_expected_count"] == 0


def test_memory_review_can_reject_pending_golden_candidate_with_audit(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    write_golden_candidates_to_pending(
        project_root=project,
        global_root=global_root,
        proposals=[
            {
                "name": "feedback-noisy",
                "query": "noisy query",
                "expected": ["target"],
                "status": "ready",
                "scope": "project",
            }
        ],
        now="2026-05-16T03:00:00+00:00",
    )

    payload = reject_golden_candidate(
        project_root=project,
        global_root=global_root,
        scope="project",
        candidate_name="feedback-noisy",
        reason="too noisy",
        write=True,
        now="2026-05-16T03:02:00+00:00",
    )
    pending_rows = [
        json.loads(line)
        for line in (project / "_pending" / "golden_eval_candidates.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    audit_rows = [
        json.loads(line)
        for line in (project / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    backlog = summarize_golden_candidate_backlog(
        project_root=project,
        global_root=global_root,
        scope="project",
    )

    assert payload["dry_run"] is False
    assert pending_rows[-1]["event"] == "golden_eval_candidate_rejected"
    assert pending_rows[-1]["reason"] == "too noisy"
    assert audit_rows[-1]["action"] == "reject_golden_eval_candidate"
    assert backlog["candidate_count"] == 0
    assert backlog["rejected_count"] == 1


def test_memory_review_summarizes_golden_candidate_backlog(tmp_path):
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
                "name": "incomplete",
                "query": "missing query",
                "expected": [],
                "status": "needs-expected-target",
                "scope": "project",
            },
            {
                "name": "ready",
                "query": "ready query",
                "expected": ["target"],
                "status": "ready",
                "scope": "project",
            },
        ],
        now="2026-05-16T03:00:00+00:00",
    )
    pending_path = project / "_pending" / "golden_eval_candidates.jsonl"
    first_row = pending_path.read_text(encoding="utf-8").splitlines()[0]
    with pending_path.open("a", encoding="utf-8") as handle:
        handle.write(first_row + "\n")

    payload = summarize_golden_candidate_backlog(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
    )

    assert payload["candidate_count"] == 2
    assert payload["ready_count"] == 1
    assert payload["needs_expected_count"] == 1
    assert payload["duplicate_count"] == 1


def test_memory_review_outputs_golden_candidate_action_guidance(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    write_golden_candidates_to_pending(
        project_root=project,
        global_root=global_root,
        proposals=[
            {
                "name": "ready-action",
                "query": "ready action query",
                "expected": ["target"],
                "status": "ready",
                "scope": "project",
            },
            {
                "name": "fill-action",
                "query": "fill action query",
                "expected": [],
                "status": "needs-expected-target",
                "scope": "project",
            },
        ],
        now="2026-05-16T03:00:00+00:00",
    )

    payload = run_review(
        project_root=project,
        global_root=global_root,
        scope="project",
    )
    human = render_human(payload)

    promote = payload["golden_candidate_actions"]["ready"][0]["command"]
    fill = payload["golden_candidate_actions"]["needs_expected"][0]["command"]
    assert "--project-root" in promote
    assert "--global-root" in promote
    assert "--promote-golden-candidate ready-action" in promote
    assert "--fill-golden-candidate fill-action" in fill
    assert "--expected '<target>'" in fill
    assert "--reject-golden-candidate '<name>'" in payload["golden_candidate_actions"]["reject_template"]
    assert "Golden Candidate Actions" in human


def test_memory_review_promote_writes_audit_event(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    registry = tmp_path / "golden.json"
    write_golden_candidates_to_pending(
        project_root=project,
        global_root=global_root,
        proposals=[
            {
                "name": "feedback-useful-audit",
                "query": "MemoryWiki review workbench",
                "expected": ["memorywiki-review-workbench"],
                "status": "ready",
                "scope": "project",
            }
        ],
        now="2026-05-16T03:00:00+00:00",
    )

    promote_golden_candidate(
        project_root=project,
        global_root=global_root,
        scope="project",
        candidate_name="feedback-useful-audit",
        registry_path=registry,
        target_scope="project",
        write=True,
        now="2026-05-16T03:02:00+00:00",
    )
    audit_rows = [
        json.loads(line)
        for line in (project / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert audit_rows[-1]["action"] == "promote_golden_eval_candidate"
    assert audit_rows[-1]["target_id"] == "feedback-useful-audit"


def test_memory_review_rejects_symlink_pending_queue_for_golden_candidates(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / "_pending").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="Pending directory"):
        write_golden_candidates_to_pending(
            project_root=project,
            global_root=tmp_path / "global",
            proposals=[
                {
                    "name": "feedback-useful",
                    "query": "safe queue",
                    "expected": ["target"],
                    "status": "ready",
                    "scope": "project",
                }
            ],
        )


def test_memory_review_health_issues_create_dry_run_repair_proposals(tmp_path):
    project = tmp_path / "project"
    _store(project).write_semantic_memory(
        SemanticMemory(
            id="weak",
            scope="project",
            title="Weak",
            content="weak memory",
            concepts=[],
            source_refs=[],
            confidence=0.1,
            strength=0.1,
            last_accessed=None,
            created_at="2026-05-16T00:00:00+00:00",
            updated_at="2026-05-16T00:00:00+00:00",
        )
    )

    payload = run_review(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
    )

    assert payload["repair_proposals"][0]["issue_code"] == "low-confidence-memory"
    assert payload["repair_proposals"][0]["dry_run_only"] is True


def test_memory_review_includes_lifecycle_proposals(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "retrieval_feedback.jsonl").write_text(
        json.dumps({"ts": "2026-01-01T00:00:00+00:00", "event": "recall_feedback"})
        + "\n",
        encoding="utf-8",
    )

    payload = run_review(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
        lifecycle_archive_after_days=30,
    )

    assert payload["lifecycle_proposal_count"] == 1
    assert payload["lifecycle_proposals"][0]["code"] == "ledger-old-rows"


def test_memory_review_apply_candidate_is_dry_run_by_default(tmp_path):
    project = tmp_path / "project"
    candidate_id = _seed_candidate(project)

    payload = apply_candidate(
        root=project,
        candidate_id=candidate_id,
        write=False,
        now="2026-05-16T02:01:00+00:00",
    )

    assert payload["dry_run"] is True
    assert payload["would_write"].startswith("semantic/")
    assert _store(project).read_semantic_memory(candidate_id) is None
    assert not (project / "audit.jsonl").exists()


def test_memory_review_apply_candidate_writes_one_item_and_audit_when_explicit(tmp_path):
    project = tmp_path / "project"
    candidate_id = _seed_candidate(project)

    payload = apply_candidate(
        root=project,
        candidate_id=candidate_id,
        write=True,
        now="2026-05-16T02:02:00+00:00",
    )
    store = _store(project)
    audit_rows = [
        json.loads(line)
        for line in (project / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert payload["dry_run"] is False
    assert store.read_semantic_memory(candidate_id) is not None
    assert audit_rows[0]["action"] == "apply_crystallize_candidate"
    assert audit_rows[0]["target_id"] == candidate_id


def test_memory_review_cli_outputs_json(tmp_path):
    project = tmp_path / "project"
    _seed_candidate(project)

    result = subprocess.run(
        [
            sys.executable,
            "memory_review.py",
            "--project-root",
            str(project),
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
    assert payload["pending_candidate_count"] >= 1
