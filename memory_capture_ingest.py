from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, cast

from memory_system.errors import MemoryCliUsageError, MemorySecurityError, format_cli_error
from memory_system.models import AuditEntry
from memory_system.paths import MemoryScopePaths
from memory_system.sanitizer import neutralize_instruction_text, sanitize_text
from memory_system.store import ScopedMemoryStore
from memory_system.store_io import MAX_MANAGED_JSONL_ROWS, MAX_MANAGED_READ_BYTES


ADAPTER_VERSION = "memorywiki-capture-v1"
PENDING_CAPTURE_FILE = "session_captures.jsonl"
MAX_SUMMARY_CHARS = 500
MAX_EVENTS = min(MAX_MANAGED_JSONL_ROWS, 10_000)
SENSITIVE_FIELDS = {
    "authorization",
    "body",
    "cookie",
    "cookies",
    "env",
    "environment",
    "file_content",
    "headers",
    "http_headers",
    "raw",
    "response",
    "stderr",
    "stdout",
    "tool_output",
    "tool_response",
}
SUMMARY_FIELDS = (
    "summary",
    "message",
    "prompt",
    "content",
    "text",
    "tool_name",
    "toolName",
    "file_path",
    "path",
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+?\d[\d .()_-]{7,}\d)\b")
LOCAL_USER_PATH_RE = re.compile(r"/" + r"Users/([^/\s]+)")


@dataclass
class CaptureRow:
    adapter: str
    adapter_version: str
    source: str
    source_hash: str
    line_hash: str
    event_id: int
    event_type: str
    event_ts: str | None
    session_id: str | None
    project_ref: str | None
    scope: str
    payload_summary: str
    redaction_status: str
    neutralization_status: str
    excluded_fields: list[str]
    warnings: list[str]


def _redact_capture_text(value: str) -> tuple[str, bool]:
    sanitized = sanitize_text(value)
    sanitized = EMAIL_RE.sub("[REDACTED_EMAIL]", sanitized)
    sanitized = PHONE_RE.sub("[REDACTED_PHONE]", sanitized)
    sanitized = LOCAL_USER_PATH_RE.sub("/" + "Users/[REDACTED_USER]", sanitized)
    return sanitized, sanitized != value


def _safe_text(value: object, max_chars: int = MAX_SUMMARY_CHARS) -> tuple[str, bool, bool]:
    text = str(value)
    redacted, changed = _redact_capture_text(text)
    neutralized = neutralize_instruction_text(redacted)
    was_neutralized = neutralized != redacted
    if len(neutralized) > max_chars:
        return neutralized[:max_chars].rstrip() + "...", changed, was_neutralized
    return neutralized, changed, was_neutralized


def _source_identifier(path: Path) -> str:
    return "file:%s" % sanitize_text(path.name or "capture.jsonl")


def _project_identifier(value: object) -> tuple[str, bool, bool]:
    text = str(value)
    path_like = text.startswith("/") or "\\" in text or "/" in text
    if path_like:
        name = Path(text).name or "project"
        return "path:[REDACTED_PATH]/%s" % sanitize_text(name), True, False
    return _safe_text(text, max_chars=240)


def _assert_no_symlink_components(path: Path) -> None:
    expanded = path.expanduser()
    check = expanded if expanded.is_absolute() else Path.cwd() / expanded
    parts = list(check.parents)
    parts.reverse()
    parts.append(check)
    for component in parts:
        if component.exists() and component.is_symlink():
            raise MemorySecurityError(
                "Capture source may not be a symlink or below a symlink: %s" % component,
                reason="capture import reads untrusted transcript material.",
                fix="copy the public-safe JSONL fixture into a normal file and retry.",
            )


