from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import sys
from html import escape
from pathlib import Path
from typing import Any

from memory_review import golden_candidate_action_guidance
from memorywiki_operator_env import resolve_mcp_python
from memorywiki_project_matrix import load_project_targets, run_project_matrix
from memorywiki_quality_report import run_quality_report
from retrieval_golden_eval import load_cases


def _safe_file(path: str | Path, *, label: str, must_exist: bool = True) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise ValueError(f"{label} must be a real file: {candidate}")
    if must_exist and not candidate.exists():
        raise ValueError(f"{label} is missing: {candidate}")
    if candidate.exists() and not candidate.is_file():
        raise ValueError(f"{label} must be a real file: {candidate}")
    cursor = candidate.parent
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError(f"{label} may not be below a symlink: {cursor}")
    for parent in cursor.parents:
        if parent.is_symlink():
            raise ValueError(f"{label} may not be below a symlink: {parent}")
    return candidate


def _read_release_baseline(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"status": "missing", "path": "", "comparison": {}, "current": {}}
    candidate = _safe_file(path, label="Release manifest", must_exist=False)
    if not candidate.exists():
        return {"status": "missing", "path": str(candidate), "comparison": {}, "current": {}}
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Release manifest must be a JSON object: {candidate}")
    baseline = payload.get("retrieval_baseline", {})
    if not isinstance(baseline, dict):
        baseline = {}
    comparison = baseline.get("comparison", {})
    current = baseline.get("current", {})
    return {
        "status": str(comparison.get("status", "missing")) if isinstance(comparison, dict) else "missing",
        "path": str(candidate),
        "comparison": comparison if isinstance(comparison, dict) else {},
        "current": current if isinstance(current, dict) else {},
    }


def _embedding_readiness() -> dict[str, Any]:
    available = importlib.util.find_spec("sentence_transformers") is not None
    return {
        "status": "available" if available else "not-installed",
        "provider": "sentence-transformers",
        "recommendation": (
            "optional local semantic embedding provider is importable"
            if available
            else "keep using memorywiki-local-hash-v1 until retrieval regressions justify a heavier local dependency"
        ),
    }


def _command(*parts: object) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts if str(part))


def _recommendation(
    *,
    category: str,
    severity: str,
    title: str,
    summary: str,
    command: str = "",
    source: str = "",
    write_required: bool = False,
    approval_required: bool = False,
) -> dict[str, Any]:
    if severity not in {"info", "warn", "fail"}:
        severity = "info"
    return {
        "category": category,
        "severity": severity,
        "title": title,
        "summary": summary,
        "command": command,
        "source": source,
        "write_required": write_required,
        "approval_required": approval_required or write_required,
    }


