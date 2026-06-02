"""MCP tool handlers that bridge MemoryWiki commands to gated local memory operations."""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

MEMORYWIKI_ROOT = Path(__file__).resolve().parents[1]
if str(MEMORYWIKI_ROOT) not in sys.path:
    sys.path.insert(0, str(MEMORYWIKI_ROOT))

from memory_index_maintain import maintain_indexes
from memory_recall import recall as recall_memory
from memorywiki_context import build_context
from memory_system.models import (
    AuditEntry,
    EpisodeFile,
    ProceduralMemory,
    SemanticMemory,
    SessionFile,
    SourceRef,
)
from memory_system.paths import MemoryScopePaths
from memory_system.retrieval_index import build_and_write_index
from memory_system.store import ScopedMemoryStore
from memory_system.store_guard import require_scoped_store
from memorywiki_list import entries_to_dicts, list_memories
from memorywiki_mcp.safety import (
    clipped_output,
    require_mcp_write_enabled,
    resolve_global_root,
    resolve_project_root,
    safe_json,
    safe_output_text,
    screen_tool_input,
)
from memorywiki_mcp.schema import (
    CrystallizeInput,
    CrystallizeOutput,
    ContextInput,
    ContextOutput,
    ForgetInput,
    ForgetOutput,
    IndexMaintainInput,
    IndexMaintainOutput,
    IndexRootStatus,
    IngestSourceInput,
    IngestSourceOutput,
    ListInput,
    ListMemoryItem,
    ListOutput,
    ReadMemoryInput,
    ReadMemoryOutput,
    RecallHitOutput,
    RecallInput,
    RecallOutput,
    WriteSessionInput,
    WriteSessionOutput,
)
from session_summary import save_summary

MAX_SOURCE_BYTES = 2_000_000
MAX_OUTPUT_REFS = 12
MAX_OUTPUT_UPDATE_LOG_ITEMS = 20
MAX_OUTPUT_REF_FIELD_CHARS = 500
MAX_OUTPUT_METADATA_TEXT_CHARS = 1_000


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _store_if_exists(root: Path, scope: str) -> ScopedMemoryStore | None:
    root = root.expanduser()
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Memory root must be a real directory: {root}")
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def _root_for_scope(input_model: Any, scope: str) -> Path:
    if scope == "global":
        return resolve_global_root(input_model.global_root)
    return resolve_project_root(input_model.project_root)


def _paths_for_scope(input_model: Any, scope: str) -> MemoryScopePaths:
    return MemoryScopePaths.from_root(_root_for_scope(input_model, scope), scope=scope)


def _store_for_scope(input_model: Any, scope: str) -> ScopedMemoryStore:
    root = _root_for_scope(input_model, scope)
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise ValueError(f"Memory root must be a real directory: {root}")
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=True,
    )


def _append_mcp_audit(
    store: ScopedMemoryStore,
    action: str,
    target_kind: str,
    target_id: str,
    reason: str,
    dry_run: bool,
    details: dict[str, Any],
) -> None:
    store.append_audit(
        AuditEntry(
            ts=_now(),
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            reason=reason,
            dry_run=dry_run,
            details=details,
        )
    )


def _assert_mcp_audit_ready(store: ScopedMemoryStore) -> None:
    """Fail before gated MCP writes if the audit ledger cannot be safely appended."""
    store._assert_mutable_managed_path(store.paths.audit_log)
    if store.paths.audit_log.exists() and not store.paths.audit_log.is_file():
        raise ValueError(f"MCP audit log must be a regular file: {store.paths.audit_log}")


def _source_refs_from_input(
    source_kind: str,
    source_path: str | None,
    source_id: str | None,
) -> list[SourceRef]:
    if not source_path:
        return []
    return [
        SourceRef(
            kind=source_kind,
            path=source_path,
            identifier=source_id,
            excerpt=None,
        )
    ]


def _safe_clipped(value: str | None, max_chars: int = MAX_OUTPUT_METADATA_TEXT_CHARS) -> str | None:
    if value is None:
        return None
    text, _ = clipped_output(str(value), max_chars)
    return text


def _source_ref_output(ref: SourceRef) -> dict[str, Any]:
    return {
        "kind": _safe_clipped(ref.kind, 80) or "",
        "path": _safe_clipped(ref.path, MAX_OUTPUT_REF_FIELD_CHARS) or "",
        "identifier": _safe_clipped(ref.identifier, 240),
        "excerpt": _safe_clipped(ref.excerpt, MAX_OUTPUT_REF_FIELD_CHARS),
    }


