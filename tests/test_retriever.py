import json

import pytest

from memory_system.models import ChatMessage
from memory_system.overlay import OverlayMemoryStore
from memory_system.paths import MemoryScopePaths
from memory_system.retriever import MemoryRetriever
from memory_system.store import (
    MAX_MANAGED_JSONL_ROWS,
    MAX_MANAGED_READ_BYTES,
    ScopedMemoryStore,
)


def test_get_day_returns_daily_markdown(tmp_path):
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
    project_store.append_episodic(
        "2026-04-23", "## 10:15 Compression Snapshot\n\n- Topic: memory design"
    )
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )
    result = retriever.get_day("2026-04-23")
    assert result.identifier == "2026-04-23"
    assert result.scope == "project"
    assert "memory design" in result.excerpt
    assert result.deprecated is True
    assert "legacy" in result.note.lower()


def test_get_day_prefers_v2_episode_when_available(tmp_path):
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
    project_store.append_episodic(
        "2026-05-08", "## 09:00 Legacy\n\n- legacy context"
    )
    project_store.append_to_episode(
        "2026-05-08", "10:00 V2", "- v2 episode context"
    )
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )

    result = retriever.get_day("2026-05-08")

    assert result.identifier == "2026-05-08"
    assert result.deprecated is False
    assert "v2 episode context" in result.excerpt
    assert "legacy context" not in result.excerpt


def test_search_all_returns_scope_labels(tmp_path):
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
    global_store.write_user_memory("# User Memory\n\n- Prefers local mode.")
    project_store.append_episodic("2026-04-23", "## Snapshot\n\n- Topic: local mode")
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )
    result = retriever.search(keyword="local mode", source="all")
    scopes = {hit.scope for hit in result.hits}
    assert scopes == {"global", "project"}


def test_search_can_limit_scope_to_global_only(tmp_path):
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
    global_store.write_user_memory("# User Memory\n\n- Prefers concise replies.")
    project_store.write_user_memory("# User Memory\n\n- Prefers verbose replies.")
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )
    result = retriever.search(keyword="prefers", source="memory", scope="global")
    assert {hit.scope for hit in result.hits} == {"global"}


def test_search_history_returns_matching_rows(tmp_path):
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
    project_store.append_history(
        ChatMessage(
            ts="2026-04-23T10:00:00+01:00",
            role="user",
            content="remember my timezone",
        )
    )
    project_store.append_history(
        ChatMessage(
            ts="2026-04-23T10:00:01+01:00",
            role="assistant",
            content="I will remember it",
        )
    )
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )
    result = retriever.search(keyword="timezone", source="history")
    assert result.hits[0].scope == "project"
    assert result.hits[0].source == "history"
    assert "timezone" in result.hits[0].excerpt


