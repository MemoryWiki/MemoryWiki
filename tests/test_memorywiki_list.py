import json
import subprocess
import sys
from pathlib import Path

from memory_system.models import ProceduralMemory, SemanticMemory, SessionFile
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore
from memorywiki_list import list_memories


REPO_ROOT = Path(__file__).resolve().parents[1]


def _store(root: Path, scope: str = "project") -> ScopedMemoryStore:
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def _seed_memory(root: Path, scope: str = "project") -> None:
    store = _store(root, scope)
    store.write_semantic_memory(
        SemanticMemory(
            id="memory-browser",
            scope=scope,
            title="Memory Browser",
            content="List command should expose durable memory inventory.",
            concepts=["browser", "memory"],
            source_refs=[],
            confidence=0.8,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-24T10:00:00+08:00",
            updated_at="2026-05-24T10:00:00+08:00",
        )
    )
    store.write_procedural_memory(
        ProceduralMemory(
            id="explicit-save",
            scope=scope,
            title="Explicit Save",
            trigger="User asks to save memory.",
            steps=["Summarize", "Write session"],
            source_refs=[],
            confidence=0.75,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-24T10:01:00+08:00",
            updated_at="2026-05-24T10:01:00+08:00",
        )
    )
    store.write_session(
        SessionFile(
            id="session-20260524-100200",
            date="2026-05-24",
            scope=scope,
            title="List memory work",
            keypoints=["List command added"],
            actions=[],
            pending=[],
            duration_seconds=None,
            body="Session body.",
        )
    )
    store.append_to_episode("2026-05-24", "List work", "Added memory list command.")


def test_list_memories_filters_semantic_concepts(tmp_path):
    project_root = tmp_path / "project"
    _seed_memory(project_root)

    rows = list_memories(
        project_root=project_root,
        global_root=tmp_path / "global",
        scope="project",
        kind="semantic",
        concepts=["browser"],
    )

    assert [row.identifier for row in rows] == ["memory-browser"]
    assert rows[0].concepts == ["browser", "memory"]


def test_list_memories_includes_layered_inventory(tmp_path):
    project_root = tmp_path / "project"
    _seed_memory(project_root)

    rows = list_memories(
        project_root=project_root,
        global_root=tmp_path / "global",
        scope="project",
        kind="all",
    )

    kinds = {row.kind for row in rows}
    assert {"semantic", "procedural", "session", "episode"}.issubset(kinds)


def test_memorywiki_list_cli_outputs_json(tmp_path):
    project_root = tmp_path / "project"
    _seed_memory(project_root)

    result = subprocess.run(
        [
            sys.executable,
            "memorywiki_list.py",
            "--project-root",
            str(project_root),
            "--scope",
            "project",
            "--kind",
            "semantic",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["memories"][0]["identifier"] == "memory-browser"
    assert payload["memories"][0]["title"] == "Memory Browser"
