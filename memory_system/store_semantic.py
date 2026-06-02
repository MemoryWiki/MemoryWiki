"""Semantic memory read, write, merge, and update-log helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

from memory_system.models import SemanticMemory, SourceRef


def write_semantic_memory(store: Any, item: SemanticMemory) -> Path:
    path = cast(Path, store.paths.semantic_file(item.id))
    content = store._serialize_semantic_memory(item)
    with store._file_lock():
        store._atomic_write_text_unlocked(path, content)
        store._mark_index_dirty_unlocked()
    return path


def read_semantic_memory(store: Any, memory_id: str) -> SemanticMemory | None:
    path = store.paths.semantic_file(memory_id)
    store._assert_safe_managed_path(path)
    if not path.exists():
        return None
    return cast(SemanticMemory, store._parse_semantic_memory(
        store._sanitize(store._read_text_bounded(path)),
        fallback_id=memory_id,
    ))


def list_semantic_memories(store: Any, limit: int = 100) -> list[SemanticMemory]:
    items = []
    for path in store._iter_safe_managed_files(
        store.paths.semantic_dir,
        "*.md",
        limit=store._safe_file_limit(limit, default=100),
    ):
        try:
            items.append(
                store._parse_semantic_memory(
                    store._sanitize(store._read_text_bounded(path)),
                    fallback_id=path.stem,
                )
            )
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
    return items


def append_semantic_update_log(
    store: Any,
    memory_id: str,
    note: str,
    source_refs: list[SourceRef] | None = None,
    conflict: bool = False,
    now: str | None = None,
) -> Path:
    item = store.read_semantic_memory(memory_id)
    if item is None:
        raise ValueError(f"Unknown semantic memory: {memory_id}")
    timestamp = now or datetime.now().astimezone().isoformat(timespec="seconds")
    prefix = "Conflict:" if conflict else "Update:"
    refs = source_refs or []
    source_suffix = ""
    if refs:
        source_suffix = " Sources: " + ", ".join(
            store._sanitize(ref.path)[:1000] for ref in refs[:10]
        )
    item.update_log.append(
        f"{timestamp} {prefix} {store._sanitize(note).strip()}{source_suffix}"
    )
    item.source_refs = store._merge_source_refs(item.source_refs, refs)
    item.updated_at = timestamp
    return cast(Path, store.write_semantic_memory(item))


def delete_semantic_memory(store: Any, memory_id: str) -> bool:
    path = store.paths.semantic_file(memory_id)
    with store._file_lock():
        store._assert_mutable_managed_path(path)
        if not path.exists():
            return False
        path.unlink()
        store._mark_index_dirty_unlocked()
        return True