def test_search_history_skips_corrupt_jsonl_rows(tmp_path):
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
    project_store.paths.history.write_text(
        "{broken-json\n"
        + json.dumps(
            {
                "ts": "2026-04-23T10:00:00+01:00",
                "role": "user",
                "content": "timezone survives corrupt history",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )

    result = retriever.search(keyword="timezone", source="history")

    assert len(result.hits) == 1
    assert result.hits[0].identifier == "history:2"


def test_search_history_sanitizes_manually_edited_rows(tmp_path):
    fake_key = "sk-proj-" + "abc1234567890abcdef1234567890abcdef"
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
    project_store.paths.root.mkdir(parents=True, exist_ok=True)
    project_store.paths.history.write_text(
        json.dumps(
            {
                "ts": "2026-05-08T10:00:00+01:00",
                "role": "user",
                "content": "timezone key=%s" % fake_key,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )

    result = retriever.search(keyword="timezone", source="history")

    assert fake_key not in result.hits[0].excerpt
    assert "[REDACTED_OPENAI_KEY]" in result.hits[0].excerpt


def test_search_history_skips_oversized_history_file(tmp_path):
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
    project_store.paths.root.mkdir(parents=True, exist_ok=True)
    project_store.paths.history.write_text(
        "needle" + ("x" * MAX_MANAGED_READ_BYTES),
        encoding="utf-8",
    )
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )

    result = retriever.search(keyword="needle", source="history")

    assert result.hits == []


def test_search_history_uses_bounded_jsonl_reader(tmp_path):
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
    project_store.paths.root.mkdir(parents=True, exist_ok=True)
    rows = [
        json.dumps(
            {
                "ts": "2026-05-08T10:00:%02d+01:00" % (index % 60),
                "role": "user",
                "content": "ordinary bounded row",
            }
        )
        for index in range(MAX_MANAGED_JSONL_ROWS)
    ]
    rows.append(
        json.dumps(
            {
                "ts": "2026-05-08T10:59:59+01:00",
                "role": "user",
                "content": "POST_CAP_HISTORY_MARKER",
            }
        )
    )
    project_store.paths.history.write_text("\n".join(rows) + "\n", encoding="utf-8")
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )

    with pytest.warns(RuntimeWarning, match="safe row limit"):
        result = retriever.search(keyword="POST_CAP_HISTORY_MARKER", source="history")

    assert result.hits == []


def test_search_episodic_returns_matching_files(tmp_path):
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
    project_store.append_episodic(
        "2026-04-23", "## 10:15 Compression Snapshot\n\n- Decisions: Use OpenAI"
    )
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )
    result = retriever.search(keyword="OpenAI", source="episodic")
    assert result.hits[0].identifier == "2026-04-23"
    assert result.hits[0].scope == "project"
    assert result.hits[0].source == "episodic"
    assert result.hits[0].deprecated is True
    assert "legacy" in result.hits[0].note.lower()


def test_search_episodic_returns_v2_episode_files(tmp_path):
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
    project_store.append_to_episode(
        "2026-05-08", "10:00 V2", "- Decisions: v2 retrieval needle"
    )
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )

    result = retriever.search(keyword="v2 retrieval needle", source="episodic")

    assert len(result.hits) == 1
    assert result.hits[0].identifier == "2026-05-08"
    assert result.hits[0].scope == "project"
    assert "v2 retrieval needle" in result.hits[0].excerpt


def test_search_episodic_skips_legacy_when_v2_same_date_exists(tmp_path):
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
    project_store.append_episodic(
        "2026-05-08", "## Legacy\n\n- shared duplicate needle"
    )
    project_store.append_to_episode(
        "2026-05-08", "10:00 V2", "- shared duplicate needle"
    )
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )

    result = retriever.search(keyword="shared duplicate needle", source="episodic")

    assert len(result.hits) == 1
    assert result.hits[0].identifier == "2026-05-08"
    assert result.hits[0].deprecated is False
    assert "Legacy" not in result.hits[0].excerpt


def test_search_episodic_excerpt_centers_match(tmp_path):
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
    project_store.append_episodic("2026-04-23", ("prefix " * 120) + "needle context")
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )

    result = retriever.search(keyword="needle", source="episodic")

    assert "needle context" in result.hits[0].excerpt


def test_search_episodic_skips_unreadable_files(tmp_path):
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
    project_store.paths.root.mkdir(parents=True, exist_ok=True)
    (project_store.paths.root / "2026-04-22.md").write_bytes(b"\xff\xfe\x00")
    project_store.append_episodic("2026-04-23", "## Snapshot\n\n- readable needle")
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )

    result = retriever.search(keyword="needle", source="episodic")

    assert len(result.hits) == 1
    assert result.hits[0].identifier == "2026-04-23"


def test_search_rejects_unknown_scope(tmp_path):
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
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )
    try:
        retriever.search(keyword="x", scope="shared")
    except ValueError as exc:
        assert "scope" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown scope")


def test_search_rejects_unknown_source(tmp_path):
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
    retriever = MemoryRetriever(
        OverlayMemoryStore(global_store=global_store, project_store=project_store)
    )
    try:
        retriever.search(keyword="x", source="vector")
    except ValueError as exc:
        assert "source" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown source")
