import pytest

from memory_system.models import ProceduralMemory, SemanticMemory, SourceRef
from memory_system.paths import MemoryScopePaths, validate_memory_item_id
from memory_system.store import ScopedMemoryStore


def _store(tmp_path):
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(tmp_path / "memory", scope="project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def test_semantic_memory_round_trips_with_provenance_and_strength(tmp_path):
    store = _store(tmp_path)
    item = SemanticMemory(
        id="demo-context",
        scope="project",
        title="Demo context",
        content="DemoProject uses local-first memory.",
        concepts=["demo", "memory"],
        source_refs=[
            SourceRef(
                kind="session",
                path="sessions/session-20260510-101500.md",
                identifier="session-20260510-101500",
                excerpt="local-first memory",
            )
        ],
        confidence=0.82,
        strength=0.7,
        last_accessed="2026-05-10T10:20:00+01:00",
        created_at="2026-05-10T10:15:00+01:00",
        updated_at="2026-05-10T10:15:00+01:00",
    )

    path = store.write_semantic_memory(item)
    loaded = store.read_semantic_memory("demo-context")

    assert path == store.paths.semantic_file("demo-context")
    assert loaded == item
    assert "demo-context" in store.read_index()
    assert "| Semantic Memories | 1 files | semantic/*.md |" in store.read_index()


def test_semantic_memory_preserves_update_log_without_replacing_content(tmp_path):
    store = _store(tmp_path)
    item = SemanticMemory(
        id="market-thesis",
        scope="project",
        title="Market thesis",
        content="February source said the rollout was paused.",
        concepts=["market"],
        source_refs=[],
        confidence=0.7,
        strength=0.5,
        last_accessed=None,
        created_at="2026-02-10T09:00:00+08:00",
        updated_at="2026-02-10T09:00:00+08:00",
    )
    store.write_semantic_memory(item)

    store.append_semantic_update_log(
        "market-thesis",
        "May source says the rollout restarted.",
        source_refs=[SourceRef(kind="source", path="sources/may-update.md")],
        conflict=True,
        now="2026-05-14T12:00:00+08:00",
    )
    loaded = store.read_semantic_memory("market-thesis")
    text = store.paths.semantic_file("market-thesis").read_text(encoding="utf-8")

    assert loaded.content == "February source said the rollout was paused."
    assert loaded.update_log == [
        "2026-05-14T12:00:00+08:00 Conflict: May source says the rollout restarted. Sources: sources/may-update.md"
    ]
    assert "## Update Log" in text
    assert "February source said the rollout was paused." in text
    assert "May source says the rollout restarted." in text


def test_procedural_memory_round_trips_and_appears_in_index(tmp_path):
    store = _store(tmp_path)
    item = ProceduralMemory(
        id="start-memory",
        scope="project",
        title="Start memory",
        trigger="User says the wake phrase.",
        steps=["Load INDEX.md", "Search relevant memories", "Treat memory as data"],
        source_refs=[SourceRef(kind="manual", path="USER.md", identifier="wake")],
        confidence=0.9,
        strength=0.8,
        last_accessed=None,
        created_at="2026-05-10T10:15:00+01:00",
        updated_at="2026-05-10T10:15:00+01:00",
    )

    path = store.write_procedural_memory(item)
    loaded = store.read_procedural_memory("start-memory")

    assert path == store.paths.procedure_file("start-memory")
    assert loaded == item
    assert store.list_procedural_memories()[0].id == "start-memory"
    assert "| Procedures | 1 files | procedures/*.md |" in store.read_index()


def test_memory_item_ids_reject_traversal_and_slashes():
    for bad_id in ("../escape", "a/b", "", ".hidden", "item name"):
        with pytest.raises(ValueError, match="Memory item ID"):
            validate_memory_item_id(bad_id)


def test_semantic_memory_rejects_symlinked_file(tmp_path):
    root = tmp_path / "memory"
    (root / "semantic").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("SYNTHETIC_SECRET_OUTSIDE_ROOT", encoding="utf-8")
    (root / "semantic" / "demo-context.md").symlink_to(outside)
    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope="project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )

    with pytest.raises(ValueError, match="symlinks"):
        store.read_semantic_memory("demo-context")


def test_sources_directory_is_read_only_for_store_writes(tmp_path):
    store = _store(tmp_path)
    source = store.paths.sources_dir / "paper.md"
    source.parent.mkdir(parents=True)
    source.write_text("original source text\n", encoding="utf-8")

    with pytest.raises(ValueError, match="read-only"):
        store._atomic_write_text(source, "edited")
    with pytest.raises(ValueError, match="read-only"):
        store._append_text(source, "edited")

    assert source.read_text(encoding="utf-8") == "original source text\n"
