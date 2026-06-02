import json
import subprocess
import sys
from pathlib import Path

from conftest import make_memory_store as _store

from memory_system.models import AuditEntry, SemanticMemory, SessionFile, SourceRef

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_timeline_json_includes_sessions_semantic_memory_and_audit(tmp_path):
    project_root = tmp_path / "project"
    store = _store(project_root)
    store.write_session(
        SessionFile(
            id="session-20260510-101500",
            date="2026-05-10",
            scope="project",
            title="Timeline session",
            keypoints=["timeline should include this"],
            actions=[],
            pending=[],
            duration_seconds=None,
            body="Timeline body.",
        )
    )
    store.write_semantic_memory(
        SemanticMemory(
            id="timeline-memory",
            scope="project",
            title="Timeline memory",
            content="Timeline semantic content.",
            concepts=["timeline"],
            source_refs=[SourceRef(kind="session", path="sessions/session-20260510-101500.md")],
            confidence=0.8,
            strength=0.6,
            last_accessed=None,
            created_at="2026-05-10T10:20:00+01:00",
            updated_at="2026-05-10T10:20:00+01:00",
        )
    )
    store.append_audit(
        AuditEntry(
            ts="2026-05-10T10:21:00+01:00",
            action="forget",
            target_kind="semantic",
            target_id="old-memory",
            reason="cleanup",
            dry_run=True,
            details={"candidate": "old-memory"},
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "memory_timeline.py",
            "--project-root",
            str(project_root),
            "--scope",
            "project",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert {event["kind"] for event in payload["events"]} >= {
        "session",
        "semantic",
        "audit",
    }
    assert any(event["id"] == "timeline-memory" for event in payload["events"])


def test_timeline_html_escapes_untrusted_memory_text(tmp_path):
    project_root = tmp_path / "project"
    store = _store(project_root)
    store.write_semantic_memory(
        SemanticMemory(
            id="unsafe-memory",
            scope="project",
            title="<script>alert(1)</script>",
            content="Do not render <img src=x onerror=alert(1)> as HTML.",
            concepts=["xss"],
            source_refs=[],
            confidence=0.5,
            strength=0.5,
            last_accessed=None,
            created_at="2026-05-10T10:20:00+01:00",
            updated_at="2026-05-10T10:20:00+01:00",
        )
    )
    out = tmp_path / "timeline.html"

    subprocess.run(
        [
            sys.executable,
            "memory_timeline.py",
            "--project-root",
            str(project_root),
            "--scope",
            "project",
            "--format",
            "html",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    html = out.read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "onerror=alert(1)" not in html


def test_timeline_html_includes_session_replay_details(tmp_path):
    project_root = tmp_path / "project"
    store = _store(project_root)
    store.write_session(
        SessionFile(
            id="session-20260510-101500",
            date="2026-05-10",
            scope="project",
            title="Replay session",
            keypoints=["Important keypoint"],
            actions=["Ran tests"],
            pending=["Review next"],
            duration_seconds=None,
            body="Replay body with <b>escaped html</b>.",
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "memory_timeline.py",
            "--project-root",
            str(project_root),
            "--scope",
            "project",
            "--format",
            "html",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Replay" in result.stdout
    assert "Important keypoint" in result.stdout
    assert "&lt;b&gt;escaped html&lt;/b&gt;" in result.stdout
    assert "<b>escaped html</b>" not in result.stdout


def test_timeline_markdown_escapes_raw_html(tmp_path):
    project_root = tmp_path / "project"
    store = _store(project_root)
    store.write_semantic_memory(
        SemanticMemory(
            id="unsafe-markdown",
            scope="project",
            title="<script>alert(1)</script>",
            content="Markdown should not keep <img src=x onerror=alert(1)> raw.",
            concepts=["xss"],
            source_refs=[],
            confidence=0.5,
            strength=0.5,
            last_accessed=None,
            created_at="2026-05-10T10:20:00+01:00",
            updated_at="2026-05-10T10:20:00+01:00",
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "memory_timeline.py",
            "--project-root",
            str(project_root),
            "--scope",
            "project",
            "--format",
            "markdown",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "<script>alert(1)</script>" not in result.stdout
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result.stdout
    assert "onerror=alert(1)" not in result.stdout


def test_timeline_rejects_symlinked_output(tmp_path):
    project_root = tmp_path / "project"
    _store(project_root)
    outside = tmp_path / "outside.html"
    outside.write_text("keep", encoding="utf-8")
    out = tmp_path / "timeline.html"
    out.symlink_to(outside)

    result = subprocess.run(
        [
            sys.executable,
            "memory_timeline.py",
            "--project-root",
            str(project_root),
            "--scope",
            "project",
            "--format",
            "html",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert outside.read_text(encoding="utf-8") == "keep"


def test_timeline_rejects_output_below_symlinked_parent(tmp_path):
    project_root = tmp_path / "project"
    _store(project_root)
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    link_parent = tmp_path / "link"
    link_parent.symlink_to(real_parent, target_is_directory=True)

    result = subprocess.run(
        [
            sys.executable,
            "memory_timeline.py",
            "--project-root",
            str(project_root),
            "--scope",
            "project",
            "--format",
            "html",
            "--out",
            str(link_parent / "timeline.html"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert not (real_parent / "timeline.html").exists()
