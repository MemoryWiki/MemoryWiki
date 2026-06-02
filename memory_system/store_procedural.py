"""Procedural memory read and write helpers for scoped stores."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from memory_system.models import ProceduralMemory


def write_procedural_memory(store: Any, item: ProceduralMemory) -> Path:
    path = cast(Path, store.paths.procedure_file(item.id))
    content = store._serialize_procedural_memory(item)
    with store._file_lock():
        store._atomic_write_text_unlocked(path, content)
        store._mark_index_dirty_unlocked()
    return path


def read_procedural_memory(store: Any, memory_id: str) -> ProceduralMemory | None:
    path = store.paths.procedure_file(memory_id)
    store._assert_safe_managed_path(path)
    if not path.exists():
        return None
    return cast(ProceduralMemory, store._parse_procedural_memory(
        store._sanitize(store._read_text_bounded(path)),
        fallback_id=memory_id,
    ))


def list_procedural_memories(store: Any, limit: int = 100) -> list[ProceduralMemory]:
    items = []
    for path in store._iter_safe_managed_files(
        store.paths.procedures_dir,
        "*.md",
        limit=store._safe_file_limit(limit, default=100),
    ):
        try:
            items.append(
                store._parse_procedural_memory(
                    store._sanitize(store._read_text_bounded(path)),
                    fallback_id=path.stem,
                )
            )
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
    return items


def delete_procedural_memory(store: Any, memory_id: str) -> bool:
    path = store.paths.procedure_file(memory_id)
    with store._file_lock():
        store._assert_mutable_managed_path(path)
        if not path.exists():
            return False
        path.unlink()
        store._mark_index_dirty_unlocked()
        return True
