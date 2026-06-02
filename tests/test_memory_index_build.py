import json
import subprocess
import sys
from pathlib import Path

from memory_system.models import SemanticMemory, SessionFile
from memory_system.retrieval_index import MAX_INDEX_TERM_COUNTS

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_memory_index_build_writes_local_retrieval_index(tmp_path, memory_store_factory):
    project_root = tmp_path / "project"
    store = memory_store_factory(project_root)
    store.write_semantic_memory(
        SemanticMemory(
            id="hybrid-retrieval",
            scope="project",
            title="Hybrid Retrieval",
            content="Hybrid recall uses a local retrieval index.",
            concepts=["retrieval", "hybrid"],
            source_refs=[],
            confidence=0.8,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-15T10:00:00+08:00",
            updated_at="2026-05-15T10:00:00+08:00",
        )
    )
    store.write_session(
        SessionFile(
            id="session-20260515-101500",
            date="2026-05-15",
            scope="project",
            title="Hybrid recall session",
            keypoints=["index build"],
            actions=[],
            pending=[],
            duration_seconds=None,
            body="Session context is indexed too.",
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "memory_index_build.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    rows = [
        json.loads(line)
        for line in (project_root / "retrieval" / "index.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert payload["indexed"] >= 2
    assert payload["index_path"] == str(project_root / "retrieval" / "index.jsonl")
    assert {row["source"] for row in rows} >= {"semantic", "session"}
    semantic = next(row for row in rows if row["identifier"] == "hybrid-retrieval")
    assert semantic["source_path"] == "semantic/hybrid-retrieval.md"
    assert semantic["sha256"]
    assert semantic["term_counts"]["retrieval"] >= 1
    assert semantic["embedding_model"] == "memorywiki-local-hash-v1"
    assert semantic["embedding_dimensions"] == 256
    assert semantic["embedding_vector"]


def test_memory_index_build_tokenizes_chinese_terms_and_update_log(
    tmp_path, memory_store_factory
):
    project_root = tmp_path / "project"
    store = memory_store_factory(project_root)
    store.write_semantic_memory(
        SemanticMemory(
            id="ai-power-scenarios",
            scope="project",
            title="AI 中美电力竞争四剧本",
            content="硬破裂、软回落、继续扩张、彻底分叉。",
            concepts=["AI", "中美", "电力竞争"],
            source_refs=[],
            confidence=0.8,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-15T10:00:00+08:00",
            updated_at="2026-05-15T10:00:00+08:00",
            update_log=[
                "2026-05-15T11:00:00+08:00 Conflict: 新来源调整彻底分叉概率。"
            ],
        )
    )

    subprocess.run(
        [
            sys.executable,
            "memory_index_build.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = [
        json.loads(line)
        for line in (project_root / "retrieval" / "index.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    semantic = next(row for row in rows if row["identifier"] == "ai-power-scenarios")

    assert semantic["term_counts"]["电力"] >= 1
    assert semantic["term_counts"]["竞争"] >= 1
    assert semantic["term_counts"]["电力竞争"] >= 1
    assert semantic["conflict_history"] is True
    assert "Conflict:" in semantic["conflict_entries"][0]


def test_memory_index_build_caps_term_counts_for_long_cjk_text(tmp_path, memory_store_factory):
    project_root = tmp_path / "project"
    store = memory_store_factory(project_root)
    store.write_session(
        SessionFile(
            id="session-20260527-101500",
            date="2026-05-27",
            scope="project",
            title="Long CJK session",
            keypoints=[],
            actions=[],
            pending=[],
            duration_seconds=None,
            body="".join(chr(0x4E00 + (index % 1800)) for index in range(5000)),
        )
    )

    subprocess.run(
        [
            sys.executable,
            "memory_index_build.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    row = json.loads((project_root / "retrieval" / "index.jsonl").read_text(encoding="utf-8"))

    assert len(row["term_counts"]) <= MAX_INDEX_TERM_COUNTS
    for view in row.get("views", []):
        assert len(view["term_counts"]) <= MAX_INDEX_TERM_COUNTS


def test_memory_index_build_rejects_symlinked_index_file(tmp_path, memory_store_factory):
    project_root = tmp_path / "project"
    store = memory_store_factory(project_root)
    store.write_semantic_memory(
        SemanticMemory(
            id="safe-index",
            scope="project",
            title="Safe Index",
            content="safe index",
            concepts=[],
            source_refs=[],
            confidence=0.5,
            strength=0.5,
            last_accessed=None,
            created_at="2026-05-15T10:00:00+08:00",
            updated_at="2026-05-15T10:00:00+08:00",
        )
    )
    outside = tmp_path / "outside.jsonl"
    outside.write_text("", encoding="utf-8")
    retrieval_dir = project_root / "retrieval"
    retrieval_dir.mkdir()
    (retrieval_dir / "index.jsonl").symlink_to(outside)

    result = subprocess.run(
        [
            sys.executable,
            "memory_index_build.py",
            "--root",
            str(project_root),
            "--scope",
            "project",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "symlink" in result.stderr.lower()
    assert outside.read_text(encoding="utf-8") == ""