def _source_refs_output(refs: list[SourceRef]) -> list[dict[str, Any]]:
    rows = [_source_ref_output(ref) for ref in refs[:MAX_OUTPUT_REFS]]
    if len(refs) > MAX_OUTPUT_REFS:
        rows.append(
            {
                "kind": "metadata",
                "path": f"[TRUNCATED_SOURCE_REFS:{len(refs) - MAX_OUTPUT_REFS}]",
                "identifier": None,
                "excerpt": None,
            }
        )
    return rows


def _text_list_output(
    entries: list[str],
    max_items: int = MAX_OUTPUT_UPDATE_LOG_ITEMS,
    max_chars: int = MAX_OUTPUT_METADATA_TEXT_CHARS,
) -> list[str]:
    rows = [(_safe_clipped(entry, max_chars) or "") for entry in entries[:max_items]]
    if len(entries) > max_items:
        rows.append(f"[TRUNCATED_ITEMS:{len(entries) - max_items}]")
    return rows


def _json_metadata_output(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            safe_output_text(str(key))[:128]: _json_metadata_output(item)
            for key, item in list(value.items())[:50]
        }
    if isinstance(value, list):
        rows = [_json_metadata_output(item) for item in value[:MAX_OUTPUT_UPDATE_LOG_ITEMS]]
        if len(value) > MAX_OUTPUT_UPDATE_LOG_ITEMS:
            rows.append(f"[TRUNCATED_ITEMS:{len(value) - MAX_OUTPUT_UPDATE_LOG_ITEMS}]")
        return rows
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _safe_clipped(str(value), MAX_OUTPUT_METADATA_TEXT_CHARS)


def _target_path(store: ScopedMemoryStore, kind: str, identifier: str) -> Path:
    return _target_path_for_paths(store.paths, kind, identifier)


def _target_path_for_paths(paths: MemoryScopePaths, kind: str, identifier: str) -> Path:
    if kind == "semantic":
        return paths.semantic_file(identifier)
    if kind == "procedure":
        return paths.procedure_file(identifier)
    if kind == "session":
        return paths.session_file(identifier)
    if kind == "episode":
        return paths.episode_for_date(identifier)
    raise ValueError(f"Unsupported memory kind: {kind}")


def _frontmatter_for_semantic(item: SemanticMemory) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        safe_json(
        {
            "id": item.id,
            "scope": item.scope,
            "title": item.title,
            "concepts": item.concepts,
            "confidence": item.confidence,
            "strength": item.strength,
            "last_accessed": item.last_accessed,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "source_refs": _source_refs_output(item.source_refs),
        }
        ),
    )


def _frontmatter_for_procedure(item: ProceduralMemory) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        safe_json(
        {
            "id": item.id,
            "scope": item.scope,
            "title": item.title,
            "trigger": item.trigger,
            "steps": item.steps,
            "confidence": item.confidence,
            "strength": item.strength,
            "last_accessed": item.last_accessed,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "source_refs": _source_refs_output(item.source_refs),
        }
        ),
    )


def _frontmatter_for_session(item: SessionFile) -> dict[str, Any]:
    frontmatter = asdict(item)
    frontmatter.pop("body", None)
    return cast(dict[str, Any], safe_json(frontmatter))


def _frontmatter_for_episode(item: EpisodeFile) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        safe_json(
        {
            "date": item.date,
            "scope": item.scope,
            "sessions": [asdict(session) for session in item.sessions],
        }
        ),
    )


def _read_hot_file(store: ScopedMemoryStore, kind: str) -> tuple[str, dict[str, Any], str] | None:
    path_by_kind = {
        "core": store.paths.core_memory,
        "user": store.paths.user_memory,
        "index": store.paths.index,
        "project_profile": store.paths.project_profile,
    }
    path = path_by_kind[kind]
    if not store._is_safe_readable_file(path):
        return None
    text = store._read_text_bounded(path)
    return text, {"path": path.name}, kind


