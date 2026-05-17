from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from memory_system.models import SemanticMemory
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore
from agent_leases import acquire_lease
from memorywiki_mcp.schema import (
    CrystallizeInput,
    ForgetInput,
    IndexMaintainInput,
    IngestSourceInput,
    ReadMemoryInput,
    WriteSessionInput,
)
from memorywiki_mcp.tools import (
    memorywiki_crystallize,
    memorywiki_forget,
    memorywiki_index_maintain,
    memorywiki_ingest_source,
    memorywiki_read_memory,
    memorywiki_write_session,
)


def _store(root: Path, scope: str = "project") -> ScopedMemoryStore:
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def test_memorywiki_write_session_requires_gate_and_writes_project_session(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")

    input_model = WriteSessionInput(
        project_root=str(project_root),
        summary="MCP v1 saves an explicit session.",
        title="MCP v1 session",
        keypoints=["gated writes"],
        actions=["saved session"],
        pending=["continue verification"],
        reason="user explicitly asked to save MemoryWiki",
    )

    with pytest.raises(PermissionError, match="MEMORY_MCP_WRITE_ENABLED"):
        memorywiki_write_session(input_model)

    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")
    output = memorywiki_write_session(input_model)

    assert output.scope == "project"
    assert output.session_id.startswith("session-")
    assert output.affected_paths
    assert (project_root / "sessions" / f"{output.session_id}.md").exists()
    assert (project_root / "audit.jsonl").exists()


def test_memorywiki_read_memory_does_not_chmod_existing_root(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    if os.name == "nt":
        pytest.skip("POSIX mode regression only")
    project_root.chmod(0o755)
    before = stat.S_IMODE(project_root.stat().st_mode)
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")

    output = memorywiki_read_memory(
        ReadMemoryInput(
            project_root=str(project_root),
            kind="semantic",
            identifier="missing-memory",
        )
    )

    assert output.found is False
    assert stat.S_IMODE(project_root.stat().st_mode) == before


def test_memorywiki_write_session_rejects_unsafe_audit_before_writing(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside-audit.jsonl"
    (project_root / "audit.jsonl").symlink_to(outside)
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")

    with pytest.raises(ValueError, match="audit|symlink"):
        memorywiki_write_session(
            WriteSessionInput(
                project_root=str(project_root),
                summary="This should not be saved.",
                reason="audit preflight test",
            )
        )

    assert not (project_root / "sessions").exists()
    assert not outside.exists()


def test_memorywiki_global_write_requires_global_gate(tmp_path, monkeypatch):
    global_root = tmp_path / "global"
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")

    input_model = WriteSessionInput(
        scope="global",
        global_root=str(global_root),
        summary="global write should need its extra gate",
        reason="test global gate",
    )

    with pytest.raises(PermissionError, match="MEMORY_GLOBAL_WRITE_ENABLED"):
        memorywiki_write_session(input_model)

    monkeypatch.setenv("MEMORY_GLOBAL_WRITE_ENABLED", "true")
    output = memorywiki_write_session(input_model)

    assert output.scope == "global"
    assert (global_root / "sessions" / f"{output.session_id}.md").exists()


def test_memorywiki_crystallize_defaults_to_dry_run_and_apply_is_gated(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    input_model = CrystallizeInput(
        project_root=str(project_root),
        kind="semantic",
        id="mcp-v1-crystal",
        title="MCP v1 Crystal",
        content="MCP v1 crystallize turns approved answers into semantic memory.",
        concepts=["mcp", "crystallize"],
        reason="approved answer",
    )

    dry_run = memorywiki_crystallize(input_model)

    assert dry_run.dry_run is True
    assert dry_run.affected_paths == ["semantic/mcp-v1-crystal.md"]
    assert not (project_root / "semantic" / "mcp-v1-crystal.md").exists()

    with pytest.raises(PermissionError, match="MEMORY_MCP_WRITE_ENABLED"):
        memorywiki_crystallize(input_model.model_copy(update={"dry_run": False}))

    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")
    applied = memorywiki_crystallize(input_model.model_copy(update={"dry_run": False}))

    assert applied.dry_run is False
    assert (project_root / "semantic" / "mcp-v1-crystal.md").exists()
    assert (project_root / "audit.jsonl").exists()


def test_memorywiki_crystallize_dry_run_does_not_create_missing_root(tmp_path, monkeypatch):
    project_root = tmp_path / "missing-project"
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")

    output = memorywiki_crystallize(
        CrystallizeInput(
            project_root=str(project_root),
            id="dry-run-no-root",
            title="Dry Run No Root",
            content="Dry-run crystallize must not create a memory root.",
            reason="verify read-only dry-run",
        )
    )

    assert output.dry_run is True
    assert not project_root.exists()


def test_memorywiki_crystallize_denied_apply_does_not_create_missing_root(tmp_path, monkeypatch):
    project_root = tmp_path / "missing-project"
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    monkeypatch.delenv("MEMORY_MCP_WRITE_ENABLED", raising=False)

    with pytest.raises(PermissionError, match="MEMORY_MCP_WRITE_ENABLED"):
        memorywiki_crystallize(
            CrystallizeInput(
                project_root=str(project_root),
                id="denied-no-root",
                title="Denied No Root",
                content="Denied crystallize must not create an empty root.",
                reason="verify denied writes are disk silent",
                dry_run=False,
            )
        )

    assert not project_root.exists()


def test_memorywiki_crystallize_rejects_unsafe_audit_before_writing(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside-audit.jsonl"
    (project_root / "audit.jsonl").symlink_to(outside)
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")

    with pytest.raises(ValueError, match="audit|symlink"):
        memorywiki_crystallize(
            CrystallizeInput(
                project_root=str(project_root),
                id="audit-preflight",
                title="Audit Preflight",
                content="This should not be crystallized.",
                reason="audit preflight test",
                dry_run=False,
            )
        )

    assert not (project_root / "semantic" / "audit-preflight.md").exists()
    assert not outside.exists()


def test_global_mcp_write_tools_check_global_gate_before_creating_root(tmp_path, monkeypatch):
    global_root = tmp_path / "missing-global"
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")
    monkeypatch.delenv("MEMORY_GLOBAL_WRITE_ENABLED", raising=False)

    with pytest.raises(PermissionError, match="MEMORY_GLOBAL_WRITE_ENABLED"):
        memorywiki_crystallize(
            CrystallizeInput(
                scope="global",
                global_root=str(global_root),
                id="global-denied-crystal",
                title="Global Denied Crystal",
                content="Global writes require the extra global gate.",
                reason="verify global gate before disk",
                dry_run=False,
            )
        )
    assert not global_root.exists()

    with pytest.raises(PermissionError, match="MEMORY_GLOBAL_WRITE_ENABLED"):
        memorywiki_ingest_source(
            IngestSourceInput(
                scope="global",
                global_root=str(global_root),
                source="note.md",
                id="global-denied-source",
                title="Global Denied Source",
                summary="Global source ingest requires the extra global gate.",
                reason="verify global gate before source resolution",
                dry_run=False,
            )
        )
    assert not global_root.exists()

    with pytest.raises(PermissionError, match="MEMORY_GLOBAL_WRITE_ENABLED"):
        memorywiki_forget(
            ForgetInput(
                scope="global",
                global_root=str(global_root),
                kind="semantic",
                identifier="global-denied-delete",
                reason="verify global gate before forget root creation",
                dry_run=False,
            )
        )
    assert not global_root.exists()


def test_memorywiki_ingest_source_is_dry_run_by_default_and_apply_writes_ledger(
    tmp_path, monkeypatch
):
    project_root = tmp_path / "project"
    sources = project_root / "sources"
    sources.mkdir(parents=True)
    (sources / "note.md").write_text("Local source about MCP v1 source ingest.", encoding="utf-8")
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    input_model = IngestSourceInput(
        project_root=str(project_root),
        source="note.md",
        id="mcp-source-ingest",
        title="MCP Source Ingest",
        summary="MCP v1 source ingest keeps SHA256 provenance.",
        concepts=["mcp", "source-ingest"],
        reason="source approved by user",
    )

    dry_run = memorywiki_ingest_source(input_model)

    assert dry_run.dry_run is True
    assert dry_run.affected_paths == ["semantic/mcp-source-ingest.md"]
    assert dry_run.source_sha256
    assert not (project_root / "semantic" / "mcp-source-ingest.md").exists()

    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")
    applied = memorywiki_ingest_source(input_model.model_copy(update={"dry_run": False}))

    assert applied.dry_run is False
    assert (project_root / "semantic" / "mcp-source-ingest.md").exists()
    rows = [
        json.loads(line)
        for line in (project_root / "source_ingest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["source_path"] == "sources/note.md"


def test_memorywiki_ingest_source_rejects_unsafe_audit_before_writing(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    sources = project_root / "sources"
    sources.mkdir(parents=True)
    (sources / "note.md").write_text("Safe source text.", encoding="utf-8")
    outside = tmp_path / "outside-audit.jsonl"
    (project_root / "audit.jsonl").symlink_to(outside)
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")

    with pytest.raises(ValueError, match="audit|symlink"):
        memorywiki_ingest_source(
            IngestSourceInput(
                project_root=str(project_root),
                source="note.md",
                id="audit-preflight-source",
                title="Audit Preflight Source",
                summary="This should not be ingested.",
                reason="audit preflight test",
                dry_run=False,
            )
        )

    assert not (project_root / "semantic" / "audit-preflight-source.md").exists()
    assert not (project_root / "source_ingest.jsonl").exists()
    assert not outside.exists()


def test_memorywiki_ingest_source_rejects_symlinked_sources(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    sources = project_root / "sources"
    sources.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside source", encoding="utf-8")
    (sources / "link.md").symlink_to(outside)
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")

    with pytest.raises(ValueError, match="symlink|Source must stay"):
        memorywiki_ingest_source(
            IngestSourceInput(
                project_root=str(project_root),
                source="link.md",
                id="symlink-source",
                title="Symlink Source",
                summary="should not ingest",
                reason="verify source sandbox",
            )
        )


def test_memorywiki_forget_dry_run_is_read_only_and_apply_deletes_with_audit(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    store = _store(project_root)
    store.write_semantic_memory(
        SemanticMemory(
            id="forget-me",
            scope="project",
            title="Forget Me",
            content="temporary memory",
            concepts=[],
            source_refs=[],
            confidence=0.5,
            strength=0.5,
            last_accessed=None,
            created_at="2026-05-15T10:00:00+08:00",
            updated_at="2026-05-15T10:00:00+08:00",
        )
    )
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    input_model = ForgetInput(
        project_root=str(project_root),
        kind="semantic",
        identifier="forget-me",
        reason="test forget",
    )

    dry_run = memorywiki_forget(input_model)

    assert dry_run.dry_run is True
    assert dry_run.existed is True
    assert dry_run.deleted is False
    assert (project_root / "semantic" / "forget-me.md").exists()
    assert not (project_root / "audit.jsonl").exists()

    with pytest.raises(PermissionError, match="MEMORY_MCP_WRITE_ENABLED"):
        memorywiki_forget(input_model.model_copy(update={"dry_run": False}))

    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")
    applied = memorywiki_forget(input_model.model_copy(update={"dry_run": False}))

    assert applied.deleted is True
    assert not (project_root / "semantic" / "forget-me.md").exists()
    assert (project_root / "audit.jsonl").exists()


def test_memorywiki_forget_rejects_unsafe_audit_before_deleting(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    store = _store(project_root)
    store.write_semantic_memory(
        SemanticMemory(
            id="keep-me",
            scope="project",
            title="Keep Me",
            content="temporary memory",
            concepts=[],
            source_refs=[],
            confidence=0.5,
            strength=0.5,
            last_accessed=None,
            created_at="2026-05-15T10:00:00+08:00",
            updated_at="2026-05-15T10:00:00+08:00",
        )
    )
    outside = tmp_path / "outside-audit.jsonl"
    (project_root / "audit.jsonl").symlink_to(outside)
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")

    with pytest.raises(ValueError, match="audit|symlink"):
        memorywiki_forget(
            ForgetInput(
                project_root=str(project_root),
                kind="semantic",
                identifier="keep-me",
                reason="audit preflight test",
                dry_run=False,
            )
        )

    assert (project_root / "semantic" / "keep-me.md").exists()
    assert not outside.exists()


def test_memorywiki_forget_dry_run_does_not_create_missing_root(tmp_path, monkeypatch):
    project_root = tmp_path / "missing-project"
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")

    output = memorywiki_forget(
        ForgetInput(
            project_root=str(project_root),
            kind="semantic",
            identifier="missing-memory",
            reason="verify dry-run read-only",
        )
    )

    assert output.dry_run is True
    assert output.existed is False
    assert output.deleted is False
    assert not project_root.exists()


def test_memorywiki_index_maintain_write_respects_existing_retrieval_lease(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    store = _store(project_root)
    store.write_semantic_memory(
        SemanticMemory(
            id="lease-conflict",
            scope="project",
            title="Lease Conflict",
            content="index rebuild should respect active retrieval-index leases",
            concepts=["mcp", "lease"],
            source_refs=[],
            confidence=0.5,
            strength=0.5,
            last_accessed=None,
            created_at="2026-05-15T10:00:00+08:00",
            updated_at="2026-05-15T10:00:00+08:00",
        )
    )
    acquire_lease(
        root=project_root,
        agent="other-agent",
        task="already rebuilding index",
        kind="retrieval-index",
        ttl_seconds=60 * 60 * 24 * 365,
        exclusive=True,
        conflicts_on="kind",
        now="2026-05-15T10:00:00+08:00",
    )
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
    monkeypatch.setenv("MEMORY_MCP_WRITE_ENABLED", "true")

    with pytest.raises(ValueError, match="Active lease conflict"):
        memorywiki_index_maintain(
            IndexMaintainInput(
                scope="project",
                write=True,
                project_root=str(project_root),
            )
        )
