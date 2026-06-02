from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from memory_system.errors import MemoryPathError, format_cli_error
from memory_system.models import ProceduralMemory, SemanticMemory, SessionFile, SourceRef
from memory_system.paths import MemoryScopePaths
from memory_system.sanitizer import neutralize_instruction_text, sanitize_text
from memory_system.store import ScopedMemoryStore


MAX_HITS = 25


@dataclass
class HistoryHit:
    scope: str
    kind: str
    id: str
    title: str
    timestamp: str | None
    matched_fields: list[str]
    source_refs: list[SourceRef]
    actions: list[dict[str, Any]]


def _clean(text: object, max_chars: int = 240) -> str:
    value = neutralize_instruction_text(sanitize_text(str(text)))
    return value[:max_chars]


def _assert_workspace_path(path: Path, workspace_root: Path) -> tuple[Path, str]:
    workspace = workspace_root.expanduser().resolve(strict=True)
    raw_target = path.expanduser()
    target = raw_target if raw_target.is_absolute() else workspace / raw_target
    if target.exists() and target.is_symlink():
        raise MemoryPathError(
            "File history target may not be a symlink: %s" % target,
            reason="the gate is advisory and must not follow project-file escapes.",
            fix="query the real file path inside the workspace.",
        )
    parent = target.parent
    for component in [target, *target.parents]:
        if component == workspace.parent:
            break
        if component.exists() and component.is_symlink():
            raise MemoryPathError("File history path may not be below a symlink: %s" % component)
    resolved_parent = parent.resolve(strict=True) if parent.exists() else parent.resolve(strict=False)
    resolved = resolved_parent / target.name
    try:
        relative = resolved.relative_to(workspace)
    except ValueError:
        raise MemoryPathError(
            "File history path must stay within the workspace root: %s" % target,
            reason="project files are only used as query keys and freshness signals.",
            fix="pass --workspace-root for the project containing the file.",
        )
    return resolved, relative.as_posix()


def _source_refs_payload(refs: list[SourceRef]) -> list[dict[str, Any]]:
    return [
        {
            "kind": ref.kind,
            "path": _clean(ref.path),
            "identifier": _clean(ref.identifier) if ref.identifier else None,
            "excerpt": _clean(ref.excerpt) if ref.excerpt else None,
        }
        for ref in refs[:10]
    ]


def _actions(kind: str, identifier: str, source_refs: list[SourceRef]) -> list[dict[str, Any]]:
    actions = [
        {
            "tool": "memorywiki_read_memory",
            "arguments": {"kind": kind, "identifier": identifier, "max_chars": 1200},
        }
    ]
    for ref in source_refs[:3]:
        actions.append(
            {
                "tool": "memorywiki_source_drilldown",
                "arguments": {
                    "kind": ref.kind,
                    "path": ref.path,
                    "identifier": ref.identifier,
                    "max_chars": 1200,
                },
            }
        )
    return actions


def _timestamp_from_path(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _matches(needle: str, aliases: list[str], fields: dict[str, str]) -> list[str]:
    matched = []
    lowered_values = {key: value.lower() for key, value in fields.items()}
    candidates = [needle.lower(), *[alias.lower() for alias in aliases if alias]]
    for key, value in lowered_values.items():
        if any(candidate and candidate in value for candidate in candidates):
            matched.append(key)
    return matched


def _semantic_hit(item: SemanticMemory, matched_fields: list[str]) -> HistoryHit:
    return HistoryHit(
        scope=item.scope,
        kind="semantic",
        id=item.id,
        title=_clean(item.title),
        timestamp=item.updated_at or item.created_at,
        matched_fields=matched_fields,
        source_refs=item.source_refs,
        actions=_actions("semantic", item.id, item.source_refs),
    )


def _procedural_hit(item: ProceduralMemory, matched_fields: list[str]) -> HistoryHit:
    return HistoryHit(
        scope=item.scope,
        kind="procedural",
        id=item.id,
        title=_clean(item.title),
        timestamp=item.updated_at or item.created_at,
        matched_fields=matched_fields,
        source_refs=item.source_refs,
        actions=_actions("procedural", item.id, item.source_refs),
    )


def _session_hit(store: ScopedMemoryStore, item: SessionFile, matched_fields: list[str]) -> HistoryHit:
    return HistoryHit(
        scope=item.scope,
        kind="session",
        id=item.id,
        title=_clean(item.title),
        timestamp=_timestamp_from_path(store.paths.session_file(item.id)) or item.date,
        matched_fields=matched_fields,
        source_refs=[],
        actions=_actions("session", item.id, []),
    )


def _collect_scope_hits(
    root: Path,
    scope: str,
    needle: str,
    aliases: list[str],
    limit: int,
) -> list[HistoryHit]:
    if not root.exists() or root.is_symlink() or not root.is_dir():
        return []
    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=True,
    )
    hits: list[HistoryHit] = []
    for semantic_item in store.list_semantic_memories(limit=500):
        fields = {
            "title": semantic_item.title,
            "content": semantic_item.content,
            "concepts": " ".join(semantic_item.concepts),
            "source_refs": " ".join(ref.path for ref in semantic_item.source_refs),
            "update_log": " ".join(semantic_item.update_log),
        }
        matched = _matches(needle, aliases, fields)
        if matched:
            hits.append(_semantic_hit(semantic_item, matched))
    for procedural_item in store.list_procedural_memories(limit=500):
        fields = {
            "title": procedural_item.title,
            "trigger": procedural_item.trigger,
            "steps": " ".join(procedural_item.steps),
            "source_refs": " ".join(ref.path for ref in procedural_item.source_refs),
        }
        matched = _matches(needle, aliases, fields)
        if matched:
            hits.append(_procedural_hit(procedural_item, matched))
    for meta in store.list_sessions(limit=500):
        session = store.read_session(meta.id)
        if session is None:
            continue
        fields = {
            "title": session.title,
            "keypoints": " ".join(session.keypoints),
            "actions": " ".join(session.actions),
            "pending": " ".join(session.pending),
            "body": session.body,
        }
        matched = _matches(needle, aliases, fields)
        if matched:
            hits.append(_session_hit(store, session, matched))
    return sorted(hits, key=lambda hit: hit.timestamp or "", reverse=True)[:limit]


