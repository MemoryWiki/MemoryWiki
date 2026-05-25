from __future__ import annotations

from memory_system import store_procedural
from memory_system.models import ProceduralMemory
from tests.conftest import make_memory_store


def _procedure(memory_id: str, updated_at: str) -> ProceduralMemory:
    return ProceduralMemory(
        id=memory_id,
        scope="project",
        title=memory_id,
        trigger="When asked.",
        steps=["Do one thing."],
        source_refs=[],
        confidence=0.8,
        strength=0.7,
        last_accessed=None,
        created_at="2026-05-24T09:00:00+08:00",
        updated_at=updated_at,
    )


def test_procedural_memory_roundtrips_lists_and_deletes(tmp_path):
    store = make_memory_store(tmp_path / "memory")
    old = _procedure("old", "2026-05-23T10:00:00+08:00")
    new = _procedure("new", "2026-05-24T10:00:00+08:00")

    store_procedural.write_procedural_memory(store, old)
    store_procedural.write_procedural_memory(store, new)

    assert store_procedural.read_procedural_memory(store, "new").title == "new"
    assert [item.id for item in store_procedural.list_procedural_memories(store)] == [
        "new",
        "old",
    ]
    assert store_procedural.delete_procedural_memory(store, "old")
    assert store_procedural.read_procedural_memory(store, "old") is None
