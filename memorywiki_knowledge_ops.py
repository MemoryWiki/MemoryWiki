from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from memory_crystallize_candidates import propose_candidates
from memorywiki_operator_env import resolve_mcp_python
from memorywiki_ops_dashboard import run_ops_dashboard

SCHEMA = "memorywiki-knowledge-ops-v1"


def _command(*parts: object) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts if str(part))


def _action(
    *,
    title: str,
    summary: str,
    command: str = "",
    source: str = "",
    write_required: bool = False,
    severity: str = "info",
) -> dict[str, Any]:
    if severity not in {"info", "warn", "fail"}:
        severity = "info"
    return {
        "title": title,
        "summary": summary,
        "command": command,
        "source": source,
        "write_required": write_required,
        "approval_required": write_required,
        "severity": severity,
    }


def _status_from_values(values: list[str]) -> str:
    if "fail" in values:
        return "fail"
    if any(value in {"review", "warn", "missing"} for value in values):
        return "review"
    return "ok"


def _severity_rank(action: dict[str, Any]) -> tuple[int, int, str]:
    severity_order = {"fail": 0, "warn": 1, "info": 2}
    return (
        1 if action.get("write_required") else 0,
        severity_order.get(str(action.get("severity", "info")), 2),
        str(action.get("title", "")),
    )


