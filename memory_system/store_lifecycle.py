"""Lifecycle helper methods for index freshness and dirty markers."""

from __future__ import annotations

from typing import Any

from memory_system.sanitizer import sanitize_text
from memory_system.store_index import refresh_index_unlocked


def refresh_index_if_dirty_unlocked(store: Any, force: bool = False) -> None:
    if not force and store.paths.index.exists() and not store._index_is_dirty():
        return
    store._refresh_index_unlocked()


def sanitize(store: Any, text: str) -> str:
    if not store.sanitize_on_write:
        return text
    return sanitize_text(text)


def refresh_index(store: Any) -> None:
    refresh_index_unlocked(store)
