from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import html
import json
import os
from pathlib import Path
import re
import sys

from memory_system.paths import MemoryScopePaths
from memory_system.sanitizer import sanitize_text
from memory_system.store import ScopedMemoryStore


EVENT_HANDLER_RE = re.compile(r"\bon([a-z0-9_-]+)\s*=", re.IGNORECASE)


def safe_store(root: Path, scope: str) -> ScopedMemoryStore | None:
    root = root.expanduser()
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Memory root must be a real directory: %s" % root)
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=True,
    )


def preview(text: str, limit: int = 220) -> str:
    clean = " ".join(sanitize_text(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def build_events_for_store(store: ScopedMemoryStore, scope: str) -> list[dict]:
    events = []
    for session_meta in store.list_sessions(limit=500):
        session = store.read_session(session_meta.id)
        if session is None:
            continue
        events.append(
            {
                "ts": session.date,
                "scope": scope,
                "kind": "session",
                "id": session.id,
                "title": session.title,
                "summary": preview(session.body or " ".join(session.keypoints)),
                "body": session.body,
                "keypoints": session.keypoints,
                "actions": session.actions,
                "pending": session.pending,
                "source_refs": [
                    {
                        "kind": "session",
                        "path": "sessions/%s.md" % session.id,
                        "identifier": session.id,
                        "excerpt": None,
                    }
                ],
            }
        )
    if store._is_safe_readable_file(store.paths.project_profile):
        profile_text = sanitize_text(store._read_text_bounded(store.paths.project_profile))
        try:
            ts = datetime.fromtimestamp(
                store.paths.project_profile.stat().st_mtime
            ).astimezone().isoformat(timespec="seconds")
        except OSError:
            ts = ""
        events.append(
            {
                "ts": ts,
                "scope": scope,
                "kind": "project_profile",
                "id": "PROJECT_PROFILE.md",
                "title": "Project Profile",
                "summary": preview(profile_text),
                "body": profile_text,
                "source_refs": [
                    {
                        "kind": "hot-file",
                        "path": "PROJECT_PROFILE.md",
                        "identifier": "project_profile",
                        "excerpt": None,
                    }
                ],
            }
        )
    for date_text in store.list_episodes():
        episode = store.read_episode(date_text)
        if episode is None:
            continue
        events.append(
            {
                "ts": episode.date,
                "scope": scope,
                "kind": "episode",
                "id": episode.date,
                "title": "Episode %s" % episode.date,
                "summary": preview(episode.body),
                "source_refs": [
                    {
                        "kind": "episode",
                        "path": "episodes/%s.md" % episode.date,
                        "identifier": episode.date,
                        "excerpt": None,
                    }
                ],
            }
        )
    for item in store.list_semantic_memories(limit=500):
        events.append(
            {
                "ts": item.updated_at or item.created_at,
                "scope": scope,
                "kind": "semantic",
                "id": item.id,
                "title": item.title,
                "summary": preview(item.content),
                "confidence": item.confidence,
                "strength": item.strength,
                "last_accessed": item.last_accessed,
                "source_refs": [asdict(ref) for ref in item.source_refs],
            }
        )
    for item in store.list_procedural_memories(limit=500):
        events.append(
            {
                "ts": item.updated_at or item.created_at,
                "scope": scope,
                "kind": "procedure",
                "id": item.id,
                "title": item.title,
                "summary": preview("\n".join([item.trigger] + item.steps)),
                "confidence": item.confidence,
                "strength": item.strength,
                "last_accessed": item.last_accessed,
                "source_refs": [asdict(ref) for ref in item.source_refs],
            }
        )
    for entry in store.read_audit(limit=500):
        events.append(
            {
                "ts": entry.ts,
                "scope": scope,
                "kind": "audit",
                "id": "%s:%s" % (entry.target_kind, entry.target_id),
                "title": "%s %s" % (entry.action, entry.target_kind),
                "summary": preview(entry.reason),
                "dry_run": entry.dry_run,
                "details": entry.details,
                "source_refs": [
                    {
                        "kind": "audit-log",
                        "path": "audit.jsonl",
                        "identifier": entry.target_id,
                        "excerpt": None,
                    }
                ],
            }
        )
    return events


def build_timeline(args) -> dict:
    roots = []
    if args.scope in ("all", "global"):
        roots.append(("global", Path(args.global_root).expanduser()))
    if args.scope in ("all", "project"):
        roots.append(("project", Path(args.project_root).expanduser()))
    events = []
    for scope, root in roots:
        store = safe_store(root, scope)
        if store is None:
            continue
        events.extend(build_events_for_store(store, scope))
    events.sort(key=lambda event: (event.get("ts") or "", event.get("id") or ""), reverse=True)
    return {"scope": args.scope, "events": events}


def escape_html_text(text) -> str:
    escaped = html.escape(str(text), quote=True)
    return EVENT_HANDLER_RE.sub(lambda match: "on-%s=" % match.group(1), escaped)


def escape_markdown_text(text) -> str:
    escaped = html.escape(str(text), quote=False)
    escaped = EVENT_HANDLER_RE.sub(lambda match: "on-%s=" % match.group(1), escaped)
    return escaped.replace("|", "\\|")


def _render_list(title: str, values: list[str]) -> str:
    if not values:
        return ""
    items = "".join("<li>%s</li>" % escape_html_text(value) for value in values)
    return "<h3>%s</h3><ul>%s</ul>" % (escape_html_text(title), items)


def render_replay_details(event: dict) -> str:
    detail_parts = []
    detail_parts.append(_render_list("Keypoints", event.get("keypoints") or []))
    detail_parts.append(_render_list("Actions", event.get("actions") or []))
    detail_parts.append(_render_list("Pending", event.get("pending") or []))
    body = event.get("body") or ""
    if body:
        detail_parts.append(
            "<h3>Replay</h3><pre>%s</pre>" % escape_html_text(body)
        )
    body_html = "".join(part for part in detail_parts if part)
    if not body_html:
        return ""
    return "<details><summary>Replay</summary>%s</details>" % body_html


def render_markdown(payload: dict) -> str:
    lines = ["# Memory Timeline", ""]
    if not payload["events"]:
        lines.append("- No timeline events found.")
        return "\n".join(lines) + "\n"
    for event in payload["events"]:
        lines.append(
            "- **%s** `%s/%s` %s: %s"
            % (
                escape_markdown_text(event.get("ts", "")),
                escape_markdown_text(event.get("scope", "")),
                escape_markdown_text(event.get("kind", "")),
                escape_markdown_text(event.get("title", "")),
                escape_markdown_text(event.get("summary", "")),
            )
        )
    return "\n".join(lines) + "\n"


def render_html(payload: dict) -> str:
    items = []
    for event in payload["events"]:
        refs = event.get("source_refs") or []
        source_text = ", ".join(
            "%s:%s" % (ref.get("kind", ""), ref.get("identifier") or ref.get("path", ""))
            for ref in refs[:3]
        )
        items.append(
            "<article class=\"event\">"
            "<div class=\"meta\">%s · %s/%s</div>"
            "<h2>%s</h2>"
            "<p>%s</p>"
            "%s"
            "<footer>%s</footer>"
            "</article>"
            % (
                escape_html_text(event.get("ts", "")),
                escape_html_text(event.get("scope", "")),
                escape_html_text(event.get("kind", "")),
                escape_html_text(event.get("title", "")),
                escape_html_text(event.get("summary", "")),
                render_replay_details(event),
                escape_html_text(source_text),
            )
        )
    body = "\n".join(items) or "<p>No timeline events found.</p>"
    return (
        "<!doctype html>\n"
        "<html><head><meta charset=\"utf-8\"><title>Memory Timeline</title>"
        "<style>"
        "body{font-family:ui-serif,Georgia,serif;margin:2rem;line-height:1.5;background:#f6f1e8;color:#1f2421}"
        ".event{background:#fffaf0;border:1px solid #dacdb6;border-radius:14px;padding:1rem 1.2rem;margin:1rem 0}"
        ".meta,footer{color:#6f6254;font-size:.9rem}h2{margin:.2rem 0 .5rem}"
        "details{margin:.8rem 0;padding:.7rem;border-radius:10px;background:#f4ead8}"
        "summary{cursor:pointer;font-weight:700}pre{white-space:pre-wrap;overflow:auto}"
        "</style></head><body><h1>Memory Timeline</h1>%s</body></html>\n"
        % body
    )


def assert_safe_output(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError("Output path may not be a symlink: %s" % path)
    parent = path.parent
    for ancestor in (parent, *parent.parents):
        if ancestor.exists() and ancestor.is_symlink():
            raise ValueError(
                "Output path may not be below a symlinked directory: %s" % ancestor
            )
    parent.mkdir(parents=True, exist_ok=True)


def write_text_no_follow(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        if path.is_symlink():
            raise ValueError("Output path may not be a symlink: %s" % path)
        raise
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def write_or_print(text: str, out: str | None) -> None:
    if out:
        path = Path(out).expanduser()
        assert_safe_output(path)
        write_text_no_follow(path, text)
    else:
        print(text, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a local memory timeline.")
    parser.add_argument(
        "--project-root",
        default=str(Path.cwd() / ".agent_memory" / "project"),
        help="Project memory root",
    )
    parser.add_argument(
        "--global-root",
        default=str(Path.home() / ".agent_memory" / "global"),
        help="Global memory root",
    )
    parser.add_argument("--scope", choices=("all", "project", "global"), default="all")
    parser.add_argument("--format", choices=("markdown", "json", "html"), default="markdown")
    parser.add_argument("--out", help="Optional output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = build_timeline(args)
        if args.format == "json":
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        elif args.format == "html":
            text = render_html(payload)
        else:
            text = render_markdown(payload)
        write_or_print(text, args.out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
