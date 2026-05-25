from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from memory_health import run_health
from memory_index_maintain import maintain_indexes
from memory_lifecycle import run_lifecycle
from memory_review import (
    load_feedback_rows,
    run_review,
    summarize_golden_candidate_backlog,
)
from memory_system.models import ProceduralMemory, SemanticMemory
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore
from retrieval_golden_eval import RetrievalCase, load_cases, run_golden_eval

DEFAULT_REVIEW_DUE_DAYS = 180


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_now(value: str | None) -> datetime:
    if not value:
        return _now()
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _selected_roots(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str,
) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    if scope in ("all", "global"):
        roots.append(("global", Path(global_root).expanduser()))
    if scope in ("all", "project"):
        roots.append(("project", Path(project_root).expanduser()))
    return roots


def _safe_existing_store(root: Path, scope: str) -> ScopedMemoryStore | None:
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Memory root must be a real directory: {root}")
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope),
        sanitize_on_write=True,
        secure_permissions=True,
    )


def _item_target(item: SemanticMemory | ProceduralMemory) -> str:
    if isinstance(item, SemanticMemory):
        return f"semantic/{item.id}.md"
    return f"procedures/{item.id}.md"


def _freshness_row(
    *,
    scope: str,
    root: Path,
    item: SemanticMemory | ProceduralMemory,
    updated: datetime,
    now: datetime,
    review_due_days: int,
) -> dict[str, Any] | None:
    age_days = (now - updated).days
    if age_days < review_due_days:
        return None
    due_at = updated + timedelta(days=review_due_days)
    return {
        "code": "review-due-memory",
        "scope": scope,
        "root": str(root),
        "target": _item_target(item),
        "title": item.title,
        "updated_at": updated.isoformat(timespec="seconds"),
        "age_days": age_days,
        "review_due_after_days": review_due_days,
        "review_due_at": due_at.isoformat(timespec="seconds"),
        "confidence": item.confidence,
        "strength": item.strength,
        "action": "review memory for freshness; refresh, append update_log, or forget only with explicit user approval",
    }


