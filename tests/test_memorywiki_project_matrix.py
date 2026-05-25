from __future__ import annotations

import json
from pathlib import Path

from memory_system.models import SemanticMemory
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore
from memorywiki_project_matrix import ProjectTarget, run_project_matrix

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_semantic(root: Path, scope: str, memory_id: str, content: str) -> None:
    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    store.write_semantic_memory(
        SemanticMemory(
            id=memory_id,
            scope=scope,
            title=memory_id,
            content=content,
            concepts=["matrix"],
            source_refs=[],
            confidence=0.8,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-16T10:00:00+08:00",
            updated_at="2026-05-16T10:00:00+08:00",
        )
    )


def test_project_matrix_can_install_rebuild_index_doctor_and_eval(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    project.mkdir()
    _write_semantic(project / ".agent_memory" / "project", "project", "matrix-target", "Matrix target memory.")

    payload = run_project_matrix(
        projects=[
            ProjectTarget(
                name="demo",
                path=project,
                cases=[{"name": "demo", "query": "matrix target", "expected": ["matrix-target"]}],
            )
        ],
        memory_system_home=REPO_ROOT,
        python="/usr/bin/python3.12",
        global_root=global_root,
        install=True,
        update_existing_agents=True,
        write_indexes=True,
    )

    row = payload["projects"][0]
    assert payload["status"] in {"ok", "warn"}
    assert row["install"]["dry_run"] is False
    assert row["doctor"]["status"] in {"ok", "warn"}
    assert row["golden_eval"]["status"] == "pass"
    assert (project / ".mcp.json").exists()
    assert (project / ".agent_memory" / "project" / "retrieval" / "index.jsonl").exists()


def test_project_matrix_loads_config_file(tmp_path):
    config = tmp_path / "projects.json"
    project = tmp_path / "project"
    project.mkdir()
    config.write_text(
        json.dumps(
            [
                {
                    "name": "demo",
                    "path": str(project),
                    "cases": [{"name": "demo", "query": "x", "expected": ["x"]}],
                }
            ]
        ),
        encoding="utf-8",
    )

    from memorywiki_project_matrix import load_project_targets

    targets = load_project_targets(config)

    assert targets[0].name == "demo"
    assert targets[0].path == project


def test_example_project_matrix_config_has_key_project_case_coverage():
    from memorywiki_project_matrix import load_project_targets

    targets = load_project_targets(REPO_ROOT / "examples" / "project-matrix.example.json")

    assert {target.name for target in targets} == {"example-project"}
    for target in targets:
        assert not target.path.is_absolute()
        assert target.required_cases_min == 1
        assert target.required_cases_max == 3
        assert 1 <= len(target.cases) <= 3
        for case in target.cases:
            assert case["name"]
            assert case["query"]
            assert case["expected"]


def test_project_matrix_can_run_optional_mcp_smoke(tmp_path, monkeypatch):
    import memorywiki_project_matrix

    def fake_run_project_smoke(**kwargs):
        return {
            "status": "ok",
            "readonly": {
                "tools": ["memorywiki_recall", "memorywiki_read_memory"],
                "default_write_denied": True,
            },
        }

    project = tmp_path / "project"
    global_root = tmp_path / "global"
    project.mkdir()
    _write_semantic(project / ".agent_memory" / "project", "project", "matrix-smoke", "Matrix smoke memory.")
    monkeypatch.setattr(memorywiki_project_matrix, "_run_project_smoke", fake_run_project_smoke)

    payload = run_project_matrix(
        projects=[
            ProjectTarget(
                name="demo",
                path=project,
                cases=[{"name": "demo", "query": "matrix smoke", "expected": ["matrix-smoke"]}],
            )
        ],
        memory_system_home=REPO_ROOT,
        python="/usr/bin/python3.12",
        global_root=global_root,
        smoke=True,
    )

    row = payload["projects"][0]
    assert row["mcp_smoke"]["status"] == "ok"
    assert row["mcp_smoke"]["readonly"]["default_write_denied"] is True


def test_project_matrix_warns_when_project_has_no_project_level_golden_cases(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    project.mkdir()

    payload = run_project_matrix(
        projects=[
            ProjectTarget(
                name="demo",
                path=project,
                cases=[],
                required_cases_min=1,
                required_cases_max=3,
            )
        ],
        memory_system_home=REPO_ROOT,
        python="/usr/bin/python3.12",
        global_root=global_root,
    )

    row = payload["projects"][0]
    assert payload["status"] == "warn"
    assert row["case_coverage"]["status"] == "warn"
    assert row["case_coverage"]["case_count"] == 0
    assert row["case_coverage"]["required_cases_min"] == 1


def test_project_matrix_warns_when_project_has_too_many_cases(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    project.mkdir()
    for index in range(4):
        _write_semantic(
            project / ".agent_memory" / "project",
            "project",
            f"matrix-target-{index}",
            f"Matrix target {index}.",
        )

    payload = run_project_matrix(
        projects=[
            ProjectTarget(
                name="demo",
                path=project,
                cases=[
                    {
                        "name": f"case-{index}",
                        "query": f"Matrix target {index}",
                        "expected": [f"matrix-target-{index}"],
                    }
                    for index in range(4)
                ],
                required_cases_min=1,
                required_cases_max=3,
            )
        ],
        memory_system_home=REPO_ROOT,
        python="/usr/bin/python3.12",
        global_root=global_root,
    )

    row = payload["projects"][0]
    assert payload["status"] == "warn"
    assert row["case_coverage"]["status"] == "warn"
    assert "above maximum" in row["case_coverage"]["message"]
