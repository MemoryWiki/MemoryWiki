from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from memory_recall import recall


@dataclass
class RetrievalCase:
    name: str
    query: str
    expected: list[str]
    query_type: str = "general"
    expected_scope: str = ""
    expected_source: str = ""
    tags: list[str] | None = None
    required: bool = True
    min_rank: int | None = None
    severity: str = "core"
    owner: str = ""
    project: str = ""


DEFAULT_CASES = [
    RetrievalCase(
        name="memorywiki-mcp",
        query="MemoryWiki MCP client bridge retrieval enhancement",
        expected=["memorywiki-overview", "memorywiki-mcp"],
        query_type="mcp",
        min_rank=3,
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="memorywiki-pkm-positioning",
        query="MemoryWiki combines chat memory with personal knowledge management local-first Markdown",
        expected=["memorywiki-pkm-positioning"],
        query_type="semantic",
        min_rank=3,
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="source-ingest-provenance",
        query="MemoryWiki source ingest SHA256 provenance tamper evidence",
        expected=["source-ingest-provenance", "source-sha256"],
        query_type="source_provenance",
        min_rank=3,
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="lifecycle-governance",
        query="MemoryWiki lifecycle review stale weak memory archival governance",
        expected=["lifecycle-governance", "memory-lifecycle"],
        query_type="lifecycle",
        min_rank=3,
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="cross-project-recall",
        query="MemoryWiki cross project recall MCP startup bridge",
        expected=["cross-project-recall", "memorywiki-mcp"],
        query_type="cross_project",
        min_rank=3,
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="privacy-public-clean",
        query="MemoryWiki public release privacy scan private path marker cleanup",
        expected=["privacy-public-clean"],
        query_type="safety",
        required=False,
        min_rank=8,
        severity="watch",
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="operator-quality-loop",
        query="MemoryWiki operator dashboard quality report golden eval review loop",
        expected=["operator-quality-loop"],
        query_type="ops",
        required=False,
        min_rank=8,
        severity="watch",
        owner="memorywiki",
        project="global",
    ),
]


DEFAULT_CASE_REGISTRY = Path(__file__).resolve().parent / "docs" / "memorywiki-golden-cases.json"
INSTALLED_CASE_REGISTRY = (
    Path(sys.prefix) / "memorywiki" / "docs" / "memorywiki-golden-cases.json"
)


