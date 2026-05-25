import subprocess
import sys
from pathlib import Path

from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_memory_crystallize_saves_good_answer_as_semantic_memory(tmp_path):
    root = tmp_path / "memory"

    subprocess.run(
        [
            sys.executable,
            "memory_crystallize.py",
            "--root",
            str(root),
            "--kind",
            "semantic",
            "--id",
            "good-answer",
            "--title",
            "Good answer",
            "--answer",
            "A good answer should be promoted into structured MemoryWiki memory, not left only in chat.",
            "--concept",
            "crystallization",
            "--source-kind",
            "session",
            "--source-path",
            "sessions/session-20260514-120000.md",
            "--source-id",
            "session-20260514-120000",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope="project"),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    loaded = store.read_semantic_memory("good-answer")

    assert "structured MemoryWiki memory" in loaded.content
    assert loaded.source_refs[0].path == "sessions/session-20260514-120000.md"
    assert "good-answer" in store.read_index()


def test_memory_crystallize_refuses_to_overwrite_without_replace(tmp_path):
    root = tmp_path / "memory"
    base_cmd = [
        sys.executable,
        "memory_crystallize.py",
        "--root",
        str(root),
        "--kind",
        "semantic",
        "--id",
        "stable-answer",
        "--title",
        "Stable answer",
        "--answer",
        "First answer.",
    ]

    subprocess.run(base_cmd, cwd=REPO_ROOT, text=True, capture_output=True, check=True)
    result = subprocess.run(
        base_cmd, cwd=REPO_ROOT, text=True, capture_output=True
    )

    assert result.returncode != 0
    assert "already exists" in result.stderr
