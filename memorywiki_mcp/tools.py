from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import sys


MEMORYWIKI_ROOT = Path(__file__).resolve().parents[1]
if str(MEMORYWIKI_ROOT) not in sys.path:
    sys.path.insert(0, str(MEMORYWIKI_ROOT))

from memory_index_maintain import maintain_indexes
from memory_recall import recall as recall_memory
from memory_system.models import (
    AuditEntry,
    EpisodeFile,
    ProceduralMemory,
    SemanticMemory,
    SessionFile,
    SourceRef,
)
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore
from session_summary import save_summary
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
    ForgetInput,
    ForgetOutput,
    IndexMaintainInput,
    IndexMaintainOutput,
    IndexRootStatus,
    IngestSourceInput,
    IngestSourceOutput,
    ReadMemoryInput,
    ReadMemoryOutput,
    RecallHitOutput,
    RecallInput,
    RecallOutput,
    WriteSessionInput,
    WriteSessionOutput,
)


MAX_SOURCE_BYTES = 2_000_000


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _store_if_exists(root: Path, scope: str) -> ScopedMemoryStore | None:
    root = root.expanduser()
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Memory root must be a real directory: %s" % root)
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
        raise ValueError("Memory root must be a real directory: %s" % root)
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
        raise ValueError("MCP audit log must be a regular file: %s" % store.paths.audit_log)


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
    raise ValueError("Unsupported memory kind: %s" % kind)


def _frontmatter_for_semantic(item: SemanticMemory) -> dict[str, Any]:
    return safe_json(
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
            "source_refs": [asdict(ref) for ref in item.source_refs],
        }
    )


def _frontmatter_for_procedure(item: ProceduralMemory) -> dict[str, Any]:
    return safe_json(
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
            "source_refs": [asdict(ref) for ref in item.source_refs],
        }
    )


def _frontmatter_for_session(item: SessionFile) -> dict[str, Any]:
    frontmatter = asdict(item)
    frontmatter.pop("body", None)
    return safe_json(frontmatter)


def _frontmatter_for_episode(item: EpisodeFile) -> dict[str, Any]:
    return safe_json(
        {
            "date": item.date,
            "scope": item.scope,
            "sessions": [asdict(session) for session in item.sessions],
        }
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
        item = store.read_semantic_memory(identifier)
        if item is None:
            return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=identifier)
        content = item.content
        frontmatter = _frontmatter_for_semantic(item)
        update_log = [safe_output_text(entry) for entry in item.update_log]
        found_identifier = item.id
    elif kind == "procedural":
        if not identifier:
            raise ValueError("identifier is required for procedural memory")
        item = store.read_procedural_memory(identifier)
        if item is None:
            return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=identifier)
        content = "\n".join([item.trigger] + item.steps)
        frontmatter = _frontmatter_for_procedure(item)
        found_identifier = item.id
    elif kind == "session":
        if not identifier:
            raise ValueError("identifier is required for session memory")
        item = store.read_session(identifier)
        if item is None:
            return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=identifier)
        content = item.body
        frontmatter = _frontmatter_for_session(item)
        found_identifier = item.id
    elif kind == "episode":
        if not identifier:
            raise ValueError("identifier is required for episode memory")
        item = store.read_episode(identifier)
        if item is None:
            return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=identifier)
        content = item.body
        frontmatter = _frontmatter_for_episode(item)
        found_identifier = item.date
    elif kind in {"core", "user", "index", "project_profile"}:
        hot = _read_hot_file(store, kind)
        if hot is None:
            return ReadMemoryOutput(found=False, scope=scope, kind=kind, identifier=kind)
        content, frontmatter, found_identifier = hot
        frontmatter = safe_json(frontmatter)
    else:
        raise ValueError("Unsupported memory kind: %s" % kind)

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
        strategy=input_model.strategy,
        refresh_index_if_needed=input_model.refresh_index_if_needed,
    )
    result = recall_memory(args)
    hits = []
    for hit in result.hits:
        explanation = safe_json(hit.score_explanation) if input_model.explain_score else {}
        hits.append(
            RecallHitOutput(
                scope=safe_output_text(hit.scope),
                source=safe_output_text(hit.source),
                identifier=safe_output_text(hit.identifier),
                title=safe_output_text(hit.title),
                excerpt=safe_output_text(hit.excerpt),
                score=round(hit.score, 4),
                tokens=hit.tokens,
                provenance=safe_json([asdict(ref) for ref in hit.provenance]),
                score_explanation=explanation,
            )
        )
    return RecallOutput(
        query=input_model.query,
        strategy=result.strategy,
        tokens_used=result.tokens_used,
        truncated=result.truncated,
        warnings=[safe_output_text(warning) for warning in result.warnings],
        hits=hits,
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
        "sessions/%s.md" % session.session_id,
    ]
    if input_model.write_episode:
        affected.append("episodes/%s.md" % session.ts[:10])
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
        scope=input_model.scope,
        session_id=session.session_id,
        dry_run=False,
        affected_paths=affected,
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
        "semantic/%s.md" % input_model.id
        if input_model.kind == "semantic"
        else "procedures/%s.md" % input_model.id
    )
    replaced = False

    if input_model.kind == "semantic":
        existing = store.read_semantic_memory(input_model.id) if store is not None else None
        replaced = existing is not None
        if existing is not None and not input_model.replace:
            raise ValueError("semantic memory already exists; set replace=true: %s" % input_model.id)
        item = SemanticMemory(
            id=input_model.id,
            scope=input_model.scope,
            title=input_model.title,
            content=input_model.content,
            concepts=input_model.concepts,
            source_refs=refs
            if existing is None
            else store._merge_source_refs(existing.source_refs, refs),
            confidence=input_model.confidence,
            strength=input_model.strength,
            last_accessed=None,
            created_at=existing.created_at if existing else timestamp,
            updated_at=timestamp,
            update_log=(
                list(existing.update_log)
                + ["%s Update: Replaced from MCP crystallize." % timestamp]
                if existing
                else []
            ),
        )
        if not input_model.dry_run:
            assert store is not None
            _assert_mcp_audit_ready(store)
            store.write_semantic_memory(item)
    else:
        existing = store.read_procedural_memory(input_model.id) if store is not None else None
        replaced = existing is not None
        if existing is not None and not input_model.replace:
            raise ValueError("procedure already exists; set replace=true: %s" % input_model.id)
        steps = input_model.steps or [
            line.strip("- ").strip()
            for line in input_model.content.splitlines()
            if line.strip()
        ]
        item = ProceduralMemory(
            id=input_model.id,
            scope=input_model.scope,
            title=input_model.title,
            trigger=input_model.trigger or input_model.content[:240],
            steps=steps,
            source_refs=refs
            if existing is None
            else store._merge_source_refs(existing.source_refs, refs),
            confidence=input_model.confidence,
            strength=input_model.strength,
            last_accessed=None,
            created_at=existing.created_at if existing else timestamp,
            updated_at=timestamp,
        )
        if not input_model.dry_run:
            assert store is not None
            _assert_mcp_audit_ready(store)
            store.write_procedural_memory(item)

    if not input_model.dry_run:
        assert store is not None
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
        scope=input_model.scope,
        kind=input_model.kind,
        id=input_model.id,
        dry_run=input_model.dry_run,
        affected_paths=[affected_path],
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
            raise ValueError("Source path may not include symlinks: %s" % item)
        try:
            item.resolve(strict=False).relative_to(root_resolved)
        except ValueError:
            raise ValueError("Source must stay below sources/: %s" % path)