def memorywiki_read_memory(input_model: ReadMemoryInput) -> ReadMemoryOutput:
    screen_tool_input("memorywiki_read_memory", input_model.model_dump())
    scope = input_model.scope
    root = _root_for_scope(input_model, scope)
    store = _store_if_exists(root, scope)
    kind = "procedural" if input_model.kind == "procedure" else input_model.kind
    identifier = input_model.identifier
    if store is None:
        return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=identifier)

    content = ""
    frontmatter: dict[str, Any] = {}
    update_log: list[str] = []
    found_identifier = identifier
    if kind == "semantic":
        if not identifier:
            raise ValueError("identifier is required for semantic memory")
        semantic_item = store.read_semantic_memory(identifier)
        if semantic_item is None:
            return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=identifier)
        content = semantic_item.content
        frontmatter = _frontmatter_for_semantic(semantic_item)
        update_log = _text_list_output(semantic_item.update_log)
        found_identifier = semantic_item.id
    elif kind == "procedural":
        if not identifier:
            raise ValueError("identifier is required for procedural memory")
        procedure_item = store.read_procedural_memory(identifier)
        if procedure_item is None:
            return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=identifier)
        content = "\n".join([procedure_item.trigger] + procedure_item.steps)
        frontmatter = _frontmatter_for_procedure(procedure_item)
        found_identifier = procedure_item.id
    elif kind == "session":
        if not identifier:
            raise ValueError("identifier is required for session memory")
        session_item = store.read_session(identifier)
        if session_item is None:
            return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=identifier)
        content = session_item.body
        frontmatter = _frontmatter_for_session(session_item)
        found_identifier = session_item.id
    elif kind == "episode":
        if not identifier:
            raise ValueError("identifier is required for episode memory")
        episode_item = store.read_episode(identifier)
        if episode_item is None:
            return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=identifier)
        content = episode_item.body
        frontmatter = _frontmatter_for_episode(episode_item)
        found_identifier = episode_item.date
    elif kind in {"core", "user", "index", "project_profile"}:
        hot = _read_hot_file(store, kind)
        if hot is None:
            return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=kind)
        content, frontmatter, found_identifier = hot
        frontmatter = safe_json(frontmatter)
    else:
        raise ValueError(f"Unsupported memory kind: {kind}")

    clipped, truncated = clipped_output(content, input_model.max_chars, input_model.full)
    return ReadMemoryOutput(
        found=True,
        scope=scope,
        kind=kind,
        identifier=found_identifier,
        content=clipped,
        frontmatter=frontmatter,
        update_log=update_log,
        truncated=truncated,
    )


def memorywiki_recall(input_model: RecallInput) -> RecallOutput:
    screen_tool_input("memorywiki_recall", input_model.model_dump())
    if input_model.refresh_index_if_needed:
        if input_model.scope in ("global", "all"):
            require_mcp_write_enabled(scope="global")
        else:
            require_mcp_write_enabled(scope="project")
    args = SimpleNamespace(
        query=input_model.query,
        scope=input_model.scope,
        project_root=str(resolve_project_root(input_model.project_root)),
        global_root=str(resolve_global_root(input_model.global_root)),
        limit=input_model.limit,
        token_budget=input_model.token_budget,
        embedding=input_model.embedding,
        graph=input_model.graph,
        ranker=input_model.ranker,
        granularity_router=input_model.granularity_router,
        association_reranker=input_model.association_reranker,
        strategy=input_model.strategy,
        refresh_index_if_needed=input_model.refresh_index_if_needed,
    )
    result = recall_memory(args)
    hits = []
    for hit in result.hits:
        explanation = _json_metadata_output(hit.score_explanation) if input_model.explain_score else {}
        hits.append(
            RecallHitOutput(
                scope=safe_output_text(hit.scope),
                source=safe_output_text(hit.source),
                identifier=safe_output_text(hit.identifier),
                title=safe_output_text(hit.title),
                excerpt=safe_output_text(hit.excerpt),
                score=round(hit.score, 4),
                tokens=hit.tokens,
                provenance=_source_refs_output(hit.provenance),
                score_explanation=explanation,
            )
        )
    return RecallOutput(
        query=safe_output_text(input_model.query),
        strategy=result.strategy,
        tokens_used=result.tokens_used,
        truncated=result.truncated,
        warnings=[safe_output_text(warning) for warning in result.warnings],
        hits=hits,
    )


