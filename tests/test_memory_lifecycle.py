from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from memory_lifecycle import run_lifecycle

REPO_ROOT = Path(__file__).resolve().parents[1]


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_lifecycle_reports_old_ledger_rows_without_writing(tmp_path):
    project = tmp_path / "project"
    _append_jsonl(
        project / "retrieval_feedback.jsonl",
        [
            {"ts": "2026-01-01T00:00:00+00:00", "event": "recall_feedback", "query": "old"},
            {"ts": "2026-01-01T00:00:00+00:00", "event": "recall_feedback", "query": "old"},
            {"ts": "2026-05-16T00:00:00+00:00", "event": "recall_feedback", "query": "new"},
        ],
    )

    payload = run_lifecycle(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
        archive_after_days=30,
        max_ledger_bytes=1,
        now="2026-05-16T12:00:00+00:00",
    )

    assert payload["status"] == "proposals"
    assert payload["proposal_count"] == 3
    assert {proposal["code"] for proposal in payload["proposals"]} == {
        "ledger-duplicates",
        "ledger-large",
        "ledger-old-rows",
    }
    old_rows = [proposal for proposal in payload["proposals"] if proposal["code"] == "ledger-old-rows"][0]
    assert old_rows["ledger"] == "retrieval_feedback.jsonl"
    assert old_rows["old_row_count"] == 2
    assert not (project / "archive").exists()


def test_lifecycle_write_archives_old_rows_and_keeps_active_rows(tmp_path):
    project = tmp_path / "project"
    ledger = project / "retrieval_feedback.jsonl"
    _append_jsonl(
        ledger,
        [
            {"ts": "2026-01-01T00:00:00+00:00", "event": "recall_feedback", "query": "old"},
            {"ts": "2026-05-16T00:00:00+00:00", "event": "recall_feedback", "query": "new"},
        ],
    )

    payload = run_lifecycle(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
        archive_after_days=30,
        apply_scope="project",
        apply_ledger="retrieval_feedback.jsonl",
        write=True,
        now="2026-05-16T12:00:00+00:00",
    )
    active_rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    archive = project / "archive" / "2026-01" / "retrieval_feedback.jsonl"

    assert payload["apply"]["dry_run"] is False
    assert active_rows == [
        {"ts": "2026-05-16T00:00:00+00:00", "event": "recall_feedback", "query": "new"}
    ]
    assert archive.exists()
    assert json.loads(archive.read_text(encoding="utf-8").splitlines()[0])["query"] == "old"
    assert "retrieval_feedback.jsonl" in (project / "archive" / "2026-01" / "INDEX.md").read_text(
        encoding="utf-8"
    )


def test_lifecycle_apply_is_dry_run_without_write(tmp_path):
    project = tmp_path / "project"
    ledger = project / "audit.jsonl"
    _append_jsonl(
        ledger,
        [{"ts": "2026-01-01T00:00:00+00:00", "action": "old"}],
    )

    payload = run_lifecycle(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
        archive_after_days=30,
        apply_scope="project",
        apply_ledger="audit.jsonl",
        write=False,
        now="2026-05-16T12:00:00+00:00",
    )

    assert payload["apply"]["dry_run"] is True
    assert ledger.exists()
    assert not (project / "archive").exists()


def test_lifecycle_rejects_write_without_explicit_target(tmp_path):
    project = tmp_path / "project"
    _append_jsonl(
        project / "audit.jsonl",
        [{"ts": "2026-01-01T00:00:00+00:00", "action": "old"}],
    )

    with pytest.raises(ValueError, match="--apply-scope and --apply-ledger"):
        run_lifecycle(
            project_root=project,
            global_root=tmp_path / "global",
            scope="project",
            write=True,
            now="2026-05-16T12:00:00+00:00",
        )


def test_lifecycle_rejects_symlinked_ledger(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    project.mkdir()
    (project / "audit.jsonl").symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        run_lifecycle(
            project_root=project,
            global_root=tmp_path / "global",
            scope="project",
        )


def test_lifecycle_reports_backup_snapshot_need_when_backup_root_is_explicit(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    payload = run_lifecycle(
        project_root=project,
        global_root=tmp_path / "global",
        scope="project",
        backup_root=tmp_path / "private-remotes",
        backup_name="memorywiki-core",
    )

    assert payload["status"] == "proposals"
    assert payload["backup"]["project"]["status"] == "missing"
    assert payload["proposals"][0]["code"] == "backup-snapshot-needed"


def test_lifecycle_cli_outputs_json(tmp_path):
    project = tmp_path / "project"
    _append_jsonl(
        project / "source_ingest.jsonl",
        [{"ts": "2026-01-01T00:00:00+00:00", "source_path": "sources/a.md"}],
    )

    result = subprocess.run(
        [
            sys.executable,
            "memory_lifecycle.py",
            "--project-root",
            str(project),
            "--scope",
            "project",
            "--now",
            "2026-05-16T12:00:00+00:00",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["proposal_count"] == 1
