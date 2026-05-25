"""Document-layer read and write helpers mixed into the scoped store facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

CORE_MEMORY_TEMPLATE = """# Core Memory

## Identity And Mission

- Keep track of the user's long-term goals and current work.
"""


USER_MEMORY_TEMPLATE = """# User Memory

## Stable Facts

- No stable facts captured yet.
"""


INDEX_TEMPLATE = """# Memory Index

> Auto-generated navigation hub for this memory scope.
"""


def read_core_memory(store: Any) -> str:
    return store._sanitize(store._read_or_create(store.paths.core_memory, CORE_MEMORY_TEMPLATE))


def write_core_memory(store: Any, content: str) -> None:
    with store._file_lock():
        store._atomic_write_text_unlocked(
            store.paths.core_memory, store._sanitize(content).strip() + "\n"
        )
        store._mark_index_dirty_unlocked()


def read_user_memory(store: Any) -> str:
    return store._sanitize(store._read_or_create(store.paths.user_memory, USER_MEMORY_TEMPLATE))


def write_user_memory(store: Any, content: str) -> None:
    with store._file_lock():
        store._atomic_write_text_unlocked(
            store.paths.user_memory, store._sanitize(content).strip() + "\n"
        )
        store._mark_index_dirty_unlocked()


def read_index(store: Any) -> str:
    if not store.paths.index.exists() or store._index_is_dirty():
        store.refresh_index(force=False)
    return store._sanitize(store._read_or_create(store.paths.index, INDEX_TEMPLATE))


def refresh_index(store: Any, force: bool = True) -> None:
    with store._file_lock():
        store._refresh_index_if_dirty_unlocked(force=force)


def append_episodic(store: Any, date_text: str, section_markdown: str) -> Path:
    path = store.paths.episodic_for_date(date_text)
    with store._file_lock():
        if not path.exists():
            store._atomic_write_text_unlocked(path, f"# {date_text} Episodic Memory\n\n")
        store._append_text_unlocked(
            path, store._sanitize(section_markdown).strip() + "\n\n"
        )
        store._mark_index_dirty_unlocked()
    return path


def read_episodic(store: Any, date_text: str) -> str:
    path = store.paths.episodic_for_date(date_text)
    store._assert_safe_managed_path(path)
    if not path.exists():
        return f"# {date_text} Episodic Memory\n"
    return store._sanitize(store._read_text_bounded(path))
