from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
import sys

from memory_system.config import MemoryConfig
from memory_system.models import SessionFile, SessionMeta, SessionSummary
from memory_system.paths import MemoryScopePaths
from memory_system.sanitizer import neutralize_instruction_text, sanitize_text
from memory_system.store import ScopedMemoryStore


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _default_session_id() -> str:
    return "session-%s" % datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _merge_items(*values: list[str] | None) -> list[str]:
    merged = []
    for value in values:
        for item in value or []:
            if item and item not in merged:
                merged.append(item)
    return merged


def _coerce_items(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(value).strip()]


def _safe_output_text(text: str | None) -> str:
    return neutralize_instruction_text(sanitize_text(text or ""))


def _safe_output_json(value):
    if isinstance(value, dict):
        return {_safe_output_text(str(key)): _safe_output_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_output_json(item) for item in value]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _safe_output_text(str(value))


def _reject_stdin_routing_fields(parser: argparse.ArgumentParser, payload: dict) -> None:
    routing_fields = {"scope", "global_root", "project_root"}
    present = sorted(field for field in routing_fields if field in payload)
    if present:
        parser.error(
            "--stdin payload may not set routing fields (%s); use CLI flags instead"
            % ", ".join(present)
        )


def _build_store(
    scope: str = "project",
    project_root: str | None = None,
    global_root: str | None = None,
) -> ScopedMemoryStore:
    config = MemoryConfig.from_env(project_storage_root=project_root)
    if scope not in {"global", "project"}:
        raise ValueError("scope must be 'global' or 'project'")
    if scope == "global":
        storage_root = global_root or config.global_storage_root
    else:
        storage_root = config.project_storage_root
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(storage_root, scope=scope),
        sanitize_on_write=config.sanitize_on_write,
        secure_permissions=config.secure_permissions,
    )


def save_summary(
    summary: str,
    session_id: str | None = None,
    title: str | None = None,
    key_points: list[str] | None = None,
    actions_taken: list[str] | None = None,
    pending_tasks: list[str] | None = None,
    body: str | None = None,
    duration_seconds: int | None = None,
    project_root: str | None = None,
    global_root: str | None = None,
    scope: str = "project",
    write_episode: bool = True,
) -> SessionSummary:
    store = _build_store(scope=scope, project_root=project_root, global_root=global_root)
    ts = datetime.now().astimezone().isoformat()
    session_id = session_id or _default_session_id()
    session = SessionSummary(
        ts=ts,
        session_id=session_id,
        summary=summary,
        key_points=key_points or [],
        actions_taken=actions_taken or [],
        pending_tasks=pending_tasks or [],
    )
    store.append_session_summary(session)
    session_file = SessionFile(
        id=session_id,
        date=ts[:10],
        scope=scope,
        title=title or summary[:80] or session_id,
        keypoints=key_points or [],
        actions=actions_taken or [],
        pending=pending_tasks or [],
        duration_seconds=duration_seconds,
        body=body or summary,
    )
    store.write_session(session_file)
    if write_episode:
        store.append_to_episode(
            ts[:10],
            session_file.title,
            body or summary,
            session_meta=SessionMeta(
                id=session_id,
                title=session_file.title,
                started_at=ts,
                ended_at=ts,
            ),
        )
    return session


