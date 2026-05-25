"""Composable scoped-store facade that delegates behavior to focused modules."""

from __future__ import annotations

import sys
from pathlib import Path

from memory_system import (
    store_codec,
    store_documents,
    store_io,
    store_lifecycle,
    store_procedural,
    store_records,
    store_semantic,
    store_sessions,
)
from memory_system.models import (
    AuditEntry,
    ChatMessage,
    EpisodeFile,
    ProceduralMemory,
    SemanticMemory,
    SessionFile,
    SessionMeta,
    SessionSummary,
    SourceRef,
    TokenUsage,
)


def _managed_jsonl_rows() -> int:
    store_module = sys.modules.get("memory_system.store")
    return getattr(
        store_module,
        "MAX_MANAGED_JSONL_ROWS",
        store_io.MAX_MANAGED_JSONL_ROWS,
    )


class ScopedMemoryStoreFacade:
    def append_history(self, message: ChatMessage) -> None:
        store_records.append_history(self, message)

    def append_token_usage(self, usage: TokenUsage) -> None:
        store_records.append_token_usage(self, usage)

    def read_core_memory(self) -> str:
        return store_documents.read_core_memory(self)

    def write_core_memory(self, content: str) -> None:
        store_documents.write_core_memory(self, content)

    def read_user_memory(self) -> str:
        return store_documents.read_user_memory(self)

    def write_user_memory(self, content: str) -> None:
        store_documents.write_user_memory(self, content)

    def read_index(self) -> str:
        return store_documents.read_index(self)

    def refresh_index(self, force: bool = True) -> None:
        store_documents.refresh_index(self, force=force)

    def append_episodic(self, date_text: str, section_markdown: str) -> Path:
        return store_documents.append_episodic(self, date_text, section_markdown)

    def read_episodic(self, date_text: str) -> str:
        return store_documents.read_episodic(self, date_text)

    def write_session(self, session: SessionFile) -> Path:
        return store_sessions.write_session(self, session)

    def read_session(self, session_id: str) -> SessionFile | None:
        return store_sessions.read_session(self, session_id)

    def list_sessions(self, limit: int = 30) -> list[SessionMeta]:
        return store_sessions.list_sessions(self, limit=limit)

    def append_to_episode(
        self,
        date_text: str,
        section_title: str,
        body: str,
        session_meta: SessionMeta | None = None,
    ) -> Path:
        return store_sessions.append_to_episode(
            self,
            date_text,
            section_title,
            body,
            session_meta=session_meta,
        )

    def read_episode(self, date_text: str) -> EpisodeFile | None:
        return store_sessions.read_episode(self, date_text)

    def list_episodes(self, since: str | int | None = None) -> list[str]:
        return store_sessions.list_episodes(self, since=since)

    def write_semantic_memory(self, item: SemanticMemory) -> Path:
        return store_semantic.write_semantic_memory(self, item)

    def read_semantic_memory(self, memory_id: str) -> SemanticMemory | None:
        return store_semantic.read_semantic_memory(self, memory_id)

    def list_semantic_memories(self, limit: int = 100) -> list[SemanticMemory]:
        return store_semantic.list_semantic_memories(self, limit=limit)

    def append_semantic_update_log(
        self,
        memory_id: str,
        note: str,
        source_refs: list[SourceRef] | None = None,
        conflict: bool = False,
        now: str | None = None,
    ) -> Path:
        return store_semantic.append_semantic_update_log(
            self,
            memory_id,
            note,
            source_refs=source_refs,
            conflict=conflict,
            now=now,
        )

    def write_procedural_memory(self, item: ProceduralMemory) -> Path:
        return store_procedural.write_procedural_memory(self, item)

    def read_procedural_memory(self, memory_id: str) -> ProceduralMemory | None:
        return store_procedural.read_procedural_memory(self, memory_id)

    def list_procedural_memories(self, limit: int = 100) -> list[ProceduralMemory]:
        return store_procedural.list_procedural_memories(self, limit=limit)

    def delete_semantic_memory(self, memory_id: str) -> bool:
        return store_semantic.delete_semantic_memory(self, memory_id)

    def delete_procedural_memory(self, memory_id: str) -> bool:
        return store_procedural.delete_procedural_memory(self, memory_id)

    def append_audit(self, entry: AuditEntry) -> None:
        store_records.append_audit(self, entry)

    def append_source_ingest(self, row: dict) -> None:
        store_records.append_source_ingest(self, row)

    def list_source_documents(self, limit: int = 100) -> list[Path]:
        return store_records.list_source_documents(self, limit=limit)

    def read_audit(self, limit: int = 100) -> list[AuditEntry]:
        return store_records.read_audit(self, limit=limit)

    def append_session_summary(self, summary: SessionSummary) -> None:
        store_records.append_session_summary(self, summary)

    def read_session_summaries(self, limit: int = 10) -> list[SessionSummary]:
        return store_records.read_session_summaries(self, limit=limit)

    def _serialize_session_file(self, session: SessionFile) -> str:
        return store_codec.serialize_session_file(self, session)

    def _parse_session_file(self, text: str) -> SessionFile:
        return store_codec.parse_session_file(self, text)

    def _serialize_episode_file(self, episode: EpisodeFile) -> str:
        return store_codec.serialize_episode_file(self, episode)

    def _parse_episode_file(
        self, text: str, fallback_date: str | None = None
    ) -> EpisodeFile:
        return store_codec.parse_episode_file(self, text, fallback_date=fallback_date)

    def _serialize_semantic_memory(self, item: SemanticMemory) -> str:
        return store_codec.serialize_semantic_memory(self, item)

    def _parse_semantic_memory(
        self, text: str, fallback_id: str | None = None
    ) -> SemanticMemory:
        return store_codec.parse_semantic_memory(self, text, fallback_id=fallback_id)

    def _split_update_log(self, body: str) -> tuple[str, list[str]]:
        return store_codec.split_update_log(body)

    def _serialize_procedural_memory(self, item: ProceduralMemory) -> str:
        return store_codec.serialize_procedural_memory(self, item)

    def _parse_procedural_memory(
        self, text: str, fallback_id: str | None = None
    ) -> ProceduralMemory:
        return store_codec.parse_procedural_memory(self, text, fallback_id=fallback_id)

    def _source_refs_json(self, refs: list[SourceRef]) -> str:
        return store_codec.source_refs_json(self, refs)

    def _parse_source_refs(self, value) -> list[SourceRef]:
        return store_codec.parse_source_refs(self, value)

    def _merge_source_refs(
        self, existing: list[SourceRef], incoming: list[SourceRef]
    ) -> list[SourceRef]:
        return store_codec.merge_source_refs(existing, incoming)

    def _optional_sanitized_text(self, value) -> str | None:
        return store_codec.optional_sanitized_text(self, value)

    def _safe_float(self, value, default: float = 0.0) -> float:
        return store_codec.safe_float(value, default=default)

    def _sanitize_json(self, value):
        return store_codec.sanitize_json(self, value)

    def _frontmatter_scalar(self, value: str | int | None) -> str:
        return store_codec.frontmatter_scalar(self, value)

    def _frontmatter_string_list(self, key: str, items: list[str]) -> list[str]:
        return store_codec.frontmatter_string_list(self, key, items)

    def _split_frontmatter(self, text: str) -> tuple[dict, str]:
        return store_codec.split_frontmatter(self, text)

    def _parse_frontmatter_lines(self, lines: list[str]) -> dict:
        return store_codec.parse_frontmatter_lines(self, lines)

    def _parse_frontmatter_scalar(self, value):
        return store_codec.parse_frontmatter_scalar(value)

    def _episode_heading(self, section_title: str) -> str:
        return store_codec.episode_heading(self, section_title)

    def _safe_string_list(self, value) -> list[str]:
        return store_codec.safe_string_list(value)

    def _read_or_create(self, path: Path, template: str) -> str:
        return store_io.read_or_create(self, path, template)

    def _append_jsonl(self, path: Path, row: dict) -> None:
        store_io.append_jsonl(self, path, row)

    def _atomic_write_text(self, path: Path, content: str) -> None:
        store_io.atomic_write_text(self, path, content)

    def _atomic_write_text_unlocked(self, path: Path, content: str) -> None:
        store_io.atomic_write_text_unlocked(self, path, content)

    def _append_text(self, path: Path, content: str) -> None:
        store_io.append_text(self, path, content)

    def _append_text_unlocked(self, path: Path, content: str) -> None:
        store_io.append_text_unlocked(self, path, content)

    def _index_is_dirty(self) -> bool:
        return store_io.index_is_dirty(self)

    def _mark_index_dirty_unlocked(self) -> None:
        store_io.mark_index_dirty_unlocked(self)

    def _clear_index_dirty_unlocked(self) -> None:
        store_io.clear_index_dirty_unlocked(self)

    def _refresh_index_if_dirty_unlocked(self, force: bool = False) -> None:
        store_lifecycle.refresh_index_if_dirty_unlocked(self, force=force)

    def _sanitize(self, text: str) -> str:
        return store_lifecycle.sanitize(self, text)

    def _file_lock(self):
        return store_io.file_lock(self)

    def _refresh_index_unlocked(self) -> None:
        store_lifecycle.refresh_index(self)

    def _file_char_count(self, path: Path) -> int:
        return store_io.file_char_count(self, path)

    def _count_nonempty_lines(self, path: Path) -> int:
        return store_io.count_nonempty_lines(self, path)

    def _preview_text(self, path: Path) -> str:
        return store_io.preview_text(self, path)

    def _iter_safe_managed_files(
        self, directory: Path, pattern: str, limit: int = store_io.MAX_MANAGED_FILES
    ) -> list[Path]:
        return store_io.iter_safe_managed_files(self, directory, pattern, limit=limit)

    def _safe_file_limit(self, limit, default: int) -> int:
        return store_io.safe_file_limit(limit, default=default)

    def _ensure_root(self) -> None:
        store_io.ensure_root(self)

    def _secure_path(self, path: Path) -> None:
        store_io.secure_path(self, path)

    def _assert_safe_managed_path(self, path: Path) -> None:
        store_io.assert_safe_managed_path(self, path)

    def _assert_mutable_managed_path(self, path: Path) -> None:
        store_io.assert_mutable_managed_path(self, path)

    def _is_safe_readable_file(self, path: Path) -> bool:
        return store_io.is_safe_readable_file(self, path)

    def _read_text_bounded(self, path: Path) -> str:
        return store_io.read_text_bounded(self, path)

    def _read_lines_bounded(self, path: Path) -> list[str]:
        return store_io.read_lines_bounded(self, path, max_rows=_managed_jsonl_rows())