def memorywiki_context(input_model: ContextInput) -> ContextOutput:
    screen_tool_input("memorywiki_context", input_model.model_dump())
    if input_model.refresh_index_if_needed:
        if input_model.scope in ("global", "all"):
            require_mcp_write_enabled(scope="global")
        else:
            require_mcp_write_enabled(scope="project")
    payload = build_context(
        project_root=resolve_project_root(input_model.project_root),
        global_root=resolve_global_root(input_model.global_root),
        scope=input_model.scope,
        mode=input_model.mode,
        query=input_model.query or "",
        limit=input_model.limit,
        token_budget=input_model.token_budget,
        max_chars=input_model.max_chars,
        include_recall=input_model.include_recall,
        include_health=input_model.include_health,
        include_actions=input_model.include_actions,
        include_excerpts=input_model.include_excerpts,
        embedding=input_model.embedding,
        graph=input_model.graph,
        strategy=input_model.strategy,
        refresh_index_if_needed=input_model.refresh_index_if_needed,
    )
    return ContextOutput(**safe_json(payload))


def memorywiki_list(input_model: ListInput) -> ListOutput:
    screen_tool_input("memorywiki_list", input_model.model_dump())
    entries = list_memories(
        project_root=resolve_project_root(input_model.project_root),
        global_root=resolve_global_root(input_model.global_root),
        scope=input_model.scope,
        kind=input_model.kind,
        concepts=input_model.concepts,
        limit=input_model.limit,
    )
    rows = []
    for payload in entries_to_dicts(entries):
        rows.append(
            ListMemoryItem(
                scope=safe_output_text(payload["scope"]),
                kind=safe_output_text(payload["kind"]),
                identifier=safe_output_text(payload["identifier"]),
                title=safe_output_text(payload["title"]),
                created_at=safe_output_text(payload["created_at"]),
                updated_at=safe_output_text(payload["updated_at"]),
                concepts=[safe_output_text(concept) for concept in payload["concepts"]],
                confidence=payload["confidence"],
                strength=payload["strength"],
            )
        )
    return ListOutput(
        scope=safe_output_text(input_model.scope),
        kind=safe_output_text(input_model.kind),
        count=len(rows),
        memories=rows,
    )


def memorywiki_index_maintain(input_model: IndexMaintainInput) -> IndexMaintainOutput:
    screen_tool_input("memorywiki_index_maintain", input_model.model_dump())
    if input_model.write:
        if input_model.scope in ("global", "all"):
            require_mcp_write_enabled(scope="global")
        else:
            require_mcp_write_enabled(scope="project")
    payload = maintain_indexes(
        project_root=resolve_project_root(input_model.project_root),
        global_root=resolve_global_root(input_model.global_root),
        scope=input_model.scope,
        write=input_model.write,
        agent=input_model.agent,
        ttl_seconds=input_model.lease_ttl_seconds,
    )
    return IndexMaintainOutput(
        dry_run=payload["dry_run"],
        scope=payload["scope"],
        rebuild_needed=payload["rebuild_needed"],
        rebuilt=payload["rebuilt"],
        roots=[
            IndexRootStatus(
                scope=safe_output_text(item["scope"]),
                root=safe_output_text(item["root"]),
                index_path=safe_output_text(item["index_path"]),
                status=safe_output_text(item["status"]),
                fresh=bool(item["fresh"]),
                needs_rebuild=bool(item["needs_rebuild"]),
                rebuilt=bool(item["rebuilt"]),
                indexed=int(item["indexed"]),
                warnings=[safe_output_text(warning) for warning in item["warnings"]],
                lease_id=safe_output_text(item["lease_id"]) if item["lease_id"] else None,
            )
            for item in payload["roots"]
        ],
    )


def memorywiki_write_session(input_model: WriteSessionInput) -> WriteSessionOutput:
    screen_tool_input("memorywiki_write_session", input_model.model_dump())
    require_mcp_write_enabled(scope=input_model.scope)
    root = _root_for_scope(input_model, input_model.scope)
    store = _store_for_scope(input_model, input_model.scope)
    _assert_mcp_audit_ready(store)
    session = save_summary(
        summary=input_model.summary,
        session_id=input_model.session_id,
        title=input_model.title,
        key_points=input_model.keypoints,
        actions_taken=input_model.actions,
        pending_tasks=input_model.pending,
        body=input_model.body,
        duration_seconds=input_model.duration_seconds,
        project_root=str(root) if input_model.scope == "project" else None,
        global_root=str(root) if input_model.scope == "global" else None,
        scope=input_model.scope,
        write_episode=input_model.write_episode,
    )
    affected = [
        "sessions.jsonl",
        f"sessions/{session.session_id}.md",
    ]
    if input_model.write_episode:
        affected.append(f"episodes/{session.ts[:10]}.md")
    _append_mcp_audit(
        store,
        action="memorywiki_write_session",
        target_kind="session",
        target_id=session.session_id,
        reason=input_model.reason,
        dry_run=False,
        details={"affected_paths": affected},
    )
    store.refresh_index()
    return WriteSessionOutput(
        scope=safe_output_text(input_model.scope),
        session_id=safe_output_text(session.session_id),
        dry_run=False,
        affected_paths=[safe_output_text(path) for path in affected],
    )


