from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

from memory_index_maintain import maintain_indexes
from memory_system.errors import format_cli_error
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore


PENDING_CAPTURE_FILE = "session_captures.jsonl"
WRITE_GATES = (
    "MEMORY_CHAT_WRITE_ENABLED",
    "MEMORY_MCP_WRITE_ENABLED",
    "MEMORY_GLOBAL_WRITE_ENABLED",
    "MEMORY_MCP_ALLOW_ROOT_OVERRIDE",
)


def _root_report(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"path": str(root), "status": "missing", "exists": False, "is_symlink": False}
    return {
        "path": str(root),
        "status": "ok" if root.is_dir() and not root.is_symlink() else "unsafe",
        "exists": True,
        "is_dir": root.is_dir(),
        "is_symlink": root.is_symlink(),
    }


def _pending_capture_count(root: Path, scope: str) -> dict[str, Any]:
    path = root / "_pending" / PENDING_CAPTURE_FILE
    report = {"path": str(path), "count": 0, "status": "missing"}
    if not root.exists() or root.is_symlink():
        return report
    try:
        store = ScopedMemoryStore(
            MemoryScopePaths.from_root(root, scope=scope),
            sanitize_on_write=True,
            secure_permissions=True,
        )
        if path.exists():
            report["count"] = len(store._read_lines_bounded(path))
            report["status"] = "ok"
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        report["status"] = "warn"
        report["warning"] = str(exc)
    return report


def _mcp_config_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "status": "missing"}
    if path.is_symlink():
        return {"path": str(path), "status": "unsafe", "warning": "MCP config is a symlink."}
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw or "{}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"path": str(path), "status": "warn", "warning": str(exc)}
    servers = payload.get("mcpServers") if isinstance(payload, dict) else None
    configured = isinstance(servers, dict) and "memorywiki-memory" in servers
    return {
        "path": str(path),
        "status": "ok" if configured else "warn",
        "memorywiki_memory_configured": configured,
    }


def _gate_report() -> dict[str, str]:
    return {
        name: "enabled" if str(os.getenv(name, "")).lower() in {"1", "true", "yes", "on"} else "disabled"
        for name in WRITE_GATES
    }


def _overall(payload: dict[str, Any]) -> str:
    if any(report.get("status") == "unsafe" for report in payload["roots"].values()):
        return "fail"
    if payload["index"].get("rebuild_needed"):
        return "warn"
    if any(report.get("count", 0) for report in payload["pending_captures"].values()):
        return "warn"
    if payload["mcp_config"].get("status") in {"missing", "warn"}:
        return "warn"
    if any(value == "enabled" for value in payload["write_gates"].values()):
        return "warn"
    return "ok"


def _next_actions(payload: dict[str, Any]) -> list[str]:
    actions = []
    if payload["index"].get("rebuild_needed"):
        actions.append("Run `memorywiki-index-maintain --write` only if explicit writes are approved.")
    if any(report.get("count", 0) for report in payload["pending_captures"].values()):
        actions.append("Review `_pending/session_captures.jsonl`; do not promote without explicit review.")
    if payload["mcp_config"].get("status") in {"missing", "warn"}:
        actions.append("Run `memorywiki-mcp-config --output .mcp.json` if this workspace needs MCP recall.")
    if any(value == "enabled" for value in payload["write_gates"].values()):
        actions.append("Disable write/root override gates unless the current task explicitly needs them.")
    if not actions:
        actions.append("Read-only MemoryWiki startup looks healthy.")
    return actions


def status_report(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str = "all",
    mcp_config: str | Path | None = None,
) -> dict[str, Any]:
    project = Path(project_root).expanduser()
    global_mem = Path(global_root).expanduser()
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "read_only": True,
        "roots": {
            "project": _root_report(project),
            "global": _root_report(global_mem),
        },
        "index": maintain_indexes(
            project_root=project,
            global_root=global_mem,
            scope=scope,
            write=False,
        ),
        "pending_captures": {
            "project": _pending_capture_count(project, "project"),
            "global": _pending_capture_count(global_mem, "global"),
        },
        "mcp_config": _mcp_config_report(Path(mcp_config or Path.cwd() / ".mcp.json").expanduser()),
        "write_gates": _gate_report(),
    }
    payload["status"] = _overall(payload)
    payload["top_next_actions"] = _next_actions(payload)
    return payload


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Status",
        "",
        "Status: %s" % payload["status"],
        "Read-only: yes",
        "Scope: %s" % payload["scope"],
        "",
        "Top next actions:",
    ]
    lines.extend("- %s" % action for action in payload["top_next_actions"])
    lines.append("")
    lines.append("Indexes:")
    for item in payload["index"]["roots"]:
        lines.append("- [%s] %s" % (item["scope"], item["status"]))
    lines.append("Pending captures:")
    for scope, report in payload["pending_captures"].items():
        lines.append("- %s: %s" % (scope, report.get("count", 0)))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only MemoryWiki startup/status report.")
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--scope", choices=("all", "project", "global"), default="all")
    parser.add_argument("--mcp-config", default=str(Path.cwd() / ".mcp.json"))
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = status_report(
            project_root=args.project_root,
            global_root=args.global_root,
            scope=args.scope,
            mcp_config=args.mcp_config,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(format_cli_error(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
