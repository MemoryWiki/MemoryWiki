from __future__ import annotations

import json

from conftest import make_memory_store

from memory_system.models import ProceduralMemory, SemanticMemory, SessionFile
from memorywiki_export import export_memories, main, render_export


def test_export_memories_reads_semantic_and_procedural_items(tmp_path):
    root = tmp_path / "memory"
    store = make_memory_store(root)
    store.write_semantic_memory(
        SemanticMemory(
            id="stable-fact",
            scope="project",
            title="Stable Fact",
            content="MemoryWiki exports durable facts.",
            concepts=["memory"],
            source_refs=[],
            confidence=0.8,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-26T00:00:00+00:00",
            updated_at="2026-05-26T00:00:00+00:00",
            update_log=["2026-05-26 Update: Created for export test."],
        )
    )
    store.write_procedural_memory(
        ProceduralMemory(
            id="save-session",
            scope="project",
            title="Save Session",
            trigger="User asks to save memory.",
            steps=["Ask for explicit approval.", "Run session summary."],
            source_refs=[],
            confidence=0.8,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-26T00:00:00+00:00",
            updated_at="2026-05-26T00:00:00+00:00",
        )
    )

    items = export_memories(
        project_root=root,
        global_root=tmp_path / "global",
        scope="project",
        kind="all",
    )

    identifiers = {(item.kind, item.identifier) for item in items}
    assert ("semantic", "stable-fact") in identifiers
    assert ("procedural", "save-session") in identifiers


def test_export_render_json_and_clip_long_session_body(tmp_path):
    root = tmp_path / "memory"
    store = make_memory_store(root)
    store.write_session(
        SessionFile(
            id="session-20260526-010203",
            date="2026-05-26",
            scope="project",
            title="Long Session",
            keypoints=[],
            actions=[],
            pending=[],
            duration_seconds=None,
            body="abcdef",
        )
    )

    items = export_memories(
        project_root=root,
        global_root=tmp_path / "global",
        scope="project",
        kind="session",
        max_chars=3,
    )
    rendered = render_export(items, scope="project", kind="session", format_name="json")
    payload = json.loads(rendered)

    assert payload["schema_version"] == "memorywiki.export.v1"
    assert payload["items"][0]["identifier"] == "session-20260526-010203"
    assert payload["items"][0]["truncated"] is True
    assert "[truncated]" in payload["items"][0]["content"]


def test_export_cli_writes_markdown_output(tmp_path):
    root = tmp_path / "memory"
    store = make_memory_store(root)
    store.write_core_memory("# Core\n\nMemoryWiki demo.")
    output = tmp_path / "export.md"

    result = main(
        [
            "--project-root",
            str(root),
            "--global-root",
            str(tmp_path / "global"),
            "--kind",
            "hot",
            "--format",
            "markdown",
            "--out",
            str(output),
        ]
    )

    assert result == 0
    text = output.read_text(encoding="utf-8")
    assert "# MemoryWiki Export" in text
    assert "Core Memory" in text
