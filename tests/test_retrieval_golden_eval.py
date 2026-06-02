from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import retrieval_golden_eval
from memory_system.models import SemanticMemory
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore
from retrieval_golden_eval import DEFAULT_CASES, RetrievalCase, load_cases, run_golden_eval


def _store(root: Path, scope: str) -> ScopedMemoryStore:
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def _write_semantic(root: Path, scope: str, memory_id: str, content: str) -> None:
    _store(root, scope).write_semantic_memory(
        SemanticMemory(
            id=memory_id,
            scope=scope,
            title=memory_id.replace("-", " ").title(),
            content=content,
            concepts=["demo", "memorywiki"],
            source_refs=[],
            confidence=0.8,
            strength=0.7,
            last_accessed=None,
            created_at="2026-05-15T10:00:00+08:00",
            updated_at="2026-05-15T10:00:00+08:00",
        )
    )


def test_retrieval_golden_eval_passes_when_expected_identifier_is_recalled(tmp_path):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    _write_semantic(
        project_root,
        "project",
        "demo-runtime",
        "DemoProject is a local-first analysis runtime.",
    )

    payload = run_golden_eval(
        project_root=project_root,
        global_root=global_root,
        cases=[
            RetrievalCase(
                name="demo-runtime",
                query="DemoProject analysis runtime",
                expected=["demo-runtime"],
            )
        ],
        min_pass_rate=1.0,
    )

    assert payload["status"] == "pass"
    assert payload["passed"] == 1
    assert payload["cases"][0]["matched"] == "demo-runtime"
    assert payload["cases"][0]["rank"] == 1
    assert payload["cases"][0]["reciprocal_rank"] == 1.0
    assert payload["mean_reciprocal_rank"] == 1.0
    assert payload["required_passed"] == 1
    assert payload["required_total"] == 1


def test_retrieval_golden_eval_reports_failed_cases(tmp_path):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    _write_semantic(project_root, "project", "other-memory", "Unrelated memory.")

    payload = run_golden_eval(
        project_root=project_root,
        global_root=global_root,
        cases=[
            RetrievalCase(
                name="missing",
                query="very specific missing target",
                expected=["not-present"],
            )
        ],
        min_pass_rate=1.0,
    )

    assert payload["status"] == "fail"
    assert payload["failed"] == 1
    assert payload["cases"][0]["rank"] is None
    assert payload["cases"][0]["failure_reason"]
    assert payload["required_failed"] == 1


