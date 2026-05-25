from __future__ import annotations

import json

from memory_system import store_codec
from memory_system.models import SemanticMemory, SourceRef
from tests.conftest import make_memory_store


def test_frontmatter_scalar_flattens_newlines(tmp_path):
    store = make_memory_store(tmp_path / "memory")

    assert store_codec.frontmatter_scalar(store, "alpha\nbeta\ngamma") == (
        "alpha beta gamma"
    )


def test_semantic_memory_update_log_roundtrips(tmp_path):
    store = make_memory_store(tmp_path / "memory")
    item = SemanticMemory(
        id="risk-model",
        scope="project",
        title="Risk Model",
        content="Stable content.",
        concepts=["risk", "model"],
        source_refs=[SourceRef(kind="episode", path="episodes/2026-05-24.md")],
        confidence=0.8,
        strength=0.7,
        last_accessed=None,
        created_at="2026-05-24T10:00:00+08:00",
        updated_at="2026-05-24T11:00:00+08:00",
        update_log=["Update: created", "Conflict: revised assumption"],
    )

    text = store_codec.serialize_semantic_memory(store, item)
    parsed = store_codec.parse_semantic_memory(store, text)

    assert parsed.content == "Stable content."
    assert parsed.update_log == ["Update: created", "Conflict: revised assumption"]
    assert parsed.source_refs == item.source_refs


def test_parse_source_refs_invalid_json_returns_empty_list(tmp_path):
    store = make_memory_store(tmp_path / "memory")

    assert store_codec.parse_source_refs(store, "{not json") == []
    assert store_codec.parse_source_refs(store, json.dumps({"not": "a list"})) == []


def test_merge_source_refs_deduplicates_and_caps_at_fifty():
    duplicate = SourceRef(kind="source", path="sources/a.md", identifier="a")
    incoming = [duplicate] + [
        SourceRef(kind="source", path=f"sources/{index}.md", identifier=str(index))
        for index in range(60)
    ]

    merged = store_codec.merge_source_refs([duplicate], incoming)

    assert merged[0] == duplicate
    assert len(merged) == 50
    keys = {(ref.kind, ref.path, ref.identifier, ref.excerpt) for ref in merged}
    assert len(keys) == 50