def _resolve_source(store: ScopedMemoryStore, source: str) -> Path:
    sources_dir = store.paths.sources_dir
    if not sources_dir.exists() or sources_dir.is_symlink() or not sources_dir.is_dir():
        raise ValueError("sources/ must be a real directory: %s" % sources_dir)
    candidate = Path(source).expanduser()
    if not candidate.is_absolute():
        candidate = sources_dir / candidate
    _assert_no_symlink_components(candidate, sources_dir)
    try:
        resolved_source = candidate.resolve(strict=True)
        resolved_source.relative_to(sources_dir.resolve(strict=True))
    except (OSError, ValueError):
        raise ValueError("Source must stay below sources/: %s" % source)
    if not resolved_source.is_file():
        raise ValueError("Source document must be a file: %s" % candidate)
    if resolved_source.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Source document is too large: %s" % candidate)
    return resolved_source


def _read_source(path: Path) -> tuple[bytes, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        if path.is_symlink():
            raise ValueError("Source document may not be a symlink: %s" % path)
        raise
    try:
        size = os.fstat(fd).st_size
        if size > MAX_SOURCE_BYTES:
            raise ValueError("Source document is too large: %s" % path)
        raw = os.read(fd, size)
    finally:
        os.close(fd)
    return raw, safe_output_text(raw.decode("utf-8", errors="replace"))


def _source_ref(store: ScopedMemoryStore, path: Path, digest: str, text: str) -> SourceRef:
    return SourceRef(
        kind="source",
        path="sources/%s" % path.relative_to(store.paths.sources_dir.resolve()).as_posix(),
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
        raise ValueError("Memory root does not exist: %s" % root)
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
            raise ValueError("Unknown semantic memory: %s" % input_model.conflict_with)
        affected_paths.append("semantic/%s.md" % input_model.conflict_with)
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
            update_log.append("%s Update: Refreshed from %s" % (timestamp, ref.path))
        item = SemanticMemory(
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
        affected_paths.append("semantic/%s.md" % input_model.id)
        if not input_model.dry_run:
            store.write_semantic_memory(item)
    else:
        if not input_model.id or not input_model.title:
            raise ValueError("id and title are required for procedure source ingest")
        item = ProceduralMemory(
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
        affected_paths.append("procedures/%s.md" % input_model.id)
        if not input_model.dry_run:
            store.write_procedural_memory(item)

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
        scope=input_model.scope,
        source_path=ref.path,
        source_sha256=digest,
        source_bytes=len(raw),
        dry_run=input_model.dry_run,
        affected_paths=affected_paths,
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
            scope=input_model.scope,
            kind=input_model.kind,
            identifier=input_model.identifier,
            dry_run=input_model.dry_run,
            existed=False,
            deleted=False,
            affected_paths=[relative],
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
                    raise ValueError("Forget target must be a file: %s" % target)
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
    return ForgetOutput(
        scope=input_model.scope,
        kind=input_model.kind,
        identifier=input_model.identifier,
        dry_run=input_model.dry_run,
        existed=existed,
        deleted=deleted,
        affected_paths=[relative],
    )
