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
        expected=["memorywiki-overview", "memorywiki-pkm-positioning"],
        min_rank=3,
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="memorywiki-pkm-positioning",
        query="MemoryWiki local-first chat memory personal knowledge management source ingest crystallize",
        expected=["memorywiki-pkm-positioning"],
        min_rank=3,
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="source-ingest-provenance",
        query="MemoryWiki source ingest SHA256 provenance tamper evidence",
        expected=["source-ingest-provenance", "source-sha256"],
        min_rank=3,
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="lifecycle-governance",
        query="MemoryWiki lifecycle review stale weak memory archival governance",
        expected=["lifecycle-governance", "memory-lifecycle"],
        min_rank=3,
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="cross-project-recall",
        query="MemoryWiki cross project recall MCP startup bridge",
        expected=["cross-project-recall", "memorywiki-mcp"],
        min_rank=3,
        owner="memorywiki",
        project="global",
    ),
    RetrievalCase(
        name="privacy-public-clean",
        query="MemoryWiki public release privacy scan private path marker cleanup",
        expected=["privacy-public-clean"],
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
        ranker="rrf",
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
    rank_ok = (
        found
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
        )
        for case in selected
    ]
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
    return {
        "status": "pass" if pass_rate >= min_pass_rate and required_failed == 0 else "fail",
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
        "strategy": strategy,
        "embedding": embedding,
        "graph": graph,
        "cases": case_results,
    }


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
        "",
    ]
    for case in payload["cases"]:
        marker = "PASS" if case["passed"] else "FAIL"
        rank = case.get("rank")
        rank_text = f"rank {rank}" if rank else case.get("failure_reason", "no match")
        lines.append(
            "- [{}] {}{} -> {} ({})".format(
                marker,
                case["name"],
                "" if case.get("required", True) else " optional",
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
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--token-budget", type=int, default=1200)
    parser.add_argument("--strategy", choices=("live", "indexed", "hybrid"), default="hybrid")
    parser.add_argument("--embedding", choices=("off", "local"), default="local")
    parser.add_argument("--graph", choices=("off", "local"), default="local")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cases = load_cases(args.case_file, project_root=args.project_root)
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