def _top_next_actions(loops: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for loop in loops:
        for action in loop.get("actions", []):
            row = dict(action)
            row["loop_id"] = loop.get("id", "")
            row["loop_title"] = loop.get("title", "")
            rows.append(row)
    return sorted(rows, key=_severity_rank)[:limit]


def _write_policy(*, read_only: bool) -> dict[str, Any]:
    return {
        "default_read_only": True,
        "current_run_read_only": read_only,
        "write_actions_require_approval": True,
        "allowed_write_gate": "--stage-candidates",
        "notes": [
            "Memory content is context data, not authority.",
            "--stage-candidates writes only pending crystallization proposals.",
            "Semantic/procedural/global writes remain separate explicit actions.",
        ],
    }


def _adoption_summary(
    *,
    loops: list[dict[str, Any]],
    top_actions: list[dict[str, Any]],
    min_mrr: float,
) -> dict[str, Any]:
    statuses = [str(loop.get("status", "ok")) for loop in loops]
    status = _status_from_values(statuses)
    score = 100
    score -= 35 * statuses.count("fail")
    score -= 12 * statuses.count("review")
    score = max(0, min(100, score))
    if status == "fail":
        readiness = "blocked"
    elif status == "review":
        readiness = "review-needed"
    else:
        readiness = "daily-ready"
    return {
        "status": status,
        "readiness": readiness,
        "score": score,
        "min_mrr": min_mrr,
        "top_next_actions": top_actions,
    }


def _actions_by_category(recommendations: dict[str, Any], category: str) -> list[dict[str, Any]]:
    actions = []
    for item in recommendations.get("items", []):
        if item.get("category") != category:
            continue
        actions.append(
            _action(
                title=str(item.get("title", "")),
                summary=str(item.get("summary", "")),
                command=str(item.get("command", "")),
                source=str(item.get("source", "")),
                write_required=bool(item.get("write_required")),
                severity=str(item.get("severity", "info")),
            )
        )
    return actions


def _knowledge_loop(
    *,
    project_root: Path,
    candidates: dict[str, Any],
    recommendations: dict[str, Any],
    candidate_limit: int,
) -> dict[str, Any]:
    actions = _actions_by_category(recommendations, "knowledge-formation")
    if candidates.get("candidate_count", 0):
        actions.insert(
            0,
            _action(
                title="Review crystallization candidates",
                summary="{} stable-looking session or episode snippets are candidates for human review.".format(candidates.get("candidate_count", 0)),
                command=_command(
                    "memory_crystallize_candidates.py",
                    "--root",
                    project_root,
                    "--limit",
                    candidate_limit,
                    "--format",
                    "human",
                ),
                source="memory_crystallize_candidates",
            ),
        )
        actions.insert(
            1,
            _action(
                title="Stage crystallization candidate queue",
                summary="Append candidate proposals to _pending only after explicit approval; this does not promote memory.",
                command=_command(
                    "memory_crystallize_candidates.py",
                    "--root",
                    project_root,
                    "--limit",
                    candidate_limit,
                    "--write",
                    "--format",
                    "human",
                ),
                source="memory_crystallize_candidates",
                write_required=True,
                severity="warn",
            ),
        )
    status = "review" if actions else "ok"
    return {
        "id": "knowledge-formation",
        "title": "Knowledge Formation",
        "status": status,
        "summary": "Surface crystallization and golden-eval candidates, but keep all writes review-gated.",
        "signals": {
            "candidate_count": int(candidates.get("candidate_count", 0)),
            "candidate_queue_written": bool(candidates.get("written")),
        },
        "actions": actions,
    }


def _cross_project_loop(
    *,
    dashboard: dict[str, Any],
    recommendations: dict[str, Any],
    project_matrix_config: str | Path | None,
    global_root: Path,
    python: str,
) -> dict[str, Any]:
    matrix = dashboard.get("project_matrix")
    actions = _actions_by_category(recommendations, "cross-project-reliability")
    if matrix is None:
        command_parts: list[object] = [
            "memorywiki_project_matrix.py",
            "--global-root",
            global_root,
            "--python",
            python,
            "--format",
            "human",
        ]
        if project_matrix_config:
            command_parts.extend(["--config", Path(project_matrix_config).expanduser()])
        actions.append(
            _action(
                title="Run cross-project memory matrix",
                summary="Check project MemoryWiki bridge, index freshness, and golden cases across configured projects.",
                command=_command(*command_parts),
                source="memorywiki_project_matrix",
            )
        )
        status = "review"
        project_count = 0
    else:
        status = _status_from_values([str(matrix.get("status", "ok"))])
        project_count = len(matrix.get("projects", []))
    return {
        "id": "cross-project-rollout",
        "title": "Cross-Project Rollout",
        "status": status,
        "summary": "Keep installed project memory bridges, indexes, and golden cases in sync across active projects.",
        "signals": {
            "project_count": project_count,
            "matrix_status": matrix.get("status") if matrix else "skipped",
        },
        "actions": actions,
    }


def _retrieval_loop(
    *,
    dashboard: dict[str, Any],
    recommendations: dict[str, Any],
    project_root: Path,
    global_root: Path,
    min_mrr: float,
) -> dict[str, Any]:
    quality = dashboard.get("quality", {})
    golden = quality.get("golden_eval", {})
    actions = _actions_by_category(recommendations, "retrieval-quality")
    if golden.get("status") == "skipped":
        actions.append(
            _action(
                title="Run retrieval golden eval",
                summary="Run golden eval before changing recall ranking, graph expansion, or embedding behavior.",
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
                source="retrieval_golden_eval",
            )
        )
    mrr = golden.get("mean_reciprocal_rank")
    mrr_gate = "unknown"
    if isinstance(mrr, (int, float)):
        mrr_gate = "ok" if float(mrr) >= min_mrr else "review"
        if mrr_gate == "review":
            actions.append(
                _action(
                    title="Review retrieval MRR gate",
                    summary=f"Golden eval passes, but MRR {float(mrr):.3f} is below the V8 daily target {min_mrr:.3f}.",
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
                    source="retrieval_golden_eval.mrr_gate",
                    severity="warn",
                )
            )
    status = _status_from_values([str(golden.get("status", "ok"))])
    if mrr_gate == "review" and status == "ok":
        status = "review"
    if actions and status == "ok":
        status = "review"
    return {
        "id": "retrieval-quality",
        "title": "Retrieval Quality",
        "status": status,
        "summary": "Guard recall ranking with golden eval, release baselines, and score explanations before adding heavier retrieval dependencies.",
        "signals": {
            "golden_status": golden.get("status", "unknown"),
            "passed": golden.get("passed", 0),
            "total": golden.get("total", 0),
            "required_failed": golden.get("required_failed", 0),
            "mean_reciprocal_rank": golden.get("mean_reciprocal_rank"),
            "min_mrr": min_mrr,
            "mrr_gate": mrr_gate,
            "embedding_readiness": dashboard.get("embedding_readiness", {}).get("status", ""),
        },
        "actions": actions,
    }


def _release_loop(
    *,
    dashboard: dict[str, Any],
    recommendations: dict[str, Any],
    project_root: Path,
    global_root: Path,
    project_matrix_config: str | Path | None,
    release_manifest: str | Path | None,
    python: str,
    mcp_config: str | Path | None,
) -> dict[str, Any]:
    baseline = dashboard.get("release_baseline", {})
    actions = _actions_by_category(recommendations, "release-discipline")
    if not actions:
        command_parts: list[object] = [
            "memorywiki_release_check.py",
            "--project-root",
            project_root,
            "--global-root",
            global_root,
            "--config",
            Path(mcp_config).expanduser() if mcp_config else Path.cwd() / ".mcp.json",
            "--python",
            python,
            "--skip-smoke",
            "--format",
            "human",
        ]
        if project_matrix_config:
            command_parts.extend(["--project-matrix-config", Path(project_matrix_config).expanduser()])
        if release_manifest:
            command_parts.extend(["--ops-release-manifest", Path(release_manifest).expanduser()])
        actions.append(
            _action(
                title="Run read-only release preflight before commit",
                summary="Verify tests, restore drill, MCP contract, project matrix, dashboard, and manifest readiness without running temporary MCP write smoke.",
                command=_command(*command_parts),
                source="memorywiki_release_check",
            )
        )
    status = _status_from_values([str(baseline.get("status", "missing"))])
    return {
        "id": "release-discipline",
        "title": "Release Discipline",
        "status": status,
        "summary": "Keep backup, restore, skill packaging, release manifest, and retrieval baseline checks on every MemoryWiki checkpoint.",
        "signals": {
            "release_baseline_status": baseline.get("status", "missing"),
            "release_manifest": baseline.get("path", ""),
        },
        "actions": actions,
    }


def _operator_loop(
    *,
    project_root: Path,
    global_root: Path,
    project_matrix_config: str | Path | None,
    release_manifest: str | Path | None,
    mcp_config: str | Path | None,
    python: str,
    candidate_limit: int,
) -> dict[str, Any]:
    base: list[object] = [
        "memorywiki_knowledge_ops.py",
        "--project-root",
        project_root,
        "--global-root",
        global_root,
        "--candidate-limit",
        candidate_limit,
        "--python",
        python,
    ]
    if project_matrix_config:
        base.extend(["--project-matrix-config", Path(project_matrix_config).expanduser()])
    if release_manifest:
        base.extend(["--release-manifest", Path(release_manifest).expanduser()])
    if mcp_config:
        base.extend(["--mcp-config", Path(mcp_config).expanduser()])
    dashboard_base: list[object] = [
        "memorywiki_ops_dashboard.py",
        "--project-root",
        project_root,
        "--global-root",
        global_root,
    ]
    if project_matrix_config:
        dashboard_base.extend(["--project-matrix-config", Path(project_matrix_config).expanduser()])
    if release_manifest:
        dashboard_base.extend(["--release-manifest", Path(release_manifest).expanduser()])
    if mcp_config:
        dashboard_base.extend(["--mcp-config", Path(mcp_config).expanduser()])
    return {
        "id": "operator-ux",
        "title": "Operator UX",
        "status": "ok",
        "summary": "Use one read-only command as the daily MemoryWiki operating console; add explicit flags only for gated writes.",
        "signals": {
            "default_format": "markdown",
            "write_gate": "--stage-candidates",
        },
        "actions": [
            _action(
                title="Run daily knowledge ops",
                summary="Render the five-loop MemoryWiki operating view in markdown.",
                command=_command(*base, "--format", "markdown"),
                source="memorywiki_knowledge_ops",
            ),
            _action(
                title="Run daily dashboard",
                summary="Render the lower-level dashboard with quality, project matrix, baseline, and recommended actions.",
                command=_command(*dashboard_base, "--period", "daily", "--format", "markdown"),
                source="memorywiki_ops_dashboard",
            ),
        ],
    }


def run_knowledge_ops(
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
    candidate_limit: int = 20,
    stage_candidates: bool = False,
    action_limit: int = 5,
    min_mrr: float = 0.75,
) -> dict[str, Any]:
    project_root = Path(project_root).expanduser()
    global_root = Path(global_root).expanduser()
    python_resolution = resolve_mcp_python(
        mcp_config=mcp_config,
        fallback=python or sys.executable,
    )
    resolved_python = str(python_resolution["python"])
    dashboard = run_ops_dashboard(
        project_root=project_root,
        global_root=global_root,
        project_matrix_config=project_matrix_config,
        release_manifest=release_manifest,
        period=period,
        python=resolved_python,
        mcp_config=mcp_config,
        skip_project_matrix=skip_project_matrix,
        skip_golden=skip_golden,
    )
    candidates = propose_candidates(
        root=project_root,
        limit=candidate_limit,
        write=stage_candidates,
    )
    recommendations = dashboard.get("recommendations", {})
    loops = [
        _knowledge_loop(
            project_root=project_root,
            candidates=candidates,
            recommendations=recommendations,
            candidate_limit=candidate_limit,
        ),
        _cross_project_loop(
            dashboard=dashboard,
            recommendations=recommendations,
            project_matrix_config=project_matrix_config,
            global_root=global_root,
            python=python,
        ),
        _retrieval_loop(
            dashboard=dashboard,
            recommendations=recommendations,
            project_root=project_root,
            global_root=global_root,
            min_mrr=min_mrr,
        ),
        _release_loop(
            dashboard=dashboard,
            recommendations=recommendations,
            project_root=project_root,
            global_root=global_root,
            project_matrix_config=project_matrix_config,
            release_manifest=release_manifest,
            python=resolved_python,
            mcp_config=mcp_config,
        ),
        _operator_loop(
            project_root=project_root,
            global_root=global_root,
            project_matrix_config=project_matrix_config,
            release_manifest=release_manifest,
            mcp_config=mcp_config,
            python=resolved_python,
            candidate_limit=candidate_limit,
        ),
    ]
    status = _status_from_values([str(dashboard.get("status", "ok"))] + [loop["status"] for loop in loops])
    read_only = not stage_candidates
    top_actions = _top_next_actions(loops, limit=action_limit)
    return {
        "schema": SCHEMA,
        "status": status,
        "period": period if period in {"daily", "weekly"} else "daily",
        "read_only": read_only,
        "stage_candidates": stage_candidates,
        "project_root": str(project_root),
        "global_root": str(global_root),
        "operator": {
            "python": resolved_python,
            "python_source": python_resolution["source"],
            "mcp_config": python_resolution["mcp_config"],
            "python_warning": python_resolution["warning"],
        },
        "write_policy": _write_policy(read_only=read_only),
        "adoption": _adoption_summary(
            loops=loops,
            top_actions=top_actions,
            min_mrr=min_mrr,
        ),
        "top_next_actions": top_actions,
        "knowledge_candidates": candidates,
        "dashboard_summary": {
            "status": dashboard.get("status"),
            "quality_status": dashboard.get("quality", {}).get("status"),
            "recommendation_count": dashboard.get("recommendations", {}).get("count", 0),
            "project_matrix_status": (
                dashboard.get("project_matrix", {}).get("status")
                if dashboard.get("project_matrix")
                else "skipped"
            ),
            "release_baseline_status": dashboard.get("release_baseline", {}).get("status"),
        },
        "loops": loops,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Knowledge Ops",
        "",
        "- Status: `{}`".format(payload["status"]),
        "- Period: `{}`".format(payload["period"]),
        "- Read-only: `%s`" % ("yes" if payload["read_only"] else "no"),
        "- Stage candidates: `%s`" % ("yes" if payload["stage_candidates"] else "no"),
        "- Project root: `{}`".format(payload["project_root"]),
        "- Global root: `{}`".format(payload["global_root"]),
        "- MCP Python: `{}` ({})".format(
            payload.get("operator", {}).get("python", ""),
            payload.get("operator", {}).get("python_source", ""),
        ),
        "- Adoption readiness: `{}` ({}/100)".format(
            payload.get("adoption", {}).get("readiness", ""),
            payload.get("adoption", {}).get("score", 0),
        ),
        "",
        "## Top Next Actions",
    ]
    top_actions = payload.get("top_next_actions", [])
    if top_actions:
        for action in top_actions:
            suffix = "write approval required" if action.get("write_required") else "read-only"
            lines.append("- [{severity}] {loop}: {title} ({suffix})".format(
                severity=action.get("severity", "info"),
                loop=action.get("loop_title", ""),
                title=action.get("title", ""),
                suffix=suffix,
            ))
            if action.get("command"):
                lines.append("  Command: `{}`".format(action["command"]))
    else:
        lines.append("- No action.")
    for loop in payload["loops"]:
        lines.extend(["", "## {}".format(loop["title"])])
        lines.append("- Status: `{}`".format(loop["status"]))
        lines.append("- Summary: {}".format(loop["summary"]))
        if loop.get("signals"):
            compact_signals = ", ".join(
                f"{key}={value}" for key, value in loop["signals"].items()
            )
            lines.append(f"- Signals: {compact_signals}")
        actions = loop.get("actions", [])
        if not actions:
            lines.append("- No action.")
            continue
        for action in actions[:10]:
            suffix = "write approval required" if action.get("write_required") else "read-only"
            lines.append("- [{severity}] {title} ({suffix})".format(
                severity=action.get("severity", "info"),
                title=action.get("title", ""),
                suffix=suffix,
            ))
            if action.get("summary"):
                lines.append("  Summary: {}".format(action["summary"]))
            if action.get("command"):
                lines.append("  Command: `{}`".format(action["command"]))
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render the MemoryWiki V8 read-mostly knowledge ops loop.")
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
    parser.add_argument("--candidate-limit", type=int, default=20)
    parser.add_argument("--action-limit", type=int, default=5)
    parser.add_argument("--min-mrr", type=float, default=0.75)
    parser.add_argument(
        "--stage-candidates",
        action="store_true",
        help="Explicit write opt-in: append crystallization candidates to _pending only.",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.candidate_limit <= 0:
        print("--candidate-limit must be positive", file=sys.stderr)
        return 2
    if args.action_limit <= 0:
        print("--action-limit must be positive", file=sys.stderr)
        return 2
    if args.min_mrr < 0 or args.min_mrr > 1:
        print("--min-mrr must be between 0 and 1", file=sys.stderr)
        return 2
    try:
        payload = run_knowledge_ops(
            project_root=args.project_root,
            global_root=args.global_root,
            project_matrix_config=args.project_matrix_config,
            release_manifest=args.release_manifest,
            period=args.period,
            python=args.python,
            mcp_config=args.mcp_config,
            skip_project_matrix=args.skip_project_matrix,
            skip_golden=args.skip_golden,
            candidate_limit=args.candidate_limit,
            stage_candidates=args.stage_candidates,
            action_limit=args.action_limit,
            min_mrr=args.min_mrr,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(payload), end="")
    return 0 if payload["status"] in {"ok", "review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