def _read_source_bytes(path: Path) -> bytes:
    _assert_no_symlink_components(path)
    source = path.expanduser()
    if not source.is_file():
        raise MemoryCliUsageError("Capture source must be a JSONL file: %s" % source)
    if source.stat().st_size > MAX_MANAGED_READ_BYTES:
        raise MemoryCliUsageError(
            "Capture source exceeds safe read limit: %s" % source,
            reason="raw agent transcripts can be large and privacy-sensitive.",
            fix="split the fixture or pass a smaller public-safe JSONL file.",
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(source, flags)
    except OSError:
        if source.is_symlink():
            raise MemorySecurityError("Capture source may not be a symlink: %s" % source)
        raise
    try:
        opened = os.fstat(fd)
        current = source.stat()
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise MemorySecurityError("Capture source changed during read: %s" % source)
        return os.read(fd, opened.st_size)
    finally:
        os.close(fd)


def _first_present(payload: dict[str, Any], names: tuple[str, ...]) -> object | None:
    for name in names:
        if name in payload and payload[name] is not None:
            return cast(object, payload[name])
    return None


def _summarize_payload(payload: dict[str, Any]) -> tuple[str, list[str], str, str]:
    excluded = []
    redacted = False
    neutralized = False
    pieces = []
    for key in sorted(payload):
        lowered = key.lower()
        if lowered in SENSITIVE_FIELDS:
            excluded.append("%s: excluded sensitive/runtime field" % key)
            continue
        value = payload[key]
        if key in SUMMARY_FIELDS and isinstance(value, (str, int, float, bool)):
            text, changed, was_neutralized = _safe_text(value)
            redacted = redacted or changed
            neutralized = neutralized or was_neutralized
            if text:
                pieces.append(text)
        elif isinstance(value, (dict, list)):
            excluded.append("%s: excluded structured field" % key)
    if not pieces:
        pieces.append("(metadata-only capture)")
    summary = " | ".join(pieces)
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS].rstrip() + "..."
    return (
        summary,
        excluded,
        "redacted" if redacted else "clean",
        "neutralized" if neutralized else "clean",
    )


def normalize_event(
    payload: dict[str, Any],
    *,
    adapter: str,
    source: Path,
    source_hash: str,
    line_hash: str,
    event_id: int,
    scope: str,
) -> CaptureRow:
    event_type = _first_present(payload, ("event_type", "type", "hook_event_name", "name"))
    event_ts = _first_present(payload, ("timestamp", "ts", "created_at", "time"))
    session_id = _first_present(payload, ("session_id", "sessionId", "conversation_id"))
    project_ref = _first_present(payload, ("project_root", "cwd", "workspace", "project_id"))
    project_text = None
    project_redacted = False
    project_neutralized = False
    if project_ref is not None:
        project_text, project_redacted, project_neutralized = _project_identifier(project_ref)
    summary, excluded, redaction_status, neutralization_status = _summarize_payload(payload)
    if project_redacted:
        redaction_status = "redacted"
    if project_neutralized:
        neutralization_status = "neutralized"
    warnings = []
    if adapter not in {"generic-jsonl", "codex", "claude-code"}:
        warnings.append("unknown adapter; parsed as generic-jsonl")
    return CaptureRow(
        adapter=adapter,
        adapter_version=ADAPTER_VERSION,
        source=_source_identifier(source),
        source_hash=source_hash,
        line_hash=line_hash,
        event_id=event_id,
        event_type=str(event_type or "unknown")[:120],
        event_ts=str(event_ts)[:120] if event_ts is not None else None,
        session_id=str(session_id)[:160] if session_id is not None else None,
        project_ref=project_text,
        scope=scope,
        payload_summary=summary,
        redaction_status=redaction_status,
        neutralization_status=neutralization_status,
        excluded_fields=excluded,
        warnings=warnings,
    )