def memorywiki_crystallize(input_model: CrystallizeInput) -> CrystallizeOutput:
    screen_tool_input("memorywiki_crystallize", input_model.model_dump())
    root = _root_for_scope(input_model, input_model.scope)
    if not input_model.dry_run:
        require_mcp_write_enabled(scope=input_model.scope)
    store = (
        _store_if_exists(root, input_model.scope)
        if input_model.dry_run
        else _store_for_scope(input_model, input_model.scope)
    )
    timestamp = _now()
    refs = _source_refs_from_input(
        input_model.source_kind,
        input_model.source_path,
        input_model.source_id,
    )
    affected_path = (
        f"semantic/{input_model.id}.md"
        if input_model.kind == "semantic"
        else f"procedures/{input_model.id}.md"
    )
    replaced = False

    if input_model.kind == "semantic":
        existing = store.read_semantic_memory(input_model.id) if store is not None else None
        replaced = existing is not None
        if existing is not None and not input_model.replace:
            raise ValueError(f"semantic memory already exists; set replace=true: {input_model.id}")
        semantic_refs = refs
        if existing is not None:
            store_for_merge = require_scoped_store(
                store,
                root=root,
                operation="memorywiki_crystallize semantic merge",
            )
            semantic_refs = store_for_merge._merge_source_refs(existing.source_refs, refs)
        semantic_item = SemanticMemory(
            id=input_model.id,
            scope=input_model.scope,
            title=input_model.title,
            content=input_model.content,
            concepts=input_model.concepts,
            source_refs=semantic_refs,
            confidence=input_model.confidence,
            strength=input_model.strength,
            last_accessed=None,
            created_at=existing.created_at if existing else timestamp,
            updated_at=timestamp,
            update_log=(
                list(existing.update_log)
                + [f"{timestamp} Update: Replaced from MCP crystallize."]
                if existing
                else []
            ),
        )
        if not input_model.dry_run:
            store = require_scoped_store(
                store,
                root=root,
                operation="memorywiki_crystallize semantic write",
            )
            _assert_mcp_audit_ready(store)
            store.write_semantic_memory(semantic_item)
    else:
        procedural_existing = (
            store.read_procedural_memory(input_model.id) if store is not None else None
        )
        replaced = procedural_existing is not None
        if procedural_existing is not None and not input_model.replace:
            raise ValueError(f"procedure already exists; set replace=true: {input_model.id}")
        procedure_refs = refs
        if procedural_existing is not None:
            store_for_merge = require_scoped_store(
                store,
                root=root,
                operation="memorywiki_crystallize procedure merge",
            )
            procedure_refs = store_for_merge._merge_source_refs(
                procedural_existing.source_refs,
                refs,
            )
        steps = input_model.steps or [
            line.strip("- ").strip()
            for line in input_model.content.splitlines()
            if line.strip()
        ]
        procedure_item = ProceduralMemory(
            id=input_model.id,
            scope=input_model.scope,
            title=input_model.title,
            trigger=input_model.trigger or input_model.content[:240],
            steps=steps,
            source_refs=procedure_refs,
            confidence=input_model.confidence,
            strength=input_model.strength,
            last_accessed=None,
            created_at=procedural_existing.created_at if procedural_existing else timestamp,
            updated_at=timestamp,
        )
        if not input_model.dry_run:
            store = require_scoped_store(
                store,
                root=root,
                operation="memorywiki_crystallize procedure write",
            )
            _assert_mcp_audit_ready(store)
            store.write_procedural_memory(procedure_item)

    if not input_model.dry_run:
        store = require_scoped_store(
            store,
            root=root,
            operation="memorywiki_crystallize audit",
        )
        _append_mcp_audit(
            store,
            action="memorywiki_crystallize",
            target_kind=input_model.kind,
            target_id=input_model.id,
            reason=input_model.reason,
            dry_run=False,
            details={"affected_paths": [affected_path], "replaced": replaced},
        )
        store.refresh_index()
    return CrystallizeOutput(
        scope=safe_output_text(input_model.scope),
        kind=safe_output_text(input_model.kind),
        id=safe_output_text(input_model.id),
        dry_run=input_model.dry_run,
        affected_paths=[safe_output_text(affected_path)],
        replaced=replaced,
    )


