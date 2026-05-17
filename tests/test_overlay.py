from memory_system.overlay import OverlayMemoryStore
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore


def test_overlay_merges_global_then_project_memory(tmp_path):
    global_store = ScopedMemoryStore(
        MemoryScopePaths.from_root(tmp_path / "global", scope="global"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    project_store = ScopedMemoryStore(
        MemoryScopePaths.from_root(tmp_path / "project", scope="project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    global_store.write_core_memory("# Core Memory\n\n- global fact")
    project_store.write_core_memory("# Core Memory\n\n- project fact")
    overlay = OverlayMemoryStore(global_store=global_store, project_store=project_store)
    merged = overlay.read_merged_core_memory()
    assert merged.index("global fact") < merged.index("project fact")


def test_overlay_reuses_memory_context_until_files_change(tmp_path):
    global_store = ScopedMemoryStore(
        MemoryScopePaths.from_root(tmp_path / "global", scope="global"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    project_store = ScopedMemoryStore(
        MemoryScopePaths.from_root(tmp_path / "project", scope="project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    global_store.write_core_memory("# Core Memory\n\n- global fact")
    project_store.write_core_memory("# Core Memory\n\n- project fact")
    overlay = OverlayMemoryStore(global_store=global_store, project_store=project_store)
    calls = {"global": 0, "project": 0}
    original_global = global_store.read_core_memory
    original_project = project_store.read_core_memory

    def counted_global():
        calls["global"] += 1
        return original_global()

    def counted_project():
        calls["project"] += 1
        return original_project()

    global_store.read_core_memory = counted_global
    project_store.read_core_memory = counted_project

    assert "global fact" in overlay.read_merged_core_memory()
    assert "project fact" in overlay.read_merged_core_memory()
    assert calls == {"global": 1, "project": 1}


def test_overlay_prefers_canonical_user_memory_when_present(tmp_path):
    canonical_user = tmp_path / "cowork" / "memory" / "USER.md"
    canonical_user.parent.mkdir(parents=True)
    canonical_user.write_text(
        "# User Memory\n\n- Canonical preference token sk-%s\n" % ("x" * 32),
        encoding="utf-8",
    )
    global_store = ScopedMemoryStore(
        MemoryScopePaths.from_root(tmp_path / "global", scope="global"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    project_store = ScopedMemoryStore(
        MemoryScopePaths.from_root(tmp_path / "project", scope="project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    global_store.write_user_memory("# User Memory\n\n- Global fallback preference")
    project_store.write_user_memory("# User Memory\n\n- Project override preference")
    overlay = OverlayMemoryStore(
        global_store=global_store,
        project_store=project_store,
        canonical_user_path=canonical_user,
    )

    merged = overlay.read_merged_user_memory()

    assert "Canonical preference" in merged
    assert "[REDACTED_OPENAI_KEY]" in merged
    assert "Project override preference" in merged
    assert "Global fallback preference" not in merged


def test_overlay_skips_symlinked_canonical_user_memory(tmp_path):
    outside_user = tmp_path / "outside-user.md"
    outside_user.write_text("# User Memory\n\n- Unsafe symlink preference\n", encoding="utf-8")
    canonical_user = tmp_path / "cowork" / "memory" / "USER.md"
    canonical_user.parent.mkdir(parents=True)
    canonical_user.symlink_to(outside_user)
    global_store = ScopedMemoryStore(
        MemoryScopePaths.from_root(tmp_path / "global", scope="global"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    project_store = ScopedMemoryStore(
        MemoryScopePaths.from_root(tmp_path / "project", scope="project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    global_store.write_user_memory("# User Memory\n\n- Global fallback preference")
    overlay = OverlayMemoryStore(
        global_store=global_store,
        project_store=project_store,
        canonical_user_path=canonical_user,
    )

    merged = overlay.read_merged_user_memory()

    assert "Global fallback preference" in merged
    assert "Unsafe symlink preference" not in merged