def _default_case_registry() -> Path | None:
    for candidate in (DEFAULT_CASE_REGISTRY, INSTALLED_CASE_REGISTRY):
        if candidate.exists() and candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def _resolve_case_file(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.exists():
        return candidate
    if candidate.as_posix() == "docs/memorywiki-golden-cases.json":
        installed = _default_case_registry()
        if installed is not None:
            return installed
    return candidate


def _case_from_dict(payload: dict[str, Any]) -> RetrievalCase:
    expected = payload.get("expected", [])
    if isinstance(expected, str):
        expected = [expected]
    return RetrievalCase(
        name=str(payload["name"]),
        query=str(payload["query"]),
        expected=[str(item) for item in expected],
        query_type=str(payload.get("query_type", "general")),
        expected_scope=str(payload.get("expected_scope", "")),
        expected_source=str(payload.get("expected_source", "")),
        tags=[str(item) for item in payload.get("tags", [])]
        if isinstance(payload.get("tags", []), list)
        else [],
        required=bool(payload.get("required", True)),
        min_rank=int(payload["min_rank"]) if payload.get("min_rank") is not None else None,
        severity=str(payload.get("severity", "core")),
        owner=str(payload.get("owner", "")),
        project=str(payload.get("project", "")),
    )


def _project_registry_keys(project_root: str | Path | None) -> set[str]:
    if project_root is None:
        return set()
    path = Path(project_root).expanduser()
    keys = {str(path), path.name}
    try:
        keys.add(str(path.resolve()))
    except OSError:
        pass
    return keys


def load_cases(
    path: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
) -> list[RetrievalCase]:
    if not path:
        registry = _default_case_registry()
        if registry is not None:
            return load_cases(registry, project_root=project_root)
        return list(DEFAULT_CASES)
    payload = json.loads(_resolve_case_file(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [_case_from_dict(item) for item in payload]
    if not isinstance(payload, dict):
        raise ValueError("Case file must be a JSON list or registry object")
    global_cases = payload.get("global", [])
    if not isinstance(global_cases, list):
        raise ValueError("Case registry global must be a list")
    cases = [_case_from_dict(item) for item in global_cases]
    projects = payload.get("projects", {})
    if not isinstance(projects, dict):
        raise ValueError("Case registry projects must be an object")
    seen_names = {case.name for case in cases}
    selected_keys = _project_registry_keys(project_root)
    for key in sorted(selected_keys):
        project_cases = projects.get(key, [])
        if not isinstance(project_cases, list):
            raise ValueError(f"Project case registry entry must be a list: {key}")
        for item in project_cases:
            case = _case_from_dict(item)
            if case.name in seen_names:
                continue
            cases.append(case)
            seen_names.add(case.name)
    return cases


def _hit_text(hit: Any) -> str:
    provenance = " ".join(
        " ".join(str(value or "") for value in vars(ref).values())
        for ref in getattr(hit, "provenance", [])
    )
    return " ".join(
        [
            str(getattr(hit, "scope", "")),
            str(getattr(hit, "source", "")),
            str(getattr(hit, "identifier", "")),
            str(getattr(hit, "title", "")),
            str(getattr(hit, "excerpt", "")),
            provenance,
        ]
    ).lower()


def _evaluate_case(
    case: RetrievalCase,
    *,
    project_root: Path,
    global_root: Path,
    limit: int,
    token_budget: int,
    strategy: str,
    embedding: str,
    graph: str,
    ranker: str,
    granularity_router: str,
    association_reranker: str,
) -> dict[str, Any]:
    args = SimpleNamespace(
        query=case.query,
        scope="all",
        project_root=str(project_root),
        global_root=str(global_root),
        limit=limit,
        token_budget=token_budget,
        strategy=strategy,
        embedding=embedding,
        graph=graph,
        ranker=ranker,
        granularity_router=granularity_router,
        association_reranker=association_reranker,
        refresh_index_if_needed=False,
    )
    result = recall(args)
    expected = [item.lower() for item in case.expected]
    matched = ""
    matched_rank: int | None = None
    expected_scope = (case.expected_scope or "").lower()
    expected_source = (case.expected_source or "").lower()
    for index, hit in enumerate(result.hits, start=1):
        if expected_scope and str(hit.scope).lower() != expected_scope:
            continue
        if expected_source and str(hit.source).lower() != expected_source:
            continue
        text = _hit_text(hit)
        for target in expected:
            if target and target in text:
                matched = target
                matched_rank = index
                break
        if matched:
            break
    found = matched_rank is not None
    rank_ok = bool(
        matched_rank is not None
        and (case.min_rank is None or matched_rank <= case.min_rank)
    )
    if not expected:
        failure_reason = "case has no expected target"
    elif found and not rank_ok:
        failure_reason = f"matched at rank {matched_rank} exceeds min_rank {case.min_rank}"
    elif matched:
        failure_reason = ""
    elif not result.hits:
        failure_reason = "no hits returned"
    elif expected_scope or expected_source:
        failure_reason = "expected target not found with required scope/source"
    else:
        failure_reason = f"expected target not found in top {len(result.hits)} hits"
    return {
        "name": case.name,
        "query": case.query,
        "query_type": case.query_type,
        "expected": case.expected,
        "expected_scope": case.expected_scope,
        "expected_source": case.expected_source,
        "required": case.required,
        "min_rank": case.min_rank,
        "severity": case.severity,
        "owner": case.owner,
        "project": case.project,
        "found": found,
        "passed": bool(rank_ok),
        "matched": matched,
        "rank": matched_rank,
        "reciprocal_rank": round(1.0 / matched_rank, 6) if matched_rank else 0.0,
        "top_k": limit,
        "failure_reason": failure_reason,
        "top_hits": [
            {
                "scope": hit.scope,
                "source": hit.source,
                "identifier": hit.identifier,
                "title": hit.title,
                "score": round(hit.score, 4),
            }
            for hit in result.hits[: min(5, len(result.hits))]
        ],
        "warnings": result.warnings,
    }


def run_golden_eval(
    *,
    project_root: str | Path,
    global_root: str | Path,
    cases: list[RetrievalCase] | None = None,
    min_pass_rate: float = 0.8,
    limit: int = 8,
    token_budget: int = 1200,
    strategy: str = "hybrid",
    embedding: str = "local",
    graph: str = "local",
    ranker: str = "rrf",
    granularity_router: str = "off",
    association_reranker: str = "off",
    index_schema_version: int | None = None,
    baseline_run_id: str = "",
    baseline: dict[str, Any] | None = None,
    min_mrr: float | None = None,
    fail_on_required_regression: bool = False,
) -> dict[str, Any]:
    selected = cases if cases is not None else list(DEFAULT_CASES)
    case_results = [
        _evaluate_case(
            case,
            project_root=Path(project_root).expanduser(),
            global_root=Path(global_root).expanduser(),
            limit=limit,
            token_budget=token_budget,
            strategy=strategy,
            embedding=embedding,
            graph=graph,
            ranker=ranker,
            granularity_router=granularity_router,
            association_reranker=association_reranker,
        )
        for case in selected
    ]
    if baseline:
        _attach_baseline_deltas(case_results, baseline)
    passed = sum(1 for item in case_results if item["passed"])
    total = len(case_results)
    required_results = [item for item in case_results if item.get("required", True)]
    optional_results = [item for item in case_results if not item.get("required", True)]
    required_passed = sum(1 for item in required_results if item["passed"])
    optional_passed = sum(1 for item in optional_results if item["passed"])
    pass_rate = passed / total if total else 1.0
    mean_reciprocal_rank = (
        sum(float(item["reciprocal_rank"]) for item in case_results) / total
        if total
        else 1.0
    )
    required_total = len(required_results)
    optional_total = len(optional_results)
    required_pass_rate = required_passed / required_total if required_total else 1.0
    optional_pass_rate = optional_passed / optional_total if optional_total else 1.0
    required_failed = required_total - required_passed
    optional_failed = optional_total - optional_passed
    query_type_metrics = _query_type_metrics(case_results)
    required_regressions = [
        item
        for item in case_results
        if item.get("required", True)
        and item.get("baseline", {}).get("old_passed") is True
        and item.get("baseline", {}).get("new_passed") is False
    ]
    mrr_ok = min_mrr is None or mean_reciprocal_rank >= min_mrr
    regression_ok = not fail_on_required_regression or not required_regressions
    status = (
        "pass"
        if pass_rate >= min_pass_rate
        and required_failed == 0
        and mrr_ok
        and regression_ok
        else "fail"
    )
    return {
        "status": status,
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "required_passed": required_passed,
        "required_failed": required_failed,
        "required_total": required_total,
        "required_pass_rate": required_pass_rate,
        "optional_passed": optional_passed,
        "optional_failed": optional_failed,
        "optional_total": optional_total,
        "optional_pass_rate": optional_pass_rate,
        "pass_rate": pass_rate,
        "top_k_pass_rate": pass_rate,
        "mean_reciprocal_rank": mean_reciprocal_rank,
        "min_pass_rate": min_pass_rate,
        "min_mrr": min_mrr,
        "mrr_ok": mrr_ok,
        "required_regression_count": len(required_regressions),
        "strategy": strategy,
        "embedding": embedding,
        "graph": graph,
        "ranker": ranker,
        "granularity_router": granularity_router,
        "association_reranker": association_reranker,
        "index_schema_version": index_schema_version,
        "baseline_run_id": baseline_run_id,
        "query_type_metrics": query_type_metrics,
        "cases": case_results,
    }


def _query_type_metrics(case_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in case_results:
        buckets.setdefault(str(item.get("query_type") or "general"), []).append(item)
    metrics = {}
    for query_type, items in sorted(buckets.items()):
        total = len(items)
        passed = sum(1 for item in items if item["passed"])
        required = [item for item in items if item.get("required", True)]
        required_passed = sum(1 for item in required if item["passed"])
        metrics[query_type] = {
            "passed": passed,
            "total": total,
            "pass_rate": passed / total if total else 1.0,
            "required_passed": required_passed,
            "required_total": len(required),
            "required_pass_rate": required_passed / len(required) if required else 1.0,
            "mean_reciprocal_rank": (
                sum(float(item["reciprocal_rank"]) for item in items) / total
                if total
                else 1.0
            ),
        }
    return metrics


def _attach_baseline_deltas(
    case_results: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> None:
    previous_cases = {
        str(item.get("name")): item
        for item in baseline.get("cases", [])
        if isinstance(item, dict) and item.get("name")
    }
    for item in case_results:
        previous = previous_cases.get(str(item.get("name")))
        if not previous:
            continue
        old_rank = previous.get("rank")
        new_rank = item.get("rank")
        old_top_hit = _top_hit_key(previous)
        new_top_hit = _top_hit_key(item)
        item["baseline"] = {
            "query_type": item.get("query_type", "general"),
            "old_rank": old_rank,
            "new_rank": new_rank,
            "rank_delta": (
                int(new_rank) - int(old_rank)
                if isinstance(old_rank, int) and isinstance(new_rank, int)
                else None
            ),
            "old_passed": bool(previous.get("passed")),
            "new_passed": bool(item.get("passed")),
            "pass_transition": "{}->{}".format(bool(previous.get("passed")), bool(item.get("passed"))),
            "old_top_hit": old_top_hit,
            "new_top_hit": new_top_hit,
            "top_hit_changed": old_top_hit != new_top_hit,
        }


def _top_hit_key(case_result: dict[str, Any]) -> str:
    hits = case_result.get("top_hits") or []
    if not hits or not isinstance(hits[0], dict):
        return ""
    hit = hits[0]
    return "{}/{}/{}".format(
        hit.get("scope", ""),
        hit.get("source", ""),
        hit.get("identifier", ""),
    )


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Retrieval Golden Eval",
        "",
        "Status: {}".format(payload["status"]),
        "Pass rate: {:.0f}% ({}/{})".format(
            payload["pass_rate"] * 100,
            payload["passed"],
            payload["total"],
        ),
        "Required: {:.0f}% ({}/{})".format(
            payload.get("required_pass_rate", 1.0) * 100,
            payload.get("required_passed", 0),
            payload.get("required_total", 0),
        ),
        "MRR: {:.3f}".format(payload.get("mean_reciprocal_rank", 0.0)),
        "Min MRR: {} | MRR OK: {}".format(
            payload.get("min_mrr") if payload.get("min_mrr") is not None else "n/a",
            payload.get("mrr_ok", True),
        ),
        "Router: {} | Association: {} | Ranker: {}".format(
            payload.get("granularity_router", "off"),
            payload.get("association_reranker", "off"),
            payload.get("ranker", "rrf"),
        ),
        "",
    ]
    for case in payload["cases"]:
        marker = "PASS" if case["passed"] else "FAIL"
        rank = case.get("rank")
        rank_text = f"rank {rank}" if rank else case.get("failure_reason", "no match")
        case_label = " ({}){}".format(
            case.get("query_type", "general"),
            "" if case.get("required", True) else " optional",
        )
        lines.append(
            "- [{}] {}{} -> {} ({})".format(
                marker,
                case["name"],
                case_label,
                case["matched"] or "no match",
                rank_text,
            )
        )
        if case["warnings"]:
            lines.append("  warnings: {}".format("; ".join(case["warnings"][:3])))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MemoryWiki retrieval golden-query evaluation.")
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument(
        "--case-file",
        help="JSON list or registry object. Defaults to docs/memorywiki-golden-cases.json when present.",
    )
    parser.add_argument("--min-pass-rate", type=float, default=0.8)
    parser.add_argument("--min-mrr", type=float)
    parser.add_argument(
        "--fail-on-required-regression",
        action="store_true",
        help="Fail if a required case that passed in --baseline-file now fails.",
    )
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--token-budget", type=int, default=1200)
    parser.add_argument("--strategy", choices=("live", "indexed", "hybrid"), default="hybrid")
    parser.add_argument("--embedding", choices=("off", "local"), default="local")
    parser.add_argument("--graph", choices=("off", "local"), default="local")
    parser.add_argument("--ranker", choices=("rrf", "score"), default="rrf")
    parser.add_argument(
        "--granularity-router",
        choices=("off", "static", "entropy"),
        default="off",
    )
    parser.add_argument(
        "--association-reranker",
        choices=("off", "local"),
        default="off",
    )
    parser.add_argument("--index-schema-version", type=int)
    parser.add_argument("--baseline-run-id", default="")
    parser.add_argument(
        "--baseline-file",
        help="Previous JSON golden eval payload for delta reporting.",
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cases = load_cases(args.case_file, project_root=args.project_root)
        baseline = None
        if args.baseline_file:
            baseline = json.loads(Path(args.baseline_file).expanduser().read_text(encoding="utf-8"))
        payload = run_golden_eval(
            project_root=args.project_root,
            global_root=args.global_root,
            cases=cases,
            min_pass_rate=args.min_pass_rate,
            limit=args.limit,
            token_budget=args.token_budget,
            strategy=args.strategy,
            embedding=args.embedding,
            graph=args.graph,
            ranker=args.ranker,
            granularity_router=args.granularity_router,
            association_reranker=args.association_reranker,
            index_schema_version=args.index_schema_version,
            baseline_run_id=args.baseline_run_id,
            baseline=baseline,
            min_mrr=args.min_mrr,
            fail_on_required_regression=args.fail_on_required_regression,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
