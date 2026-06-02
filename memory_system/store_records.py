"""Append-only record helpers for history, sessions, tokens, and audit logs."""

from __future__ import annotations

import json
from dataclasses import asdict
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from memory_system.models import AuditEntry, ChatMessage, SessionSummary, TokenUsage


def append_history(store: Any, message: ChatMessage) -> None:
    row = asdict(message)
    row["content"] = store._sanitize(row["content"])
    store._append_jsonl(store.paths.history, row)


def append_token_usage(store: Any, usage: TokenUsage) -> None:
    store._append_jsonl(store.paths.tokens, asdict(usage))


def append_audit(store: Any, entry: AuditEntry) -> None:
    row = asdict(entry)
    row["ts"] = store._sanitize(str(row["ts"]))
    row["action"] = store._sanitize(str(row["action"]))
    row["target_kind"] = store._sanitize(str(row["target_kind"]))
    row["target_id"] = store._sanitize(str(row["target_id"]))
    row["reason"] = store._sanitize(str(row["reason"]))
    row["dry_run"] = bool(row["dry_run"])
    row["details"] = store._sanitize_json(row.get("details", {}))
    store._append_jsonl(store.paths.audit_log, row)


def append_source_ingest(store: Any, row: dict) -> None:
    store._append_jsonl(store.paths.source_ingest_log, store._sanitize_json(row))


def list_source_documents(store: Any, limit: int = 100) -> list[Path]:
    limit = store._safe_file_limit(limit, default=100)
    try:
        store._assert_safe_managed_path(store.paths.sources_dir)
    except ValueError:
        return []
    if (
        not store.paths.sources_dir.exists()
        or not store.paths.sources_dir.is_dir()
        or store.paths.sources_dir.is_symlink()
    ):
        return []
    safe_paths = []
    for path in sorted(store.paths.sources_dir.rglob("*")):
        if not store._is_safe_readable_file(path):
            continue
        safe_paths.append(path)
        if len(safe_paths) >= limit:
            break
    return safe_paths


def read_audit(store: Any, limit: int = 100) -> list[AuditEntry]:
    rows: list[AuditEntry] = []
    if not store.paths.audit_log.exists():
        return rows
    try:
        lines = store._read_lines_bounded(store.paths.audit_log)
    except ValueError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            details = payload.get("details", {})
            if not isinstance(details, dict):
                details = {}
            rows.append(
                AuditEntry(
                    ts=store._sanitize(str(payload["ts"])),
                    action=store._sanitize(str(payload["action"])),
                    target_kind=store._sanitize(str(payload["target_kind"])),
                    target_id=store._sanitize(str(payload["target_id"])),
                    reason=store._sanitize(str(payload.get("reason", ""))),
                    dry_run=bool(payload.get("dry_run", False)),
                    details=store._sanitize_json(details),
                )
            )
        except (JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return rows[-limit:]


def append_session_summary(store: Any, summary: SessionSummary) -> None:
    row = asdict(summary)
    row["summary"] = store._sanitize(str(row["summary"]))
    row["key_points"] = [store._sanitize(str(item)) for item in row["key_points"]]
    row["actions_taken"] = [store._sanitize(str(item)) for item in row["actions_taken"]]
    row["pending_tasks"] = [store._sanitize(str(item)) for item in row["pending_tasks"]]
    store._append_jsonl(store.paths.sessions, row)


def read_session_summaries(store: Any, limit: int = 10) -> list[SessionSummary]:
    rows: list[SessionSummary] = []
    if not store.paths.sessions.exists():
        return rows
    try:
        lines = store._read_lines_bounded(store.paths.sessions)
    except ValueError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            rows.append(
                SessionSummary(
                    ts=store._sanitize(str(payload["ts"])),
                    session_id=store._sanitize(str(payload["session_id"])),
                    summary=store._sanitize(str(payload["summary"])),
                    key_points=[
                        store._sanitize(item)
                        for item in store._safe_string_list(
                            payload.get("key_points", [])
                        )
                    ],
                    actions_taken=[
                        store._sanitize(item)
                        for item in store._safe_string_list(
                            payload.get("actions_taken", [])
                        )
                    ],
                    pending_tasks=[
                        store._sanitize(item)
                        for item in store._safe_string_list(
                            payload.get("pending_tasks", [])
                        )
                    ],
                )
            )
        except (JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda row: row.ts, reverse=True)
    return rows[:limit]
