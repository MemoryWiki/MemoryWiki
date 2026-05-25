from __future__ import annotations

import pytest

from memory_system import store_semantic
from memory_system.models import SemanticMemory, SourceRef
from tests.conftest import make_memory_store


def _semantic(memory_id: str, updated_at: str) -> SemanticMemory:
    return SemanticMemory(
        id=memory_id,
        scope="project",
        title=memory_id,
        content="Stable fact.",
        concepts=["memory"],
        source_refs=[],
        confidence=0.8,
        strength=0.7,
        last_accessed=None,
        created_at="2026-05-24T09:00:00+08:00",
        updated_at=updated_at,
    )


def test_semantic_memory_roundtrips_lists_and_deletes(tmp_path):
    store = make_memory_store(tmp_path / "memory")
    old = _semantic("old", "2026-05-23T10:00:00+08:00")
    new = _semantic("new", "2026-05-24T10:00:00+08:00")

    store_semantic.write_semantic_memory(store, old)
    store_semantic.write_semantic_memory(store, new)

    assert store_semantic.read_semantic_memory(store, "new").title == "new"
    assert [item.id for item in store_semantic.list_semantic_memories(store)] == [
        "new",
        "old",
    ]
    assert store_semantic.delete_semantic_memory(store, "old")
    assert store_semantic.read_semantic_memory(store, "old") is None


def test_append_semantic_update_log_merges_sources_and_conflict(tmp_path):
    store = make_memory_store(tmp_path / "memory")
    item = _semantic("risk", "2026-05-24T10:00:00+08:00")
    item.source_refs = [SourceRef(kind="episode", path="episodes/a.md")]
    store_semantic.write_semantic_memory(store, item)

    store_semantic.append_semantic_update_log(
        store,
        "risk",
        "Revised assumption.",
        source_refs=[SourceRef(kind="source", path="sources/b.md")],
        conflict=True,
        now="2026-05-24T11:00:00+08:00",
    )

    loaded = store_semantic.read_semantic_memory(store, "risk")
    assert loaded.updated_at == "2026-05-24T11:00:00+08:00"
    assert loaded.update_log == [
        "2026-05-24T11:00:00+08:00 Conflict: Revised assumption. Sources: sources/b.md"
    ]
    assert [ref.path for ref in loaded.source_refs] == ["episodes/a.md", "sources/b.md"]


def test_append_semantic_update_log_rejects_missing_memory(tmp_path):
    store = make_memory_store(tmp_path / "memory")

    with pytest.raises(ValueError, match="Unknown semantic memory"):
        store_semantic.append_semantic_update_log(store, "missing", "note")