def scan_review_due(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str = "all",
    review_due_days: int = DEFAULT_REVIEW_DUE_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = now or _now()
    due: list[dict[str, Any]] = []
    root_reports: list[dict[str, Any]] = []
    for selected_scope, root in _selected_roots(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
    ):
        store = _safe_existing_store(root, selected_scope)
        if store is None:
            root_reports.append(
                {
                    "scope": selected_scope,
                    "root": str(root),
                    "status": "missing",
                    "review_due_count": 0,
                }
            )
            continue
        count_before = len(due)
        items: list[SemanticMemory | ProceduralMemory] = []
        items.extend(store.list_semantic_memories(limit=1000))
        items.extend(store.list_procedural_memories(limit=1000))
        for item in items:
            updated = _parse_datetime(item.updated_at) or _parse_datetime(item.created_at)
            if updated is None:
                continue
            row = _freshness_row(
                scope=selected_scope,
                root=root,
                item=item,
                updated=updated,
                now=timestamp,
                review_due_days=review_due_days,
            )
            if row is not None:
                due.append(row)
        root_reports.append(
            {
                "scope": selected_scope,
                "root": str(root),
                "status": "review" if len(due) > count_before else "ok",
                "review_due_count": len(due) - count_before,
            }
        )
    due.sort(key=lambda row: (-int(row["age_days"]), row["scope"], row["target"]))
    return {
        "status": "review" if due else "ok",
        "review_due_days": review_due_days,
        "review_due_count": len(due),
        "roots": root_reports,
        "review_due": due,
    }


def summarize_health(payload: dict[str, Any]) -> dict[str, Any]:
    by_code = Counter(str(issue.get("code", "")) for issue in payload.get("issues", []))
    by_severity = Counter(
        str(issue.get("severity", "")) for issue in payload.get("issues", [])
    )
    return {
        "status": payload.get("status", "ok"),
        "issue_count": int(payload.get("issue_count", 0)),
        "by_code": dict(sorted(by_code.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "issues": payload.get("issues", []),
    }


def summarize_feedback(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for selected_scope, root in _selected_roots(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
    ):
        root = root.expanduser()
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise ValueError(f"Memory root must be a real directory: {root}")
        rows.extend(load_feedback_rows(root, selected_scope))
    events = Counter(str(row.get("event", "")) for row in rows)
    ratings = Counter(
        str(row.get("rating", ""))
        for row in rows
        if row.get("event") == "recall_feedback"
    )
    return {
        "row_count": len(rows),
        "events": dict(sorted(events.items())),
        "ratings": dict(sorted(ratings.items())),
        "recent": rows[-10:],
    }


def _status_from_sections(
    *,
    index: dict[str, Any],
    health: dict[str, Any],
    review: dict[str, Any],
    lifecycle: dict[str, Any],
    freshness: dict[str, Any],
    golden_eval: dict[str, Any],
    golden_candidates: dict[str, Any],
) -> str:
    if golden_eval.get("status") == "fail":
        return "fail"
    if index.get("rebuild_needed"):
        if (
            int(health.get("issue_count", 0))
            or int(review.get("review_inbox_count", 0))
            or int(lifecycle.get("proposal_count", 0))
            or int(freshness.get("review_due_count", 0))
            or int(golden_candidates.get("candidate_count", 0))
        ):
            return "review"
        return "warn"
    if (
        int(health.get("issue_count", 0))
        or int(review.get("review_inbox_count", 0))
        or int(lifecycle.get("proposal_count", 0))
        or int(freshness.get("review_due_count", 0))
        or int(golden_candidates.get("candidate_count", 0))
    ):
        return "review"
    return "ok"


def run_quality_report(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str = "all",
    review_due_days: int = DEFAULT_REVIEW_DUE_DAYS,
    hot_file_max_bytes: int = 250_000,
    low_confidence: float = 0.4,
    stale_days: int = 365,
    lifecycle_archive_after_days: int = 90,
    lifecycle_max_ledger_bytes: int = 250_000,
    now: datetime | None = None,
    golden_cases: list[RetrievalCase] | None = None,
    skip_golden: bool = False,
    golden_min_pass_rate: float = 0.8,
    golden_strategy: str = "hybrid",
    golden_embedding: str = "local",
    golden_graph: str = "local",
) -> dict[str, Any]:
    timestamp = now or _now()
    index = maintain_indexes(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
        write=False,
    )
    health_raw = run_health(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
        hot_file_max_bytes=hot_file_max_bytes,
        low_confidence=low_confidence,
        stale_days=stale_days,
        now=timestamp,
    )
    health = summarize_health(health_raw)
    lifecycle = run_lifecycle(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
        archive_after_days=lifecycle_archive_after_days,
        max_ledger_bytes=lifecycle_max_ledger_bytes,
        now=timestamp.isoformat(timespec="seconds"),
    )
    review_raw = run_review(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
        hot_file_max_bytes=hot_file_max_bytes,
        low_confidence=low_confidence,
        stale_days=stale_days,
        lifecycle_archive_after_days=lifecycle_archive_after_days,
        lifecycle_max_ledger_bytes=lifecycle_max_ledger_bytes,
    )
    review = {
        "status": review_raw["status"],
        "review_inbox_count": review_raw["review_inbox_count"],
        "golden_proposal_count": len(review_raw["golden_proposals"]),
        "repair_proposal_count": len(review_raw["repair_proposals"]),
        "pending_candidate_count": review_raw["pending_candidate_count"],
        "lifecycle_proposal_count": review_raw["lifecycle_proposal_count"],
        "review_inbox": review_raw["review_inbox"][:25],
    }
    freshness = scan_review_due(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
        review_due_days=review_due_days,
        now=timestamp,
    )
    feedback = summarize_feedback(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
    )
    golden_candidates = summarize_golden_candidate_backlog(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
    )
    if skip_golden:
        golden_eval = {"status": "skipped", "passed": 0, "failed": 0, "total": 0}
    else:
        golden_eval = run_golden_eval(
            project_root=project_root,
            global_root=global_root,
            cases=golden_cases,
            min_pass_rate=golden_min_pass_rate,
            strategy=golden_strategy,
            embedding=golden_embedding,
            graph=golden_graph,
        )
    status = _status_from_sections(
        index=index,
        health=health,
        review=review,
        lifecycle=lifecycle,
        freshness=freshness,
        golden_eval=golden_eval,
        golden_candidates=golden_candidates,
    )
    warnings = []
    for root_report in index.get("roots", []):
        warnings.extend(root_report.get("warnings", []))
    return {
        "status": status,
        "scope": scope,
        "generated_at": timestamp.isoformat(timespec="seconds"),
        "read_only": True,
        "index": index,
        "health": health,
        "feedback": feedback,
        "review": review,
        "freshness": freshness,
        "lifecycle": {
            "status": lifecycle["status"],
            "ledger_count": lifecycle["ledger_count"],
            "proposal_count": lifecycle["proposal_count"],
            "ledgers": lifecycle["ledgers"],
            "proposals": lifecycle["proposals"],
        },
        "golden_eval": golden_eval,
        "golden_candidates": golden_candidates,
        "warnings": warnings,
    }


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Quality Report",
        "",
        "Status: {}".format(payload["status"]),
        "Read-only: %s" % ("yes" if payload["read_only"] else "no"),
        "Scope: {}".format(payload["scope"]),
        "Index rebuild needed: %s"
        % ("yes" if payload["index"]["rebuild_needed"] else "no"),
        "Health issues: {}".format(payload["health"]["issue_count"]),
        "Review inbox: {}".format(payload["review"]["review_inbox_count"]),
        "Review-due memories: {}".format(payload["freshness"]["review_due_count"]),
        "Lifecycle proposals: {}".format(payload["lifecycle"]["proposal_count"]),
        "Feedback rows: {}".format(payload["feedback"]["row_count"]),
        "Golden candidates: {} ready / {} total".format(
            payload["golden_candidates"]["ready_count"],
            payload["golden_candidates"]["candidate_count"],
        ),
        "Golden eval: {}".format(payload["golden_eval"]["status"]),
        "",
    ]
    if payload["warnings"]:
        lines.append("## Warnings")
        for warning in payload["warnings"][:10]:
            lines.append(f"- {warning}")
        lines.append("")
    if payload["review"]["review_inbox"]:
        lines.append("## Review Inbox")
        for item in payload["review"]["review_inbox"][:10]:
            lines.append(
                "- [{severity}] {category}/{scope} {target}: {summary}".format(**item)
            )
        lines.append("")
    if payload["freshness"]["review_due"]:
        lines.append("## Review Due")
        for item in payload["freshness"]["review_due"][:10]:
            lines.append(
                "- {scope}/{target}: age {age_days}d, due after {review_due_after_days}d".format(
                    **item
                )
            )
        lines.append("")
    if payload["golden_candidates"]["candidates"]:
        lines.append("## Golden Candidate Backlog")
        for item in payload["golden_candidates"]["candidates"][:10]:
            lines.append(
                "- [{status}] {name}: {query}".format(
                    status=item.get("status", ""),
                    name=item.get("name", ""),
                    query=item.get("query", ""),
                )
            )
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the read-only MemoryWiki quality and memory-review checkpoint."
    )
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--scope", choices=("all", "project", "global"), default="all")
    parser.add_argument("--review-due-days", type=int, default=DEFAULT_REVIEW_DUE_DAYS)
    parser.add_argument("--hot-file-max-bytes", type=int, default=250_000)
    parser.add_argument("--low-confidence", type=float, default=0.4)
    parser.add_argument("--stale-days", type=int, default=365)
    parser.add_argument("--lifecycle-archive-after-days", type=int, default=90)
    parser.add_argument("--lifecycle-max-ledger-bytes", type=int, default=250_000)
    parser.add_argument("--case-file")
    parser.add_argument("--skip-golden", action="store_true")
    parser.add_argument("--golden-min-pass-rate", type=float, default=0.8)
    parser.add_argument(
        "--golden-strategy",
        choices=("live", "indexed", "hybrid"),
        default="hybrid",
    )
    parser.add_argument("--golden-embedding", choices=("off", "local"), default="local")
    parser.add_argument("--golden-graph", choices=("off", "local"), default="local")
    parser.add_argument("--now")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cases = (
            None
            if args.skip_golden
            else load_cases(args.case_file, project_root=args.project_root)
        )
        payload = run_quality_report(
            project_root=args.project_root,
            global_root=args.global_root,
            scope=args.scope,
            review_due_days=args.review_due_days,
            hot_file_max_bytes=args.hot_file_max_bytes,
            low_confidence=args.low_confidence,
            stale_days=args.stale_days,
            lifecycle_archive_after_days=args.lifecycle_archive_after_days,
            lifecycle_max_ledger_bytes=args.lifecycle_max_ledger_bytes,
            now=_parse_now(args.now) if args.now else None,
            golden_cases=cases,
            skip_golden=args.skip_golden,
            golden_min_pass_rate=args.golden_min_pass_rate,
            golden_strategy=args.golden_strategy,
            golden_embedding=args.golden_embedding,
            golden_graph=args.golden_graph,
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0 if payload["status"] in {"ok", "review", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