def _assert_no_symlink_components(path: Path, root: Path) -> None:
    root_resolved = root.resolve(strict=True)
    cursor = path
    checked = []
    while True:
        checked.append(cursor)
        if cursor == root or cursor.parent == cursor:
            break
        cursor = cursor.parent
    for item in checked:
        if item.exists() and item.is_symlink():
            raise ValueError(f"Source path may not include symlinks: {item}")
        try:
            item.resolve(strict=False).relative_to(root_resolved)
        except ValueError:
            raise ValueError(f"Source must stay below sources/: {path}")


def _resolve_source(store: ScopedMemoryStore, source: str) -> Path:
    sources_dir = store.paths.sources_dir
    if not sources_dir.exists() or sources_dir.is_symlink() or not sources_dir.is_dir():
        raise ValueError(f"sources/ must be a real directory: {sources_dir}")
    candidate = Path(source).expanduser()
    if not candidate.is_absolute():
        candidate = sources_dir / candidate
    _assert_no_symlink_components(candidate, sources_dir)
    try:
        resolved_source = candidate.resolve(strict=True)
        resolved_source.relative_to(sources_dir.resolve(strict=True))
    except (OSError, ValueError):
        raise ValueError(f"Source must stay below sources/: {source}")
    if not resolved_source.is_file():
        raise ValueError(f"Source document must be a file: {candidate}")
    if resolved_source.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError(f"Source document is too large: {candidate}")
    return resolved_source


