from __future__ import annotations

from memory_system import store_documents
from tests.conftest import make_memory_store


def test_core_and_user_memory_documents_roundtrip(tmp_path):
    store = make_memory_store(tmp_path / "memory")

    assert store_documents.read_core_memory(store).startswith("# Core Memory")
    assert store_documents.read_user_memory(store).startswith("# User Memory")

    store_documents.write_core_memory(store, "# Core Memory\n\n- token sk-" + ("x" * 32))
    store_documents.write_user_memory(store, "# User Memory\n\n- prefers local")

    assert "[REDACTED_OPENAI_KEY]" in store_documents.read_core_memory(store)
    assert "prefers local" in store_documents.read_user_memory(store)


def test_index_refresh_clears_dirty_marker(tmp_path):
    store = make_memory_store(tmp_path / "memory")
    store_documents.write_core_memory(store, "# Core Memory\n\n- changed")

    assert store._index_is_dirty()
    index = store_documents.read_index(store)

    assert "Core Memory" in index
    assert not store._index_is_dirty()


def test_episodic_document_append_and_fallback(tmp_path):
    store = make_memory_store(tmp_path / "memory")

    assert store_documents.read_episodic(store, "2026-05-24").startswith(
        "# 2026-05-24 Episodic Memory"
    )

    path = store_documents.append_episodic(
        store, "2026-05-24", "## Session\n\n- Built documents module."
    )

    assert path == store.paths.episodic_for_date("2026-05-24")
    assert "Built documents module" in store_documents.read_episodic(
        store, "2026-05-24"
    )