def ingest_capture(
    *,
    source: str | Path,
    adapter: str = "generic-jsonl",
    project_root: str | Path | None = None,
    global_root: str | Path | None = None,
    scope: str = "project",
    write: bool = False,
    reason: str | None = None,
    allow_global: bool = False,
    limit: int = MAX_EVENTS,
) -> dict[str, Any]:
    if scope not in {"project", "global"}:
        raise MemoryCliUsageError("scope must be project or global")
    if write and not reason:
        raise MemoryCliUsageError(
            "--reason is required with --write",
            reason="pending capture writes are auditable evidence-staging writes.",
            fix="add --reason describing why this public-safe capture is being staged.",
        )
    if write and scope == "global" and not allow_global:
        raise MemorySecurityError(
            "global capture writes require --allow-global",
            reason="global memory roots are shared across projects.",
            fix="retry with --allow-global only after confirming the capture belongs globally.",
        )
    source_path = Path(source).expanduser()
    raw = _read_source_bytes(source_path)
    source_hash = hashlib.sha256(raw).hexdigest()
    rows: list[CaptureRow] = []
    parse_warnings: list[str] = []
    for event_id, raw_line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if event_id > limit:
            parse_warnings.append("capture limit reached at %s rows" % limit)
            break
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            parse_warnings.append("line %s skipped: invalid JSON (%s)" % (event_id, exc.msg))
            continue
        if not isinstance(payload, dict):
            parse_warnings.append("line %s skipped: event must be an object" % event_id)
            continue
        rows.append(
            normalize_event(
                payload,
                adapter=adapter,
                source=source_path,
                source_hash=source_hash,
                line_hash=hashlib.sha256(raw_line.encode("utf-8")).hexdigest(),
                event_id=event_id,
                scope=scope,
            )
        )

    root = (
        Path(global_root or Path.home() / ".agent_memory" / "global").expanduser()
        if scope == "global"
        else Path(project_root or Path.cwd() / ".agent_memory" / "project").expanduser()
    )
    pending_path = root / "_pending" / PENDING_CAPTURE_FILE
    payload = {
        "dry_run": not write,
        "write": write,
        "adapter": adapter,
        "adapter_version": ADAPTER_VERSION,
        "scope": scope,
        "source": _source_identifier(source_path),
        "source_hash": source_hash,
        "captured": len(rows),
        "warnings": parse_warnings,
        "affected_paths": [str(pending_path)] if write and rows else [],
        "rows": [asdict(row) for row in rows],
    }
    if not write:
        return payload

    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=True,
    )
    with store._file_lock():
        for row in rows:
            store._append_text_unlocked(
                pending_path,
                json.dumps(store._sanitize_json(asdict(row)), ensure_ascii=False) + "\n",
            )
    store.append_audit(
        AuditEntry(
            ts=datetime.now().astimezone().isoformat(timespec="seconds"),
            action="capture_ingest",
            target_kind="pending_capture",
            target_id=PENDING_CAPTURE_FILE,
            reason=reason or "",
            dry_run=False,
            details={
                "adapter": adapter,
                "scope": scope,
                "source_hash": source_hash,
                "captured": len(rows),
                "pending_path": str(pending_path),
            },
        )
    )
    return payload


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Capture Ingest",
        "",
        "Mode: %s" % ("dry-run" if payload["dry_run"] else "write"),
        "Adapter: %s" % payload["adapter"],
        "Scope: %s" % payload["scope"],
        "Captured: %s" % payload["captured"],
        "Source hash: %s" % payload["source_hash"][:16],
    ]
    for warning in payload.get("warnings", []):
        lines.append("Warning: %s" % warning)
    if payload.get("affected_paths"):
        lines.append("Affected paths:")
        lines.extend("- %s" % path for path in payload["affected_paths"])
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import public-safe agent lifecycle JSONL into a pending capture queue."
    )
    parser.add_argument("--source", required=True, help="JSONL lifecycle/transcript fixture.")
    parser.add_argument(
        "--adapter",
        choices=("generic-jsonl", "codex", "claude-code"),
        default="generic-jsonl",
    )
    parser.add_argument(
        "--project-root",
        default=str(Path.cwd() / ".agent_memory" / "project"),
        help="Project memory root for pending captures.",
    )
    parser.add_argument(
        "--global-root",
        default=str(Path.home() / ".agent_memory" / "global"),
        help="Global memory root; writes require --allow-global.",
    )
    parser.add_argument("--scope", choices=("project", "global"), default="project")
    parser.add_argument("--write", action="store_true", help="Append rows to _pending/session_captures.jsonl.")
    parser.add_argument("--reason", help="Required when --write is used.")
    parser.add_argument("--allow-global", action="store_true", help="Permit --write --scope global.")
    parser.add_argument("--limit", type=int, default=MAX_EVENTS)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = ingest_capture(
            source=args.source,
            adapter=args.adapter,
            project_root=args.project_root,
            global_root=args.global_root,
            scope=args.scope,
            write=args.write,
            reason=args.reason,
            allow_global=args.allow_global,
            limit=args.limit,
        )
    except (OSError, UnicodeDecodeError, ValueError, MemorySecurityError, MemoryCliUsageError) as exc:
        print(format_cli_error(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