def _quality_recommendations(
    *,
    quality: dict[str, Any],
    project_root: Path,
    global_root: Path,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    index = quality.get("index", {})
    if index.get("rebuild_needed"):
        affected = [
            item.get("scope", "memory")
            for item in index.get("roots", [])
            if item.get("needs_rebuild")
        ]
        recommendations.append(
            _recommendation(
                category="memory-ops",
                severity="warn",
                title="Refresh stale retrieval sidecars",
                summary="Index maintenance reports stale, missing, or tampered sidecars for: %s."
                % (", ".join(affected) or "memory roots"),
                command=_command(
                    "memory_index_maintain.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--scope",
                    "all",
                    "--write",
                    "--format",
                    "human",
                ),
                source="memorywiki_quality_report.index",
                write_required=True,
            )
        )
    health = quality.get("health", {})
    if health.get("issue_count", 0):
        recommendations.append(
            _recommendation(
                category="memory-ops",
                severity="warn" if health.get("status") != "fail" else "fail",
                title="Review memory health issues",
                summary="{} memory health issues need review before applying repairs.".format(health.get("issue_count", 0)),
                command=_command(
                    "memory_review.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--scope",
                    "all",
                    "--format",
                    "human",
                ),
                source="memorywiki_quality_report.health",
            )
        )
    lifecycle = quality.get("lifecycle", {})
    if lifecycle.get("proposal_count", 0):
        recommendations.append(
            _recommendation(
                category="memory-ops",
                severity="warn",
                title="Review lifecycle ledger proposals",
                summary="{} lifecycle proposals are pending; archive only with explicit write approval.".format(lifecycle.get("proposal_count", 0)),
                command=_command(
                    "memory_lifecycle.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--scope",
                    "all",
                    "--format",
                    "human",
                ),
                source="memorywiki_quality_report.lifecycle",
            )
        )
    return recommendations


def _knowledge_recommendations(
    *,
    quality: dict[str, Any],
    golden_actions: dict[str, Any],
    project_root: Path,
    global_root: Path,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    review = quality.get("review", {})
    if review.get("review_inbox_count", 0):
        recommendations.append(
            _recommendation(
                category="knowledge-formation",
                severity="warn",
                title="Review pending memory formation inbox",
                summary="{} review inbox items need human judgment before writing memory.".format(review.get("review_inbox_count", 0)),
                command=_command(
                    "memory_review.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--scope",
                    "all",
                    "--format",
                    "human",
                ),
                source="memorywiki_quality_report.review",
            )
        )
    for item in golden_actions.get("ready", [])[:5]:
        recommendations.append(
            _recommendation(
                category="knowledge-formation",
                severity="warn",
                title="Promote reviewed golden candidate",
                summary="Pending golden candidate `{}` is ready; review expected targets before writing.".format(item.get("name", "")),
                command=str(item.get("command", "")),
                source="memory_review.golden_candidates",
                write_required=True,
            )
        )
    for item in golden_actions.get("needs_expected", [])[:5]:
        recommendations.append(
            _recommendation(
                category="knowledge-formation",
                severity="warn",
                title="Fill or reject incomplete golden candidate",
                summary="Pending golden candidate `{}` needs an expected target or rejection reason.".format(item.get("name", "")),
                command=str(item.get("command", "")),
                source="memory_review.golden_candidates",
                write_required=True,
            )
        )
    return recommendations


def _retrieval_recommendations(
    *,
    quality: dict[str, Any],
    release_baseline: dict[str, Any],
    embedding: dict[str, Any],
    project_root: Path,
    global_root: Path,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    golden = quality.get("golden_eval", {})
    golden_status = golden.get("status", "")
    if golden_status in {"fail", "warn"} or golden.get("required_failed", 0):
        recommendations.append(
            _recommendation(
                category="retrieval-quality",
                severity="fail" if golden.get("required_failed", 0) else "warn",
                title="Investigate retrieval golden regression",
                summary="Golden eval status is `{}` with {} required failures.".format(golden_status, golden.get("required_failed", 0)),
                command=_command(
                    "retrieval_golden_eval.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--case-file",
                    Path(__file__).resolve().parent / "docs" / "memorywiki-golden-cases.json",
                    "--format",
                    "human",
                ),
                source="memorywiki_quality_report.golden_eval",
            )
        )
    elif golden_status == "skipped":
        recommendations.append(
            _recommendation(
                category="retrieval-quality",
                severity="info",
                title="Run golden eval before retrieval changes",
                summary="Golden eval was skipped; run it before changing recall ranking or embeddings.",
                command=_command(
                    "retrieval_golden_eval.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--case-file",
                    Path(__file__).resolve().parent / "docs" / "memorywiki-golden-cases.json",
                    "--format",
                    "human",
                ),
                source="memorywiki_quality_report.golden_eval",
            )
        )
    release_status = release_baseline.get("status", "")
    if release_status in {"warn", "fail"}:
        recommendations.append(
            _recommendation(
                category="retrieval-quality",
                severity="fail" if release_status == "fail" else "warn",
                title="Compare release retrieval baseline",
                summary=f"Previous release baseline reports `{release_status}`; inspect rank deltas before release.",
                command=_command(
                    "retrieval_golden_eval.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--case-file",
                    Path(__file__).resolve().parent / "docs" / "memorywiki-golden-cases.json",
                    "--format",
                    "human",
                ),
                source="release_baseline",
            )
        )
    if embedding.get("status") == "not-installed" and golden_status in {"fail", "warn"}:
        recommendations.append(
            _recommendation(
                category="retrieval-quality",
                severity="info",
                title="Keep sentence-transformers as a probe",
                summary="Do not install heavier embeddings unless golden regressions persist after lexical/graph fixes.",
                command=_command(
                    "memory_recall.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--scope",
                    "all",
                    "--query",
                    "<debug-query>",
                    "--strategy",
                    "hybrid",
                    "--embedding",
                    "local",
                    "--graph",
                    "local",
                    "--explain-score",
                    "--format",
                    "json",
                ),
                source="embedding_readiness",
            )
        )
    return recommendations


def _project_matrix_recommendations(
    *,
    project_matrix: dict[str, Any] | None,
    global_root: Path,
    python: str,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    if not project_matrix:
        return recommendations
    for row in project_matrix.get("projects", [])[:10]:
        if row.get("status") == "ok":
            continue
        project_name = str(row.get("name", "project"))
        project_path = Path(str(row.get("path", ""))).expanduser()
        project_memory = Path(str(row.get("project_root", project_path / ".agent_memory" / "project")))
        index = row.get("index", {})
        if index.get("rebuild_needed"):
            recommendations.append(
                _recommendation(
                    category="cross-project-reliability",
                    severity="warn",
                    title=f"Refresh {project_name} project index",
                    summary=f"{project_name} has stale, missing, or tampered project retrieval sidecars.",
                    command=_command(
                        "memory_index_maintain.py",
                        "--project-root",
                        project_memory,
                        "--global-root",
                        global_root,
                        "--scope",
                        "project",
                        "--write",
                        "--format",
                        "human",
                    ),
                    source="memorywiki_project_matrix.index",
                    write_required=True,
                )
            )
        doctor = row.get("doctor", {})
        if doctor.get("status") in {"warn", "fail"}:
            recommendations.append(
                _recommendation(
                    category="cross-project-reliability",
                    severity="fail" if doctor.get("status") == "fail" else "warn",
                    title=f"Diagnose {project_name} MemoryWiki bridge",
                    summary="{} MCP bridge doctor reports `{}`.".format(project_name, doctor.get("status")),
                    command=_command(
                        "memorywiki_mcp_doctor.py",
                        "--python",
                        python,
                        "--project-root",
                        project_memory,
                        "--global-root",
                        global_root,
                        "--config",
                        project_path / ".mcp.json",
                        "--format",
                        "human",
                    ),
                    source="memorywiki_project_matrix.doctor",
                )
            )
        golden = row.get("golden_eval", {})
        if golden.get("status") not in {"pass", None}:
            recommendations.append(
                _recommendation(
                    category="cross-project-reliability",
                    severity="fail" if golden.get("status") == "fail" else "warn",
                    title=f"Investigate {project_name} project golden eval",
                    summary="{} project golden eval status is `{}`.".format(project_name, golden.get("status")),
                    command=_command(
                        "retrieval_golden_eval.py",
                        "--project-root",
                        project_memory,
                        "--global-root",
                        global_root,
                        "--format",
                        "human",
                    ),
                    source="memorywiki_project_matrix.golden_eval",
                )
            )
        coverage = row.get("case_coverage", {})
        if coverage.get("status") == "warn":
            recommendations.append(
                _recommendation(
                    category="cross-project-reliability",
                    severity="warn",
                    title=f"Adjust {project_name} project golden coverage",
                    summary=str(coverage.get("message", "")),
                    command="",
                    source="memorywiki_project_matrix.case_coverage",
                )
            )
    return recommendations


def _release_recommendations(
    *,
    release_baseline: dict[str, Any],
    project_root: Path,
    global_root: Path,
    project_matrix_config: str | Path | None,
    release_manifest: str | Path | None,
) -> list[dict[str, Any]]:
    status = release_baseline.get("status", "")
    if status in {"ok"}:
        return []
    command_parts: list[object] = [
        "memorywiki_release_check.py",
        "--project-root",
        project_root,
        "--global-root",
        global_root,
        "--config",
        Path.cwd() / ".mcp.json",
        "--skip-smoke",
        "--format",
        "human",
    ]
    if project_matrix_config:
        command_parts.extend(["--project-matrix-config", Path(project_matrix_config).expanduser()])
    if release_manifest and Path(release_manifest).expanduser().exists():
        command_parts.extend(["--ops-release-manifest", Path(release_manifest).expanduser()])
    summary = (
        "No previous release baseline was provided; run release checks before checkpointing."
        if status in {"", "missing"}
        else f"Release baseline status is `{status}`; include it in the next checkpoint review."
    )
    return [
        _recommendation(
            category="release-discipline",
            severity="warn" if status != "fail" else "fail",
            title="Run MemoryWiki release discipline before checkpoint",
            summary=summary,
            command=_command(*command_parts),
            source="release_baseline",
        )
    ]


def _build_recommendations(
    *,
    quality: dict[str, Any],
    project_matrix: dict[str, Any] | None,
    release_baseline: dict[str, Any],
    embedding: dict[str, Any],
    golden_actions: dict[str, Any],
    project_root: Path,
    global_root: Path,
    project_matrix_config: str | Path | None,
    release_manifest: str | Path | None,
    python: str,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    items.extend(
        _quality_recommendations(
            quality=quality,
            project_root=project_root,
            global_root=global_root,
        )
    )
    items.extend(
        _knowledge_recommendations(
            quality=quality,
            golden_actions=golden_actions,
            project_root=project_root,
            global_root=global_root,
        )
    )
    items.extend(
        _retrieval_recommendations(
            quality=quality,
            release_baseline=release_baseline,
            embedding=embedding,
            project_root=project_root,
            global_root=global_root,
        )
    )
    items.extend(
        _project_matrix_recommendations(
            project_matrix=project_matrix,
            global_root=global_root,
            python=python,
        )
    )
    items.extend(
        _release_recommendations(
            release_baseline=release_baseline,
            project_root=project_root,
            global_root=global_root,
            project_matrix_config=project_matrix_config,
            release_manifest=release_manifest,
        )
    )
    by_category: dict[str, int] = {}
    for item in items:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
    return {
        "status": "fail"
        if any(item["severity"] == "fail" for item in items)
        else "review"
        if items
        else "ok",
        "count": len(items),
        "by_category": by_category,
        "items": items,
    }


def _status_from_sections(
    *,
    quality: dict[str, Any],
    project_matrix: dict[str, Any] | None,
    release_baseline: dict[str, Any],
    recommendations: dict[str, Any] | None = None,
) -> str:
    statuses = [quality.get("status", "ok"), release_baseline.get("status", "ok")]
    if project_matrix:
        statuses.append(project_matrix.get("status", "ok"))
    if recommendations:
        statuses.append(recommendations.get("status", "ok"))
    if "fail" in statuses:
        return "fail"
    if any(status in {"missing", "review", "warn"} for status in statuses):
        return "review"
    return "ok"


def run_ops_dashboard(
    *,
    project_root: str | Path,
    global_root: str | Path,
    project_matrix_config: str | Path | None = None,
    release_manifest: str | Path | None = None,
    period: str = "daily",
    python: str | Path | None = None,
    mcp_config: str | Path | None = None,
    skip_project_matrix: bool = False,
    skip_golden: bool = False,
) -> dict[str, Any]:
    project_root = Path(project_root).expanduser()
    global_root = Path(global_root).expanduser()
    python_resolution = resolve_mcp_python(
        mcp_config=mcp_config,
        fallback=python or sys.executable,
    )
    resolved_python = str(python_resolution["python"])
    cases = None if skip_golden else load_cases(project_root=project_root)
    quality = run_quality_report(
        project_root=project_root,
        global_root=global_root,
        scope="all",
        golden_cases=cases,
        skip_golden=skip_golden,
    )
    matrix = None
    if not skip_project_matrix and project_matrix_config:
        matrix_config = _safe_file(project_matrix_config, label="Project matrix config")
        matrix = run_project_matrix(
            projects=load_project_targets(matrix_config),
            memory_system_home=Path(__file__).resolve().parent,
            python=resolved_python,
            global_root=global_root,
            install=False,
            update_existing_agents=False,
            write_indexes=False,
            smoke=False,
        )
    release = _read_release_baseline(release_manifest)
    registry = Path(__file__).resolve().parent / "docs" / "memorywiki-golden-cases.json"
    base_command = [
        "memorywiki_ops_dashboard.py",
        "--project-root",
        project_root,
        "--global-root",
        global_root,
    ]
    if project_matrix_config:
        base_command.extend(["--project-matrix-config", Path(project_matrix_config).expanduser()])
    if release_manifest:
        base_command.extend(["--release-manifest", Path(release_manifest).expanduser()])
    if mcp_config:
        base_command.extend(["--mcp-config", Path(mcp_config).expanduser()])
    golden_actions = golden_candidate_action_guidance(
        backlog=quality["golden_candidates"],
        project_root=project_root,
        global_root=global_root,
        golden_case_registry=registry,
    )
    actions = {
        "golden_candidates": golden_actions,
        "daily_command": _command(*base_command, "--period", "daily", "--format", "markdown"),
        "weekly_command": _command(*base_command, "--period", "weekly", "--format", "markdown"),
    }
    embedding = _embedding_readiness()
    recommendations = _build_recommendations(
        quality=quality,
        project_matrix=matrix,
        release_baseline=release,
        embedding=embedding,
        golden_actions=golden_actions,
        project_root=project_root,
        global_root=global_root,
        project_matrix_config=project_matrix_config,
        release_manifest=release_manifest,
        python=resolved_python,
    )
    payload = {
        "status": _status_from_sections(
            quality=quality,
            project_matrix=matrix,
            release_baseline=release,
            recommendations=recommendations,
        ),
        "period": period if period in {"daily", "weekly"} else "daily",
        "read_only": True,
        "quality": quality,
        "project_matrix": matrix,
        "release_baseline": release,
        "embedding_readiness": embedding,
        "operator": {
            "python": resolved_python,
            "python_source": python_resolution["source"],
            "mcp_config": python_resolution["mcp_config"],
            "python_warning": python_resolution["warning"],
        },
        "recommendations": recommendations,
        "actions": actions,
    }
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    quality = payload["quality"]
    golden = quality.get("golden_eval", {})
    candidates = quality.get("golden_candidates", {})
    lines = [
        "# MemoryWiki Ops Dashboard",
        "",
        "- Status: `{}`".format(payload["status"]),
        "- Period: `{}`".format(payload["period"]),
        "- Read-only: `%s`" % ("yes" if payload["read_only"] else "no"),
        "- Quality: `{}`, health issues `{}`, review inbox `{}`, lifecycle proposals `{}`".format(
            quality.get("status", ""),
            quality.get("health", {}).get("issue_count", 0),
            quality.get("review", {}).get("review_inbox_count", 0),
            quality.get("lifecycle", {}).get("proposal_count", 0),
        ),
        "- Golden eval: `{}`, pass `{}/{}`, required failed `{}`, MRR `{}`".format(
            golden.get("status", ""),
            golden.get("passed", 0),
            golden.get("total", 0),
            golden.get("required_failed", 0),
            "{:.3f}".format(golden.get("mean_reciprocal_rank", 0.0))
            if isinstance(golden.get("mean_reciprocal_rank"), (int, float))
            else "n/a",
        ),
        "- Golden candidates: `{}` ready / `{}` total".format(candidates.get("ready_count", 0), candidates.get("candidate_count", 0)),
        "- Release baseline: `{}`".format(payload.get("release_baseline", {}).get("status", "")),
        "- Embedding readiness: `{}`".format(payload.get("embedding_readiness", {}).get("status", "")),
        "- MCP Python: `{}` ({})".format(
            payload.get("operator", {}).get("python", ""),
            payload.get("operator", {}).get("python_source", ""),
        ),
        "",
        "## Recommended Actions",
    ]
    recommendations = payload.get("recommendations", {})
    for item in recommendations.get("items", [])[:15]:
        suffix = "write approval required" if item.get("write_required") else "read-only"
        command = item.get("command", "")
        lines.append(
            "- [{severity}] {category}: {title} ({suffix})".format(
                severity=item.get("severity", ""),
                category=item.get("category", ""),
                title=item.get("title", ""),
                suffix=suffix,
            )
        )
        if item.get("summary"):
            lines.append("  Summary: {}".format(item.get("summary", "")))
        if command:
            lines.append(f"  Command ({suffix}): `{command}`")
    if not recommendations.get("items"):
        lines.append("- No recommended action.")
    lines.extend(
        [
            "",
            "## Golden Candidate Actions",
        ]
    )
    actions = payload.get("actions", {}).get("golden_candidates", {})
    for item in actions.get("ready", []):
        lines.append("- Promote `{name}` (write approval required): `{command}`".format(**item))
    for item in actions.get("needs_expected", []):
        lines.append("- Fill `{name}` (write approval required): `{command}`".format(**item))
    if not actions.get("ready") and not actions.get("needs_expected"):
        lines.append("- No pending golden candidate action.")
    lines.extend(["", "## Project Matrix"])
    matrix = payload.get("project_matrix")
    if matrix:
        lines.append("| Project | Status | Cases | Golden |")
        lines.append("|---|---|---:|---|")
        for row in matrix.get("projects", []):
            coverage = row.get("case_coverage", {})
            golden_eval = row.get("golden_eval", {})
            lines.append(
                "| {name} | {status} | {cases} | {golden} |".format(
                    name=row.get("name", ""),
                    status=row.get("status", ""),
                    cases=coverage.get("case_count", 0),
                    golden=golden_eval.get("status", ""),
                )
            )
    else:
        lines.append("- Project matrix skipped.")
    lines.extend(["", "## Next Read-Only Reports"])
    lines.append("- Daily: `{}`".format(payload.get("actions", {}).get("daily_command", "")))
    lines.append("- Weekly: `{}`".format(payload.get("actions", {}).get("weekly_command", "")))
    return "\n".join(lines).rstrip() + "\n"


def render_html(payload: dict[str, Any]) -> str:
    markdown = render_markdown(payload)
    paragraphs = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            paragraphs.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            paragraphs.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("- "):
            paragraphs.append(f"<p>{escape(line[2:])}</p>")
        elif line.startswith("|"):
            paragraphs.append(f"<pre>{escape(line)}</pre>")
        elif line.strip():
            paragraphs.append(f"<p>{escape(line)}</p>")
    return "<!doctype html>\n<html><body>\n{}\n</body></html>\n".format("\n".join(paragraphs))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a read-only MemoryWiki ops dashboard.")
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--project-matrix-config")
    parser.add_argument("--release-manifest")
    parser.add_argument("--period", choices=("daily", "weekly"), default="daily")
    parser.add_argument("--python", default=None)
    parser.add_argument(
        "--mcp-config",
        default=str(Path.cwd() / ".mcp.json"),
        help="Read the memorywiki-memory command from this config to reuse the MCP Python runtime.",
    )
    parser.add_argument("--skip-project-matrix", action="store_true")
    parser.add_argument("--skip-golden", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown", "html"), default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_ops_dashboard(
            project_root=args.project_root,
            global_root=args.global_root,
            project_matrix_config=args.project_matrix_config,
            release_manifest=args.release_manifest,
            period=args.period,
            python=args.python,
            mcp_config=args.mcp_config,
            skip_project_matrix=args.skip_project_matrix,
            skip_golden=args.skip_golden,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "html":
        print(render_html(payload), end="")
    else:
        print(render_markdown(payload), end="")
    return 0 if payload["status"] in {"ok", "review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