def _read_source(path: Path) -> tuple[bytes, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        if path.is_symlink():
            raise ValueError(f"Source document may not be a symlink: {path}")
        raise
    try:
        size = os.fstat(fd).st_size
        if size > MAX_SOURCE_BYTES:
            raise ValueError(f"Source document is too large: {path}")
        raw = os.read(fd, size)
    finally:
        os.close(fd)
    return raw, safe_output_text(raw.decode("utf-8", errors="replace"))


def _source_ref(store: ScopedMemoryStore, path: Path, digest: str, text: str) -> SourceRef:
    return SourceRef(
        kind="source",
        path=f"sources/{path.relative_to(store.paths.sources_dir.resolve()).as_posix()}",
        identifier=digest[:16],
        excerpt=" ".join(text.split())[:240] or None,
    )


def memorywiki_ingest_source(input_model: IngestSourceInput) -> IngestSourceOutput:
    screen_tool_input("memorywiki_ingest_source", input_model.model_dump())
    root = _root_for_scope(input_model, input_model.scope)
    if not input_model.dry_run:
        require_mcp_write_enabled(scope=input_model.scope)
    store = (
        _store_if_exists(root, input_model.scope)
        if input_model.dry_run
        else _store_for_scope(input_model, input_model.scope)
    )
    if store is None:
        raise ValueError(f"Memory root does not exist: {root}")
    source_path = _resolve_source(store, input_model.source)
    raw, text = _read_source(source_path)
    digest = hashlib.sha256(raw).hexdigest()
    ref = _source_ref(store, source_path, digest, text)
    timestamp = _now()
    affected_paths: list[str] = []
    if not input_model.dry_run:
        _assert_mcp_audit_ready(store)

    if input_model.conflict_with:
        note = input_model.conflict_note or input_model.summary or "New source conflicts with this memory."
        if store.read_semantic_memory(input_model.conflict_with) is None:
            raise ValueError(f"Unknown semantic memory: {input_model.conflict_with}")
        affected_paths.append(f"semantic/{input_model.conflict_with}.md")
        if not input_model.dry_run:
            store.append_semantic_update_log(
                input_model.conflict_with,
                note,
                source_refs=[ref],
                conflict=True,
                now=timestamp,
            )
    elif input_model.target_kind == "semantic":
        if not input_model.id or not input_model.title or not input_model.summary:
            raise ValueError("id, title, and summary are required for semantic source ingest")
        existing = store.read_semantic_memory(input_model.id)
        update_log = list(existing.update_log) if existing else []
        if existing:
            update_log.append(f"{timestamp} Update: Refreshed from {ref.path}")
        semantic_item = SemanticMemory(
            id=input_model.id,
            scope=input_model.scope,
            title=input_model.title,
            content=input_model.summary,
            concepts=input_model.concepts,
            source_refs=store._merge_source_refs(existing.source_refs if existing else [], [ref]),
            confidence=input_model.confidence,
            strength=input_model.strength,
            last_accessed=None,
            created_at=existing.created_at if existing else timestamp,
            updated_at=timestamp,
            update_log=update_log,
        )
        affected_paths.append(f"semantic/{input_model.id}.md")
        if not input_model.dry_run:
            store.write_semantic_memory(semantic_item)
    else:
        if not input_model.id or not input_model.title:
            raise ValueError("id and title are required for procedure source ingest")
        procedure_item = ProceduralMemory(
            id=input_model.id,
            scope=input_model.scope,
            title=input_model.title,
            trigger=input_model.trigger or input_model.summary or text[:300],
            steps=input_model.steps or ([input_model.summary] if input_model.summary else []),
            source_refs=[ref],
            confidence=input_model.confidence,
            strength=input_model.strength,
            last_accessed=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        affected_paths.append(f"procedures/{input_model.id}.md")
        if not input_model.dry_run:
            store.write_procedural_memory(procedure_item)

    if not input_model.dry_run:
        ledger_row = {
            "ts": timestamp,
            "source_path": ref.path,
            "source_sha256": digest,
            "source_bytes": len(raw),
            "affected_paths": affected_paths,
            "dry_run": False,
        }
        store.append_source_ingest(ledger_row)
        _append_mcp_audit(
            store,
            action="memorywiki_ingest_source",
            target_kind=input_model.target_kind,
            target_id=input_model.conflict_with or input_model.id or "",
            reason=input_model.reason,
            dry_run=False,
            details=ledger_row,
        )
        store.refresh_index()
    return IngestSourceOutput(
        scope=safe_output_text(input_model.scope),
        source_path=safe_output_text(ref.path),
        source_sha256=digest,
        source_bytes=len(raw),
        dry_run=input_model.dry_run,
        affected_paths=[safe_output_text(path) for path in affected_paths],
    )


def memorywiki_forget(input_model: ForgetInput) -> ForgetOutput:
    screen_tool_input("memorywiki_forget", input_model.model_dump())
    root = _root_for_scope(input_model, input_model.scope)
    if not input_model.dry_run:
        require_mcp_write_enabled(scope=input_model.scope)
    paths = _paths_for_scope(input_model, input_model.scope)
    target = _target_path_for_paths(paths, input_model.kind, input_model.identifier)
    relative = target.relative_to(paths.root).as_posix()
    store = (
        _store_if_exists(root, input_model.scope)
        if input_model.dry_run
        else _store_for_scope(input_model, input_model.scope)
    )
    if store is None:
        return ForgetOutput(
            scope=safe_output_text(input_model.scope),
            kind=safe_output_text(input_model.kind),
            identifier=safe_output_text(input_model.identifier),
            dry_run=input_model.dry_run,
            existed=False,
            deleted=False,
            affected_paths=[safe_output_text(relative)],
        )
    target = _target_path(store, input_model.kind, input_model.identifier)
    store._assert_safe_managed_path(target)
    existed = target.exists() and target.is_file()
    deleted = False
    if not input_model.dry_run:
        _assert_mcp_audit_ready(store)
        with store._file_lock():
            store._assert_mutable_managed_path(target)
            if target.exists():
                if not target.is_file():
                    raise ValueError(f"Forget target must be a file: {target}")
                target.unlink()
                store._mark_index_dirty_unlocked()
                deleted = True
        _append_mcp_audit(
            store,
            action="memorywiki_forget",
            target_kind=input_model.kind,
            target_id=input_model.identifier,
            reason=input_model.reason,
            dry_run=False,
            details={"path": relative, "existed": existed, "deleted": deleted},
        )
        store.refresh_index()
        if deleted:
            build_and_write_index(store, input_model.scope)
    return ForgetOutput(
        scope=safe_output_text(input_model.scope),
        kind=safe_output_text(input_model.kind),
        identifier=safe_output_text(input_model.identifier),
        dry_run=input_model.dry_run,
        existed=existed,
        deleted=deleted,
        affected_paths=[safe_output_text(relative)],
    )