def test_retrieval_golden_eval_enforces_required_min_rank(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"

    def fake_recall(args):
        return SimpleNamespace(
            hits=[
                SimpleNamespace(
                    scope="project",
                    source="semantic",
                    identifier="first-memory",
                    title="First",
                    excerpt="Shared MemoryWiki governance target.",
                    score=2.0,
                    provenance=[],
                ),
                SimpleNamespace(
                    scope="project",
                    source="semantic",
                    identifier="target-memory",
                    title="Target",
                    excerpt="Shared MemoryWiki governance target.",
                    score=1.0,
                    provenance=[],
                ),
            ],
            warnings=[],
        )

    monkeypatch.setattr(retrieval_golden_eval, "recall", fake_recall)

    payload = run_golden_eval(
        project_root=project_root,
        global_root=global_root,
        cases=[
            RetrievalCase(
                name="rank-guard",
                query="Shared MemoryWiki governance target",
                expected=["target-memory"],
                query_type="semantic",
                min_rank=1,
                required=True,
                severity="core",
                owner="memorywiki",
                project="demo-project",
            )
        ],
        min_pass_rate=1.0,
        strategy="live",
    )

    assert payload["status"] == "fail"
    assert payload["required_failed"] == 1
    assert payload["cases"][0]["rank"] == 2
    assert payload["cases"][0]["min_rank"] == 1
    assert "min_rank" in payload["cases"][0]["failure_reason"]
    assert payload["cases"][0]["owner"] == "memorywiki"
    assert payload["cases"][0]["project"] == "demo-project"
    assert payload["cases"][0]["query_type"] == "semantic"
    assert payload["query_type_metrics"]["semantic"]["required_total"] == 1


def test_retrieval_golden_eval_optional_failure_does_not_fail_required_set(tmp_path):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    _write_semantic(project_root, "project", "core-memory", "Core MemoryWiki governance target.")

    payload = run_golden_eval(
        project_root=project_root,
        global_root=global_root,
        cases=[
            RetrievalCase(
                name="core",
                query="Core MemoryWiki governance target",
                expected=["core-memory"],
                required=True,
            ),
            RetrievalCase(
                name="optional",
                query="missing optional target",
                expected=["not-present"],
                required=False,
            ),
        ],
        min_pass_rate=0.5,
        strategy="live",
    )

    assert payload["status"] == "pass"
    assert payload["optional_failed"] == 1
    assert payload["required_failed"] == 0


def test_retrieval_golden_eval_respects_expected_scope_and_source(tmp_path):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    _write_semantic(project_root, "project", "target-memory", "Shared target text.")

    payload = run_golden_eval(
        project_root=project_root,
        global_root=global_root,
        cases=[
            RetrievalCase(
                name="wrong-scope",
                query="Shared target text",
                expected=["target-memory"],
                expected_scope="global",
                expected_source="semantic",
            )
        ],
        min_pass_rate=1.0,
        strategy="live",
    )

    assert payload["status"] == "fail"
    assert payload["cases"][0]["failure_reason"] == "expected target not found with required scope/source"


def test_load_cases_merges_registry_global_and_matching_project_cases(tmp_path):
    project_root = tmp_path / "project-alpha"
    registry = tmp_path / "golden.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "global": [
                    {
                        "name": "global-case",
                        "query": "global query",
                        "expected": ["global-target"],
                    }
                ],
                "projects": {
                    project_root.name: [
                        {
                            "name": "project-case",
                            "query": "project query",
                            "expected": ["project-target"],
                            "expected_scope": "project",
                            "expected_source": "semantic",
                            "query_type": "cross_project",
                            "required": False,
                            "min_rank": 3,
                            "severity": "watch",
                            "owner": "retrieval",
                            "project": "project-alpha",
                        }
                    ],
                    "other": [
                        {
                            "name": "other-case",
                            "query": "other query",
                            "expected": ["other-target"],
                        }
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cases = load_cases(registry, project_root=project_root)

    assert [case.name for case in cases] == ["global-case", "project-case"]
    assert cases[1].expected_scope == "project"
    assert cases[1].expected_source == "semantic"
    assert cases[1].query_type == "cross_project"


def test_retrieval_golden_eval_passes_router_and_reranker_flags_to_recall(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    seen = {}

    def fake_recall(args):
        seen["granularity_router"] = args.granularity_router
        seen["association_reranker"] = args.association_reranker
        seen["ranker"] = args.ranker
        return SimpleNamespace(
            hits=[
                SimpleNamespace(
                    scope="project",
                    source="semantic",
                    identifier="target-memory",
                    title="Target",
                    excerpt="target memory text",
                    score=2.0,
                    provenance=[],
                )
            ],
            warnings=[],
        )

    monkeypatch.setattr(retrieval_golden_eval, "recall", fake_recall)

    payload = run_golden_eval(
        project_root=project_root,
        global_root=global_root,
        cases=[
            RetrievalCase(
                name="router-case",
                query="target memory",
                expected=["target-memory"],
                query_type="view_router",
            )
        ],
        min_pass_rate=1.0,
        ranker="score",
        granularity_router="entropy",
        association_reranker="local",
        index_schema_version=3,
        baseline_run_id="baseline-001",
    )

    assert payload["status"] == "pass"
    assert seen == {
        "granularity_router": "entropy",
        "association_reranker": "local",
        "ranker": "score",
    }
    assert payload["granularity_router"] == "entropy"
    assert payload["association_reranker"] == "local"
    assert payload["index_schema_version"] == 3
    assert payload["baseline_run_id"] == "baseline-001"
    assert payload["query_type_metrics"]["view_router"]["pass_rate"] == 1.0


def test_retrieval_golden_eval_attaches_baseline_rank_deltas(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"

    def fake_recall(args):
        return SimpleNamespace(
            hits=[
                SimpleNamespace(
                    scope="project",
                    source="semantic",
                    identifier="target-memory",
                    title="Target",
                    excerpt="target memory text",
                    score=2.0,
                    provenance=[],
                )
            ],
            warnings=[],
        )

    monkeypatch.setattr(retrieval_golden_eval, "recall", fake_recall)

    payload = run_golden_eval(
        project_root=project_root,
        global_root=global_root,
        cases=[
            RetrievalCase(
                name="delta-case",
                query="target memory",
                expected=["target-memory"],
            )
        ],
        min_pass_rate=1.0,
        baseline={
            "cases": [
                {
                    "name": "delta-case",
                    "rank": 3,
                    "passed": False,
                }
            ]
        },
    )

    assert payload["cases"][0]["baseline"]["old_rank"] == 3
    assert payload["cases"][0]["baseline"]["new_rank"] == 1
    assert payload["cases"][0]["baseline"]["rank_delta"] == -2
    assert payload["cases"][0]["baseline"]["pass_transition"] == "False->True"
    assert payload["cases"][0]["baseline"]["top_hit_changed"] is True


def test_retrieval_golden_eval_enforces_min_mrr_and_required_regression_gate(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"

    def fake_recall(args):
        return SimpleNamespace(
            hits=[
                SimpleNamespace(
                    scope="project",
                    source="semantic",
                    identifier="wrong-memory",
                    title="Wrong",
                    excerpt="wrong memory text",
                    score=2.0,
                    provenance=[],
                )
            ],
            warnings=[],
        )

    monkeypatch.setattr(retrieval_golden_eval, "recall", fake_recall)

    payload = run_golden_eval(
        project_root=project_root,
        global_root=global_root,
        cases=[
            RetrievalCase(
                name="regression-case",
                query="target memory",
                expected=["target-memory"],
                required=True,
            )
        ],
        min_pass_rate=0.0,
        min_mrr=0.9,
        fail_on_required_regression=True,
        baseline={
            "cases": [
                {
                    "name": "regression-case",
                    "rank": 1,
                    "passed": True,
                    "top_hits": [
                        {
                            "scope": "project",
                            "source": "semantic",
                            "identifier": "target-memory",
                        }
                    ],
                }
            ]
        },
    )

    assert payload["status"] == "fail"
    assert payload["mrr_ok"] is False
    assert payload["required_regression_count"] == 1


def test_default_golden_cases_do_not_include_private_session_ids():
    encoded = json.dumps([case.__dict__ for case in DEFAULT_CASES])

    assert "session-" not in encoded


def test_private_golden_registry_is_not_packaged_for_public_builds():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert '"docs/memorywiki-golden-cases.json"' not in pyproject


def test_load_cases_falls_back_to_installed_default_registry(tmp_path, monkeypatch):
    installed = tmp_path / "prefix" / "memorywiki" / "docs" / "memorywiki-golden-cases.json"
    installed.parent.mkdir(parents=True)
    installed.write_text(
        json.dumps(
            {
                "global": [
                    {
                        "name": "installed-case",
                        "query": "installed query",
                        "expected": ["installed-target"],
                    }
                ],
                "projects": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retrieval_golden_eval, "DEFAULT_CASE_REGISTRY", tmp_path / "missing.json")
    monkeypatch.setattr(retrieval_golden_eval, "INSTALLED_CASE_REGISTRY", installed)
    monkeypatch.chdir(tmp_path)

    cases = load_cases("docs/memorywiki-golden-cases.json")

    assert [case.name for case in cases] == ["installed-case"]


def test_load_cases_deduplicates_project_registry_alias_matches(tmp_path):
    project_root = tmp_path / "project-alpha"
    project_root.mkdir()
    registry = tmp_path / "golden.json"
    project_case = {
        "name": "project-case",
        "query": "project query",
        "expected": ["project-target"],
    }
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "global": [],
                "projects": {
                    project_root.name: [project_case],
                    str(project_root.resolve()): [project_case],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cases = load_cases(registry, project_root=project_root)

    assert [case.name for case in cases] == ["project-case"]


def test_load_cases_rejects_invalid_registry_global_shape(tmp_path):
    registry = tmp_path / "golden.json"
    registry.write_text(
        json.dumps({"version": 1, "global": {}, "projects": {}}) + "\n",
        encoding="utf-8",
    )

    try:
        load_cases(registry, project_root=tmp_path / "project")
    except ValueError as exc:
        assert "global must be a list" in str(exc)
    else:
        raise AssertionError("expected invalid global registry shape to fail")


def test_default_golden_cases_cover_core_global_projects():
    names = {case.name for case in DEFAULT_CASES}

    assert {
        "memorywiki-mcp",
        "memorywiki-pkm-positioning",
        "source-ingest-provenance",
        "lifecycle-governance",
        "cross-project-recall",
        "privacy-public-clean",
        "operator-quality-loop",
    }.issubset(names)