def list_summaries(
    limit: int = 10,
    project_root: str | None = None,
    global_root: str | None = None,
    scope: str = "project",
) -> list[SessionSummary]:
    return _build_store(
        scope=scope, project_root=project_root, global_root=global_root
    ).read_session_summaries(limit=limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="Save or list memory session summaries")
    parser.add_argument("--project-root", help="Project memory root")
    parser.add_argument("--global-root", help="Global memory root")
    parser.add_argument("--scope", choices=["global", "project"], help="Memory scope")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    parser.add_argument("--limit", type=int, default=10)

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--save", action="store_true", help="Save a session summary")
    action.add_argument("--list", action="store_true", help="List recent summaries")

    parser.add_argument("--id", dest="session_id", help="Session ID")
    parser.add_argument("--title", help="Human-readable session title")
    parser.add_argument("--summary", help="One-line summary")
    parser.add_argument("--body", help="Long-form session body")
    parser.add_argument("--duration-seconds", type=int, help="Session duration")
    parser.add_argument("--stdin", action="store_true", help="Read JSON payload from stdin")
    parser.add_argument("--no-episode", action="store_true", help="Do not append the daily episode")
    parser.add_argument("--keypoint", action="append", default=[], help="Repeatable key point")
    parser.add_argument("--action", action="append", default=[], help="Repeatable action taken")
    parser.add_argument("--pending", action="append", default=[], help="Repeatable pending task")
    parser.add_argument("--keypoints", help="Deprecated comma-separated key points")
    parser.add_argument("--actions", help="Deprecated comma-separated actions taken")
    args = parser.parse_args()

    if args.save:
        stdin_payload = {}
        if args.stdin:
            try:
                stdin_payload = json.loads(sys.stdin.read() or "{}")
            except json.JSONDecodeError as exc:
                parser.error("--stdin must contain a JSON object: %s" % exc)
            if not isinstance(stdin_payload, dict):
                parser.error("--stdin must contain a JSON object")
            _reject_stdin_routing_fields(parser, stdin_payload)
        legacy_keypoints = _split_csv(args.keypoints)
        legacy_actions = _split_csv(args.actions)
        legacy_pending = []
        pending_flags = args.pending or []
        if any("," in item for item in pending_flags):
            print(
                "Warning: comma-separated --pending values are deprecated; use repeated --pending flags.",
                file=sys.stderr,
            )
            legacy_pending = []
            for item in pending_flags:
                legacy_pending.extend(_split_csv(item))
            pending_flags = []
        if args.keypoints:
            print(
                "Warning: --keypoints is deprecated; use repeated --keypoint flags.",
                file=sys.stderr,
            )
        if args.actions:
            print(
                "Warning: --actions is deprecated; use repeated --action flags.",
                file=sys.stderr,
            )

        summary = args.summary or stdin_payload.get("summary")
        if not summary and stdin_payload.get("body"):
            summary = str(stdin_payload["body"]).splitlines()[0][:160]
        if not summary:
            parser.error("--summary is required with --save")
        scope = args.scope or "project"
        session = save_summary(
            summary=str(summary),
            session_id=args.session_id
            or stdin_payload.get("session_id")
            or stdin_payload.get("id"),
            title=args.title or stdin_payload.get("title"),
            key_points=_merge_items(
                _coerce_items(stdin_payload.get("key_points")),
                _coerce_items(stdin_payload.get("keypoints")),
                legacy_keypoints,
                args.keypoint,
            ),
            actions_taken=_merge_items(
                _coerce_items(stdin_payload.get("actions_taken")),
                _coerce_items(stdin_payload.get("actions")),
                legacy_actions,
                args.action,
            ),
            pending_tasks=_merge_items(
                _coerce_items(stdin_payload.get("pending_tasks")),
                _coerce_items(stdin_payload.get("pending")),
                legacy_pending,
                pending_flags,
            ),
            body=args.body or stdin_payload.get("body"),
            duration_seconds=args.duration_seconds
            if args.duration_seconds is not None
            else stdin_payload.get("duration_seconds"),
            project_root=args.project_root,
            global_root=args.global_root,
            scope=scope,
            write_episode=not args.no_episode,
        )
        if args.format == "json":
            print(json.dumps(_safe_output_json(asdict(session)), ensure_ascii=False, indent=2))
        else:
            print("Saved session summary: %s" % _safe_output_text(session.session_id))
            print(_safe_output_text(session.summary))
        return

    sessions = list_summaries(
        limit=args.limit,
        project_root=args.project_root,
        global_root=args.global_root,
        scope=args.scope or "project",
    )
    if args.format == "json":
        print(
            json.dumps(
                _safe_output_json([asdict(session) for session in sessions]),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not sessions:
        print("No session summaries found.")
        return
    for index, session in enumerate(sessions, start=1):
        print("[%s] %s %s" % (index, _safe_output_text(session.session_id), _safe_output_text(session.ts[:19])))
        print("    %s" % _safe_output_text(session.summary))
        if session.pending_tasks:
            print("    Pending: %s" % ", ".join(_safe_output_text(item) for item in session.pending_tasks))


if __name__ == "__main__":
    main()