def file_history(
    *,
    path: str | Path,
    workspace_root: str | Path,
    project_root: str | Path,
    global_root: str | Path,
    scope: str = "all",
    limit: int = MAX_HITS,
) -> dict[str, Any]:
    if scope not in {"all", "project", "global"}:
        raise ValueError("scope must be all, project, or global")
    target, relative = _assert_workspace_path(Path(path), Path(workspace_root))
    aliases = [relative, Path(relative).name]
    scopes: list[tuple[str, Path]] = []
    if scope in {"all", "global"}:
        scopes.append(("global", Path(global_root).expanduser()))
    if scope in {"all", "project"}:
        scopes.append(("project", Path(project_root).expanduser()))
    hits: list[HistoryHit] = []
    for scope_name, root in scopes:
        remaining = max(limit - len(hits), 0)
        if remaining <= 0:
            break
        hits.extend(_collect_scope_hits(root, scope_name, relative, aliases, remaining))
    warnings: list[str] = []
    file_mtime = target.stat().st_mtime if target.exists() else None
    memory_times = []
    for hit in hits:
        if not hit.timestamp:
            continue
        try:
            memory_times.append(datetime.fromisoformat(hit.timestamp.replace("Z", "+00:00")).timestamp())
        except ValueError:
            continue
    if file_mtime is not None and memory_times and file_mtime > max(memory_times):
        warnings.append("file_modified_after_latest_memory")
    if not hits:
        warnings.append("no_prior_memory_found")
    return {
        "path": {
            "input": str(path),
            "workspace_root": str(Path(workspace_root).expanduser().resolve(strict=True)),
            "relative": relative,
            "exists": target.exists(),
            "mtime": datetime.fromtimestamp(file_mtime, tz=timezone.utc).isoformat() if file_mtime else None,
        },
        "scope": scope,
        "advisory_only": True,
        "warnings": warnings,
        "hits": [
            {
                "scope": hit.scope,
                "kind": hit.kind,
                "id": hit.id,
                "title": hit.title,
                "timestamp": hit.timestamp,
                "matched_fields": hit.matched_fields,
                "source_refs": _source_refs_payload(hit.source_refs),
                "actions": hit.actions,
            }
            for hit in hits[:limit]
        ],
    }


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki File History",
        "",
        "Path: %s" % payload["path"]["relative"],
        "Advisory only: yes",
    ]
    for warning in payload.get("warnings", []):
        lines.append("Warning: %s" % warning)
    if not payload["hits"]:
        lines.append("No prior memory found.")
        return "\n".join(lines) + "\n"
    lines.append("")
    for hit in payload["hits"]:
        lines.append("- [%s/%s] %s (%s)" % (hit["scope"], hit["kind"], hit["id"], hit["title"]))
        lines.append("  matched: %s" % ", ".join(hit["matched_fields"]))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show advisory MemoryWiki history for a project file.")
    parser.add_argument("--path", required=True, help="Project file path to query.")
    parser.add_argument("--workspace-root", default=str(Path.cwd()), help="Workspace root that contains --path.")
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--scope", choices=("all", "project", "global"), default="all")
    parser.add_argument("--limit", type=int, default=MAX_HITS)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = file_history(
            path=args.path,
            workspace_root=args.workspace_root,
            project_root=args.project_root,
            global_root=args.global_root,
            scope=args.scope,
            limit=args.limit,
        )
    except (OSError, ValueError) as exc:
        print(format_cli_error(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
