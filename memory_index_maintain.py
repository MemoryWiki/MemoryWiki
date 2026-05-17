from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from agent_leases import acquire_lease, release_lease
from memory_system.paths import MemoryScopePaths
from memory_system.retrieval_index import build_and_write_index, load_index
from memory_system.store import ScopedMemoryStore


LEASE_KIND = "retrieval-index"
DEFAULT_LEASE_TTL_SECONDS = 3600


def _scope_roots(args) -> list[tuple[str, Path]]:
    roots = []
    if args.scope in ("all", "global"):
        roots.append(("global", Path(args.global_root).expanduser()))
    if args.scope in ("all", "project"):
        roots.append(("project", Path(args.project_root).expanduser()))
    return roots


def _missing_root_report(root: Path, scope: str) -> dict:
    return {
        "scope": scope,
        "root": str(root),
        "index_path": str(root / "retrieval" / "index.jsonl"),
        "status": "missing_root",
        "fresh": False,
        "needs_rebuild": False,
        "rebuilt": False,
        "indexed": 0,
        "warnings": ["Memory root does not exist: %s" % root],
        "lease_id": None,
    }


def _classify_status(warnings: list[str], fresh: bool) -> str:
    if fresh:
        return "current"
    lowered = "\n".join(warnings).lower()
    if "missing retrieval index" in lowered:
        return "missing_index"
    tamper_markers = (
        "text hash changed",
        "malformed retrieval index",
        "unsupported retrieval index",
        "unreadable retrieval index",
        "derived term counts changed",
        "embedding vector changed",
        "conflict flag changed",
        "conflict entries changed",
        "canonical source is missing or changed",
        "canonical content changed",
        "symlink",
        "schema",
    )
    if any(marker in lowered for marker in tamper_markers):
        return "tampered_index"
    return "stale_index"


def inspect_scope_index(root: str | Path, scope: str) -> dict:
    memory_root = Path(root).expanduser()
    if not memory_root.exists():
        return _missing_root_report(memory_root, scope)
    if memory_root.is_symlink() or not memory_root.is_dir():
        raise ValueError("Memory root must be a real directory: %s" % memory_root)
    load_result = load_index(memory_root, scope)
    status = _classify_status(load_result.warnings, load_result.fresh)
    return {
        "scope": scope,
        "root": str(memory_root),
        "index_path": str(memory_root / "retrieval" / "index.jsonl"),
        "status": status,
        "fresh": load_result.fresh,
        "needs_rebuild": not load_result.fresh,
        "rebuilt": False,
        "indexed": len(load_result.rows),
        "warnings": load_result.warnings,
        "lease_id": None,
    }


def rebuild_scope_index(
    root: str | Path,
    scope: str,
    agent: str = "memorywiki-index-maintain",
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> dict:
    memory_root = Path(root).expanduser()
    report = inspect_scope_index(memory_root, scope)
    if not report["needs_rebuild"]:
        return report
    if report["status"] == "missing_root":
        return report
    lease = acquire_lease(
        root=memory_root,
        agent=agent,
        task="rebuild %s retrieval index" % scope,
        kind=LEASE_KIND,
        ttl_seconds=ttl_seconds,
        pid=os.getpid(),
        exclusive=True,
        conflicts_on="kind",
    )
    release_reason = "retrieval index rebuild complete"
    try:
        store = ScopedMemoryStore(
            MemoryScopePaths.from_root(memory_root, scope=scope),
            sanitize_on_write=True,
            secure_permissions=True,
        )
        payload = build_and_write_index(store, scope)
        refreshed = inspect_scope_index(memory_root, scope)
        refreshed.update(
            {
                "rebuilt": True,
                "indexed": payload["indexed"],
                "index_path": payload["index_path"],
                "lease_id": lease["lease_id"],
            }
        )
        return refreshed
    except Exception:
        release_reason = "retrieval index rebuild failed"
        raise
    finally:
        release_lease(
            root=memory_root,
            lease_id=lease["lease_id"],
            reason=release_reason,
        )


def maintain_indexes(
    project_root: str | Path,
    global_root: str | Path,
    scope: str = "all",
    write: bool = False,
    agent: str = "memorywiki-index-maintain",
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> dict:
    class Args:
        pass

    args = Args()
    args.project_root = project_root
    args.global_root = global_root
    args.scope = scope
    roots = _scope_roots(args)
    reports = []
    initial_rebuild_needed = False
    for root_scope, root in roots:
        report = inspect_scope_index(root, root_scope)
        initial_rebuild_needed = initial_rebuild_needed or report["needs_rebuild"]
        if write and report["needs_rebuild"]:
            report = rebuild_scope_index(
                root,
                root_scope,
                agent=agent,
                ttl_seconds=ttl_seconds,
            )
        reports.append(report)
    return {
        "dry_run": not write,
        "scope": scope,
        "rebuild_needed": initial_rebuild_needed,
        "rebuilt": any(item["rebuilt"] for item in reports),
        "roots": reports,
    }


def render_human(payload: dict) -> str:
    lines = [
        "# MemoryWiki Retrieval Index Maintenance",
        "",
        "Mode: %s" % ("dry-run" if payload["dry_run"] else "write"),
        "Scope: %s" % payload["scope"],
        "Rebuild needed: %s" % ("yes" if payload["rebuild_needed"] else "no"),
        "Rebuilt: %s" % ("yes" if payload["rebuilt"] else "no"),
        "",
    ]
    for item in payload["roots"]:
        lines.append(
            "- [%s] %s: %s%s"
            % (
                item["scope"],
                item["status"],
                item["index_path"],
                " (rebuilt)" if item["rebuilt"] else "",
            )
        )
        for warning in item["warnings"]:
            lines.append("  warning: %s" % warning)
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check and optionally rebuild MemoryWiki retrieval indexes."
    )
    parser.add_argument(
        "--project-root",
        default=str(Path.cwd() / ".agent_memory" / "project"),
        help="Project memory root.",
    )
    parser.add_argument(
        "--global-root",
        default=str(Path.home() / ".agent_memory" / "global"),
        help="Global memory root.",
    )
    parser.add_argument(
        "--scope",
        choices=("all", "project", "global"),
        default="all",
        help="Which scope indexes to inspect or rebuild.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Rebuild missing, stale, or tampered retrieval indexes.",
    )
    parser.add_argument(
        "--agent",
        default="memorywiki-index-maintain",
        help="Agent name recorded in the retrieval-index lease ledger.",
    )
    parser.add_argument(
        "--lease-ttl-seconds",
        type=int,
        default=DEFAULT_LEASE_TTL_SECONDS,
        help="TTL for the exclusive retrieval-index rebuild lease.",
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = maintain_indexes(
            project_root=args.project_root,
            global_root=args.global_root,
            scope=args.scope,
            write=args.write,
            agent=args.agent,
            ttl_seconds=args.lease_ttl_seconds,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
