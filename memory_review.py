from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
from typing import Any

from memory_crystallize_candidates import QUEUE_NAME
from memory_feedback import LEDGER_NAME
from memory_health import run_health
from memory_lifecycle import run_lifecycle
from memory_system.models import AuditEntry, ProceduralMemory, SemanticMemory, SourceRef
from memory_system.paths import MemoryScopePaths
from memory_system.sanitizer import sanitize_text
from memory_system.store import ScopedMemoryStore


MAX_JSONL_BYTES = 2_000_000
MAX_REVIEW_ROWS = 500
GOLDEN_CANDIDATES_NAME = "golden_eval_candidates.jsonl"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_store(root: str | Path, scope: str = "project") -> ScopedMemoryStore:
    path = Path(root).expanduser()
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise ValueError("Memory root must be a real directory: %s" % path)
    cursor = path
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError("Memory root may not be below a symlink: %s" % cursor)
    for parent in cursor.parents:
        if parent.is_symlink():
            raise ValueError("Memory root may not be below a symlink: %s" % parent)
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(path, scope),
        sanitize_on_write=True,
        secure_permissions=True,
    )


def _read_jsonl(path: Path, *, root: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        raise ValueError("Review ledger must stay below memory root: %s" % path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Review ledger must be a real file: %s" % path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        size = os.fstat(fd).st_size
        if size > MAX_JSONL_BYTES:
            raise ValueError("Review ledger exceeds safe read limit: %s" % path)
        raw = os.read(fd, size).decode("utf-8")
    finally:
        os.close(fd)
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines()[-MAX_REVIEW_ROWS:]:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(_clean_json(payload))
    return rows


def _clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {sanitize_text(str(k))[:120]: _clean_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_json(item) for item in value[:50]]
    if isinstance(value, str):
        return sanitize_text(value)[:5000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return sanitize_text(str(value))[:5000]


def _selected_roots(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str,
) -> list[tuple[str, Path]]:
    roots = []
    if scope in ("all", "global"):
        roots.append(("global", Path(global_root).expanduser()))
    if scope in ("all", "project"):
        roots.append(("project", Path(project_root).expanduser()))
    return roots


def load_feedback_rows(root: str | Path, scope: str) -> list[dict[str, Any]]:
    path = Path(root).expanduser()
    rows = _read_jsonl(path / LEDGER_NAME, root=path)
    for row in rows:
        row["scope"] = scope
        row["root"] = str(path)
    return rows


def load_candidate_rows(root: str | Path, scope: str) -> list[dict[str, Any]]:
    path = Path(root).expanduser()
    rows = _read_jsonl(path / "_pending" / QUEUE_NAME, root=path)
    for row in rows:
        row["scope"] = scope
        row["root"] = str(path)
    return rows


def load_golden_candidate_rows(root: str | Path, scope: str) -> list[dict[str, Any]]:
    path = Path(root).expanduser()
    rows = _read_jsonl(path / "_pending" / GOLDEN_CANDIDATES_NAME, root=path)
    for row in rows:
        row["scope"] = row.get("scope") or scope
        row["root"] = str(path)
    return rows


def _proposal_name(prefix: str, query: str, identifier: str = "") -> str:
    digest = hashlib.sha1(("%s|%s" % (query, identifier)).encode("utf-8")).hexdigest()[:10]
    return "%s-%s" % (prefix, digest)


def golden_proposals_from_feedback(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proposals = []
    seen = set()
    for row in rows:
        if row.get("event") != "recall_feedback":
            continue
        query = sanitize_text(str(row.get("query", ""))).strip()
        if not query:
            continue
        rating = str(row.get("rating", ""))
        hit_identifier = sanitize_text(str(row.get("hit_identifier", ""))).strip()
        if rating == "useful" and hit_identifier:
            expected = [hit_identifier]
            status = "ready"
        elif rating in {"missing", "not-useful"}:
            expected = []
            status = "needs-expected-target"
        else:
            continue
        key = (query, rating, tuple(expected))
        if key in seen:
            continue
        seen.add(key)
        proposals.append(
            {
                "name": _proposal_name("feedback-%s" % rating, query, hit_identifier),
                "query": query,
                "expected": expected,
                "status": status,
                "reason": sanitize_text(str(row.get("reason", ""))).strip(),
                "source_feedback_ts": row.get("ts", ""),
                "scope": row.get("scope", ""),
                "root": row.get("root", ""),
                "hit_scope": row.get("hit_scope", ""),
                "hit_source": row.get("hit_source", ""),
            }
        )
    return proposals


def _inbox_id(category: str, scope: str, target: str, summary: str) -> str:
    digest = hashlib.sha1(
        ("%s|%s|%s|%s" % (category, scope, target, summary)).encode("utf-8")
    ).hexdigest()[:12]
    return "%s-%s" % (category, digest)


def _inbox_item(
    *,
    category: str,
    scope: str,
    severity: str,
    status: str,
    summary: str,
    action: str,
    source: str,
    target: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_summary = sanitize_text(summary).strip()[:500]
    clean_target = sanitize_text(target).strip()[:500]
    clean_scope = sanitize_text(scope).strip()[:40]
    return {
        "id": _inbox_id(category, clean_scope, clean_target, clean_summary),
        "category": category,
        "scope": clean_scope,
        "severity": severity if severity in {"warn", "info"} else "info",
        "status": status,
        "summary": clean_summary,
        "action": sanitize_text(action).strip()[:500],
        "source": sanitize_text(source).strip()[:120],
        "target": clean_target,
        "payload": payload or {},
    }


def build_review_inbox(
    *,
    health_issues: list[dict[str, Any]],
    feedback_rows: list[dict[str, Any]],
    pending_candidates: list[dict[str, Any]],
    golden_proposals: list[dict[str, Any]],
    repair_proposals: list[dict[str, Any]],
    lifecycle_proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    inbox: list[dict[str, Any]] = []
    for issue in health_issues:
        inbox.append(
            _inbox_item(
                category="health",
                scope=str(issue.get("scope", "")),
                severity=str(issue.get("severity", "info")),
                status="open",
                summary="%s: %s" % (issue.get("code", ""), issue.get("message", "")),
                action="review health issue and apply an explicit repair if appropriate",
                source="memory_health",
                target=str(issue.get("target", "")),
                payload=issue,
            )
        )
    for row in feedback_rows:
        rating = str(row.get("rating", ""))
        severity = "warn" if rating in {"missing", "not-useful"} else "info"
        inbox.append(
            _inbox_item(
                category="feedback",
                scope=str(row.get("scope", "")),
                severity=severity,
                status="open",
                summary="%s feedback for query: %s"
                % (rating or str(row.get("event", "")), row.get("query", "")),
                action="review feedback; use explicit golden candidate write if it should become eval coverage",
                source="memory_feedback",
                target=str(row.get("hit_identifier", "")),
                payload=row,
            )
        )
    for candidate in pending_candidates:
        inbox.append(
            _inbox_item(
                category="crystallize-candidate",
                scope=str(candidate.get("scope", "")),
                severity="info",
                status="pending",
                summary="%s candidate: %s"
                % (candidate.get("kind", "memory"), candidate.get("title", "")),
                action="review candidate; apply only with --apply-candidate and --write",
                source="memory_crystallize_candidates",
                target=str(candidate.get("id", "")),
                payload=candidate,
            )
        )
    for proposal in golden_proposals:
        status = str(proposal.get("status", ""))
        inbox.append(
            _inbox_item(
                category="golden-eval",
                scope=str(proposal.get("scope", "")),
                severity="warn" if status != "ready" else "info",
                status=status or "proposed",
                summary="Golden candidate %s: %s"
                % (proposal.get("name", ""), proposal.get("query", "")),
                action=(
                    "fill expected target before adding to golden eval"
                    if status != "ready"
                    else "write pending golden candidate only if explicitly requested"
                ),
                source="memory_review",
                target=str(proposal.get("name", "")),
                payload=proposal,
            )
        )
    for proposal in repair_proposals:
        inbox.append(
            _inbox_item(
                category="health-repair",
                scope=str(proposal.get("scope", "")),
                severity=str(proposal.get("severity", "info")),
                status="dry-run",
                summary="%s for %s"
                % (proposal.get("action", ""), proposal.get("target", "")),
                action=str(proposal.get("action", "")),
                source="memory_review",
                target=str(proposal.get("target", "")),
                payload=proposal,
            )
        )
    for proposal in lifecycle_proposals:
        target = str(proposal.get("ledger") or proposal.get("backup_name") or "")
        severity = (
            "warn"
            if str(proposal.get("code", "")).endswith(("large", "needed", "stale"))
            else "info"
        )
        inbox.append(
            _inbox_item(
                category="lifecycle",
                scope=str(proposal.get("scope", "")),
                severity=severity,
                status="proposed",
                summary="%s for %s" % (proposal.get("code", ""), target),
                action=str(proposal.get("action", "")),
                source="memory_lifecycle",
                target=target,
                payload=proposal,
            )
        )
    severity_rank = {"warn": 0, "info": 1}
    inbox.sort(
        key=lambda item: (
            severity_rank.get(item["severity"], 9),
            item["category"],
            item["scope"],
            item["target"],
        )
    )
    return inbox


def _assert_safe_pending_file(root: Path, filename: str) -> Path:
    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        raise ValueError("Invalid pending filename: %s" % filename)
    pending = root / "_pending"
    if pending.exists() and (pending.is_symlink() or not pending.is_dir()):
        raise ValueError("Pending directory must be a real directory: %s" % pending)
    cursor = pending
    checked = []
    while cursor != cursor.parent:
        checked.append(cursor)
        if cursor == root:
            break
        cursor = cursor.parent
    root_resolved = root.resolve(strict=False)
    for item in checked:
        if item.exists() and item.is_symlink():
            raise ValueError("Pending path may not include symlinks: %s" % item)
        try:
            item.resolve(strict=False).relative_to(root_resolved)
        except ValueError:
            raise ValueError("Pending path must stay below memory root: %s" % pending)
    return pending / filename


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("Review write target must be a real file: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError("Review write directory must be a real directory: %s" % path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(
            fd,
            (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
    finally:
        os.close(fd)


def _golden_candidate_key(row: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    expected = row.get("expected", [])
    if not isinstance(expected, list):
        expected = []
    return (
        str(row.get("name", "")),
        str(row.get("query", "")),
        tuple(str(item) for item in expected),
    )


def write_golden_candidates_to_pending(
    *,
    project_root: str | Path,
    global_root: str | Path,
    proposals: list[dict[str, Any]],
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or _now()
    root_by_scope = {
        "project": Path(project_root).expanduser(),
        "global": Path(global_root).expanduser(),
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for proposal in proposals:
        scope = str(proposal.get("scope") or "project")
        grouped.setdefault(scope, []).append(proposal)
    written_rows: list[dict[str, Any]] = []
    skipped = 0
    paths: list[str] = []
    for scope, scope_proposals in grouped.items():
        root = root_by_scope.get(scope)
        if root is None:
            skipped += len(scope_proposals)
            continue
        store = _safe_store(root, scope)
        root = store.paths.root
        path = _assert_safe_pending_file(root, GOLDEN_CANDIDATES_NAME)
        existing_rows = _read_jsonl(path, root=root)
        seen = {
            _golden_candidate_key(row)
            for row in existing_rows
            if row.get("event") == "golden_eval_candidate"
        }
        for proposal in scope_proposals:
            row = {
                "ts": timestamp,
                "event": "golden_eval_candidate",
                "name": proposal.get("name", ""),
                "query": proposal.get("query", ""),
                "expected": proposal.get("expected", []),
                "status": proposal.get("status", ""),
                "reason": proposal.get("reason", ""),
                "source_feedback_ts": proposal.get("source_feedback_ts", ""),
                "scope": scope,
                "hit_scope": proposal.get("hit_scope", ""),
                "hit_source": proposal.get("hit_source", ""),
                "source": "retrieval_feedback",
            }
            key = _golden_candidate_key(row)
            if key in seen:
                skipped += 1
                continue
            _append_jsonl(path, _clean_json(row))
            seen.add(key)
            written_rows.append(row)
        try:
            paths.append(path.relative_to(root).as_posix())
        except ValueError:
            paths.append(str(path))
    return {
        "written": len(written_rows),
        "skipped": skipped,
        "paths": sorted(set(paths)),
        "rows": written_rows,
    }


def _candidate_expected(candidate: dict[str, Any]) -> list[str]:
    expected = candidate.get("expected", [])
    if isinstance(expected, str):
        expected = [expected]
    if not isinstance(expected, list):
        return []
    return [sanitize_text(str(item)).strip() for item in expected if str(item).strip()]


def _candidate_identity(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("scope") or "project"), str(row.get("name", "")))


def _append_golden_lifecycle_audit(
    *,
    root: str | Path,
    scope: str,
    action: str,
    candidate_name: str,
    reason: str,
    details: dict[str, Any] | None = None,
    now: str | None = None,
) -> None:
    store = _safe_store(root, scope)
    store.append_audit(
        AuditEntry(
            ts=now or _now(),
            action=action,
            target_kind="golden-eval-candidate",
            target_id=sanitize_text(candidate_name).strip()[:240],
            reason=sanitize_text(reason).strip()[:500] or "Explicit golden eval lifecycle action",
            dry_run=False,
            details=_clean_json(details or {}),
        )
    )


def summarize_golden_candidate_backlog(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str = "all",
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for selected_scope, root in _selected_roots(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
    ):
        rows.extend(load_golden_candidate_rows(root, selected_scope))
    promoted = {
        _candidate_identity(row)
        for row in rows
        if row.get("event") == "golden_eval_candidate_promoted"
    }
    rejected = {
        _candidate_identity(row)
        for row in rows
        if row.get("event") == "golden_eval_candidate_rejected"
    }
    candidates = [
        row
        for row in rows
        if row.get("event") == "golden_eval_candidate"
        and _candidate_identity(row) not in promoted
        and _candidate_identity(row) not in rejected
    ]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in candidates:
        key = _candidate_identity(row)
        grouped.setdefault(key, []).append(row)
    unique_candidates = [rows_for_key[-1] for rows_for_key in grouped.values()]
    ready = [
        row
        for row in unique_candidates
        if row.get("status") == "ready" and _candidate_expected(row)
    ]
    needs_expected = [
        row
        for row in unique_candidates
        if row.get("status") != "ready" or not _candidate_expected(row)
    ]
    duplicate_count = sum(max(0, len(rows_for_key) - 1) for rows_for_key in grouped.values())
    return {
        "status": "review" if unique_candidates else "ok",
        "candidate_count": len(unique_candidates),
        "ready_count": len(ready),
        "needs_expected_count": len(needs_expected),
        "duplicate_count": duplicate_count,
        "promoted_count": len(promoted),
        "rejected_count": len(rejected),
        "candidates": unique_candidates[:50],
        "ready": ready[:50],
        "needs_expected": needs_expected[:50],
    }


def _command(*parts: object) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts if str(part))


def golden_candidate_action_guidance(
    *,
    backlog: dict[str, Any],
    project_root: str | Path,
    global_root: str | Path,
    golden_case_registry: str | Path | None = None,
) -> dict[str, Any]:
    project = Path(project_root).expanduser()
    global_mem = Path(global_root).expanduser()
    registry = (
        Path(golden_case_registry).expanduser()
        if golden_case_registry
        else Path(__file__).resolve().parent / "docs" / "memorywiki-golden-cases.json"
    )
    ready = []
    needs_expected = []
    for candidate in backlog.get("ready", [])[:10]:
        name = sanitize_text(str(candidate.get("name", ""))).strip()
        target_scope = sanitize_text(str(candidate.get("scope") or "project")).strip()
        if target_scope not in {"project", "global"}:
            target_scope = "project"
        ready.append(
            {
                "name": name,
                "query": candidate.get("query", ""),
                "command": _command(
                    "memory_review.py",
                    "--project-root",
                    project,
                    "--global-root",
                    global_mem,
                    "--scope",
                    "all",
                    "--promote-golden-candidate",
                    name,
                    "--golden-case-registry",
                    registry,
                    "--golden-target-scope",
                    target_scope,
                    "--write",
                ),
                "note": "review the expected target before promoting this ready candidate",
            }
        )
    for candidate in backlog.get("needs_expected", [])[:10]:
        name = sanitize_text(str(candidate.get("name", ""))).strip()
        needs_expected.append(
            {
                "name": name,
                "query": candidate.get("query", ""),
                "command": _command(
                    "memory_review.py",
                    "--project-root",
                    project,
                    "--global-root",
                    global_mem,
                    "--scope",
                    "all",
                    "--fill-golden-candidate",
                    name,
                    "--expected",
                    "<target>",
                    "--golden-reason",
                    "<reason>",
                    "--write",
                ),
                "note": "fill exactly one expected target, or reject if the feedback is too noisy",
            }
        )
    return {
        "ready": ready,
        "needs_expected": needs_expected,
        "reject_template": _command(
            "memory_review.py",
            "--project-root",
            project,
            "--global-root",
            global_mem,
            "--scope",
            "all",
            "--reject-golden-candidate",
            "<name>",
            "--golden-reason",
            "<reason>",
            "--write",
        ),
    }


def _safe_registry_path(path: str | Path) -> Path:
    registry = Path(path).expanduser()
    if registry.exists() and (registry.is_symlink() or not registry.is_file()):
        raise ValueError("Golden case registry must be a real file: %s" % registry)
    cursor = registry.parent
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError("Golden case registry may not be below a symlink: %s" % cursor)
    for parent in cursor.parents:
        if parent.is_symlink():
            raise ValueError("Golden case registry may not be below a symlink: %s" % parent)
    return registry


def _read_case_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "global": [], "projects": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {"version": 1, "global": payload, "projects": {}}
    if not isinstance(payload, dict):
        raise ValueError("Golden case registry must be a JSON object or list")
    payload.setdefault("version", 1)
    payload.setdefault("global", [])
    payload.setdefault("projects", {})
    if not isinstance(payload["global"], list) or not isinstance(payload["projects"], dict):
        raise ValueError("Golden case registry has invalid global/projects shape")
    return payload


def _write_case_registry(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError("Golden case registry directory must be real: %s" % path.parent)
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists() and tmp.is_symlink():
        raise ValueError("Golden case registry temp path may not be a symlink: %s" % tmp)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(tmp, flags, 0o600)
    try:
        os.write(fd, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _case_from_golden_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    case = {
        "name": sanitize_text(str(candidate.get("name", ""))).strip(),
        "query": sanitize_text(str(candidate.get("query", ""))).strip(),
        "expected": _candidate_expected(candidate),
        "tags": ["feedback"],
    }
    if candidate.get("hit_scope"):
        case["expected_scope"] = sanitize_text(str(candidate.get("hit_scope", ""))).strip()
    if candidate.get("hit_source"):
        case["expected_source"] = sanitize_text(str(candidate.get("hit_source", ""))).strip()
    return case


def _find_golden_candidate(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str,
    candidate_name: str,
) -> dict[str, Any]:
    matches = []
    promoted = set()
    for selected_scope, root in _selected_roots(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
    ):
        for row in load_golden_candidate_rows(root, selected_scope):
            if row.get("event") == "golden_eval_candidate_promoted":
                promoted.add(_candidate_identity(row))
            elif row.get("event") == "golden_eval_candidate_rejected":
                promoted.add(_candidate_identity(row))
            elif row.get("event") == "golden_eval_candidate" and row.get("name") == candidate_name:
                matches.append(row)
    matches = [row for row in matches if _candidate_identity(row) not in promoted]
    if not matches:
        raise ValueError("Golden eval candidate not found: %s" % candidate_name)
    return matches[-1]


def fill_golden_candidate_expected(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str,
    candidate_name: str,
    expected: list[str],
    reason: str = "",
    write: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    candidate = _find_golden_candidate(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
        candidate_name=candidate_name,
    )
    clean_expected = [sanitize_text(str(item)).strip() for item in expected if str(item).strip()]
    if not clean_expected:
        raise ValueError("Expected targets are required to fill a golden eval candidate")
    timestamp = now or _now()
    updated = dict(candidate)
    updated.update(
        {
            "ts": timestamp,
            "event": "golden_eval_candidate",
            "expected": clean_expected,
            "status": "ready",
            "reason": sanitize_text(reason).strip()[:500] or candidate.get("reason", ""),
            "source": "manual-fill",
        }
    )
    payload = {
        "dry_run": not write,
        "candidate_name": candidate_name,
        "candidate": _clean_json(updated),
    }
    if not write:
        return payload
    candidate_scope = str(candidate.get("scope") or "project")
    root = Path(global_root if candidate_scope == "global" else project_root).expanduser()
    store = _safe_store(root, candidate_scope)
    pending_path = _assert_safe_pending_file(store.paths.root, GOLDEN_CANDIDATES_NAME)
    _append_jsonl(pending_path, _clean_json(updated))
    _append_golden_lifecycle_audit(
        root=store.paths.root,
        scope=candidate_scope,
        action="fill_golden_eval_candidate",
        candidate_name=candidate_name,
        reason=reason or "Explicitly filled expected target for golden eval candidate",
        details={
            "expected": clean_expected,
            "pending_path": pending_path.relative_to(store.paths.root).as_posix(),
        },
        now=timestamp,
    )
    payload["dry_run"] = False
    payload["affected_path"] = pending_path.relative_to(store.paths.root).as_posix()
    return payload


def reject_golden_candidate(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str,
    candidate_name: str,
    reason: str,
    write: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    candidate = _find_golden_candidate(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
        candidate_name=candidate_name,
    )
    if not sanitize_text(reason).strip():
        raise ValueError("A reason is required to reject a golden eval candidate")
    payload = {
        "dry_run": not write,
        "candidate_name": candidate_name,
        "reason": sanitize_text(reason).strip()[:500],
    }
    if not write:
        return payload
    timestamp = now or _now()
    candidate_scope = str(candidate.get("scope") or "project")
    root = Path(global_root if candidate_scope == "global" else project_root).expanduser()
    store = _safe_store(root, candidate_scope)
    pending_path = _assert_safe_pending_file(store.paths.root, GOLDEN_CANDIDATES_NAME)
    _append_jsonl(
        pending_path,
        _clean_json(
            {
                "ts": timestamp,
                "event": "golden_eval_candidate_rejected",
                "name": candidate_name,
                "scope": candidate_scope,
                "reason": reason,
            }
        ),
    )
    _append_golden_lifecycle_audit(
        root=store.paths.root,
        scope=candidate_scope,
        action="reject_golden_eval_candidate",
        candidate_name=candidate_name,
        reason=reason,
        details={"pending_path": pending_path.relative_to(store.paths.root).as_posix()},
        now=timestamp,
    )
    payload["dry_run"] = False
    payload["affected_path"] = pending_path.relative_to(store.paths.root).as_posix()
    return payload


def promote_golden_candidate(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str,
    candidate_name: str,
    registry_path: str | Path,
    target_scope: str = "project",
    write: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    if target_scope not in {"project", "global"}:
        raise ValueError("target_scope must be project or global")
    candidate = _find_golden_candidate(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
        candidate_name=candidate_name,
    )
    expected = _candidate_expected(candidate)
    if candidate.get("status") != "ready" or not expected:
        raise ValueError("Golden eval candidate is not ready: %s" % candidate_name)
    registry = _safe_registry_path(registry_path)
    case = _case_from_golden_candidate(candidate)
    project_key = str(Path(project_root).expanduser().resolve())
    section = "global" if target_scope == "global" else project_key
    payload = {
        "dry_run": not write,
        "candidate_name": candidate_name,
        "target_scope": target_scope,
        "registry_path": str(registry),
        "would_write": str(registry),
        "case": case,
        "project_key": project_key if target_scope == "project" else "",
    }
    if not write:
        return payload
    registry_payload = _read_case_registry(registry)
    if target_scope == "global":
        cases = registry_payload["global"]
    else:
        cases = registry_payload["projects"].setdefault(section, [])
        if not isinstance(cases, list):
            raise ValueError("Project registry entry must be a list: %s" % section)
    if not any(item.get("name") == case["name"] for item in cases if isinstance(item, dict)):
        cases.append(case)
        _write_case_registry(registry, registry_payload)
        payload["written"] = True
    else:
        payload["written"] = False
    candidate_scope = str(candidate.get("scope") or "project")
    root = Path(global_root if candidate_scope == "global" else project_root).expanduser()
    store = _safe_store(root, candidate_scope)
    pending_path = _assert_safe_pending_file(store.paths.root, GOLDEN_CANDIDATES_NAME)
    _append_jsonl(
        pending_path,
        _clean_json(
            {
                "ts": now or _now(),
                "event": "golden_eval_candidate_promoted",
                "name": candidate_name,
                "scope": candidate_scope,
                "registry_path": str(registry),
                "target_scope": target_scope,
                "project_key": project_key if target_scope == "project" else "",
            }
        ),
    )
    _append_golden_lifecycle_audit(
        root=store.paths.root,
        scope=candidate_scope,
        action="promote_golden_eval_candidate",
        candidate_name=candidate_name,
        reason="Explicitly promoted pending golden eval candidate",
        details={
            "registry_path": str(registry),
            "target_scope": target_scope,
            "project_key": project_key if target_scope == "project" else "",
            "pending_path": pending_path.relative_to(store.paths.root).as_posix(),
        },
        now=now,
    )
    payload["dry_run"] = False
    payload["promoted_event_path"] = pending_path.relative_to(store.paths.root).as_posix()
    return payload


def repair_proposals_from_health(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = {
        "duplicate-memory": "review-merge-or-forget-duplicate",
        "stale-memory": "review-refresh-or-forget",
        "semantic-conflict-history": "append-resolution-update-log",
        "source-ref-tampered": "verify-source-or-reingest",
        "source-ref-missing": "restore-source-or-remove-ref",
        "source-ref-outside": "remove-or-rewrite-unsafe-source-ref",
        "low-confidence-memory": "review-promote-strengthen-or-forget",
        "hot-file-large": "propose-compact-hot-file",
    }
    proposals = []
    for issue in issues:
        code = str(issue.get("code", ""))
        if code not in actions:
            continue
        proposals.append(
            {
                "id": _proposal_name(code, str(issue.get("target", "")), str(issue.get("message", ""))),
                "kind": "health-repair",
                "action": actions[code],
                "scope": issue.get("scope", ""),
                "target": issue.get("target", ""),
                "issue_code": code,
                "severity": issue.get("severity", ""),
                "message": issue.get("message", ""),
                "dry_run_only": True,
            }
        )
    return proposals


def _candidate_by_id(store: ScopedMemoryStore, candidate_id: str) -> dict[str, Any]:
    rows = load_candidate_rows(store.paths.root, store.paths.scope)
    matches = [row for row in rows if str(row.get("id", "")) == candidate_id]
    if not matches:
        raise ValueError("Candidate not found: %s" % candidate_id)
    return matches[-1]


def _source_ref_from_candidate(candidate: dict[str, Any]) -> SourceRef:
    return SourceRef(
        kind=sanitize_text(str(candidate.get("source_kind", "candidate")))[:64],
        path=sanitize_text(str(candidate.get("source_path", "")))[:1000],
        identifier=sanitize_text(str(candidate.get("source_id", "")))[:500] or None,
        excerpt=None,
    )


def _float_from_candidate(candidate: dict[str, Any], key: str, default: float) -> float:
    try:
        value = float(candidate.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def apply_candidate(
    *,
    root: str | Path,
    candidate_id: str,
    write: bool = False,
    replace: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    store = _safe_store(root, "project")
    candidate = _candidate_by_id(store, candidate_id)
    kind = sanitize_text(str(candidate.get("kind", "semantic"))).strip()
    if kind not in {"semantic", "procedure"}:
        raise ValueError("Unsupported candidate kind: %s" % kind)
    timestamp = now or _now()
    title = sanitize_text(str(candidate.get("title", candidate_id))).strip() or candidate_id
    answer = sanitize_text(str(candidate.get("answer", ""))).strip()
    if not answer:
        raise ValueError("Candidate has no answer/content: %s" % candidate_id)
    source_ref = _source_ref_from_candidate(candidate)
    target_path = "%s/%s.md" % ("semantic" if kind == "semantic" else "procedures", candidate_id)
    if kind == "semantic" and store.read_semantic_memory(candidate_id) is not None and not replace:
        raise ValueError("semantic memory already exists; use --replace: %s" % candidate_id)
    if kind == "procedure" and store.read_procedural_memory(candidate_id) is not None and not replace:
        raise ValueError("procedure already exists; use --replace: %s" % candidate_id)
    if not write:
        return {
            "dry_run": True,
            "candidate_id": candidate_id,
            "kind": kind,
            "would_write": target_path,
            "candidate": candidate,
        }
    if kind == "semantic":
        item = SemanticMemory(
            id=candidate_id,
            scope="project",
            title=title,
            content=answer,
            concepts=[sanitize_text(str(item)) for item in candidate.get("concepts", [])]
            if isinstance(candidate.get("concepts"), list)
            else [],
            source_refs=[source_ref],
            confidence=_float_from_candidate(candidate, "confidence", 0.55),
            strength=_float_from_candidate(candidate, "strength", 0.5),
            last_accessed=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        path = store.write_semantic_memory(item)
    else:
        steps = candidate.get("steps") if isinstance(candidate.get("steps"), list) else []
        clean_steps = [sanitize_text(str(step)).strip() for step in steps if str(step).strip()]
        item = ProceduralMemory(
            id=candidate_id,
            scope="project",
            title=title,
            trigger=answer[:240],
            steps=clean_steps or [answer],
            source_refs=[source_ref],
            confidence=_float_from_candidate(candidate, "confidence", 0.55),
            strength=_float_from_candidate(candidate, "strength", 0.5),
            last_accessed=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        path = store.write_procedural_memory(item)
    store.append_audit(
        AuditEntry(
            ts=timestamp,
            action="apply_crystallize_candidate",
            target_kind=kind,
            target_id=candidate_id,
            reason="Explicit memory_review candidate apply",
            dry_run=False,
            details={
                "candidate_source": candidate.get("source_path", ""),
                "affected_path": path.relative_to(store.paths.root).as_posix(),
            },
        )
    )
    store.refresh_index()
    return {
        "dry_run": False,
        "candidate_id": candidate_id,
        "kind": kind,
        "affected_path": path.relative_to(store.paths.root).as_posix(),
    }


def run_review(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str = "all",
    apply_candidate_id: str | None = None,
    write: bool = False,
    replace: bool = False,
    hot_file_max_bytes: int = 250_000,
    low_confidence: float = 0.4,
    stale_days: int = 365,
    lifecycle_archive_after_days: int = 90,
    lifecycle_max_ledger_bytes: int = 250_000,
    write_golden_candidates: bool = False,
    promote_golden_candidate_name: str | None = None,
    fill_golden_candidate_name: str | None = None,
    fill_golden_expected: list[str] | None = None,
    reject_golden_candidate_name: str | None = None,
    golden_reason: str = "",
    golden_case_registry: str | Path | None = None,
    golden_target_scope: str = "project",
) -> dict[str, Any]:
    health = run_health(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
        hot_file_max_bytes=hot_file_max_bytes,
        low_confidence=low_confidence,
        stale_days=stale_days,
    )
    lifecycle = run_lifecycle(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
        archive_after_days=lifecycle_archive_after_days,
        max_ledger_bytes=lifecycle_max_ledger_bytes,
    )
    feedback_rows = []
    pending_candidates = []
    for selected_scope, root in _selected_roots(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
    ):
        feedback_rows.extend(load_feedback_rows(root, selected_scope))
        pending_candidates.extend(load_candidate_rows(root, selected_scope))
    apply_payload = None
    if apply_candidate_id:
        apply_payload = apply_candidate(
            root=project_root,
            candidate_id=apply_candidate_id,
            write=write,
            replace=replace,
        )
    golden_proposals = golden_proposals_from_feedback(feedback_rows)
    repair_proposals = repair_proposals_from_health(health["issues"])
    golden_candidate_write = {"written": 0, "skipped": 0, "paths": [], "rows": []}
    if write_golden_candidates:
        golden_candidate_write = write_golden_candidates_to_pending(
            project_root=project_root,
            global_root=global_root,
            proposals=golden_proposals,
        )
    golden_candidate_promotion = None
    golden_candidate_fill = None
    golden_candidate_rejection = None
    if fill_golden_candidate_name:
        golden_candidate_fill = fill_golden_candidate_expected(
            project_root=project_root,
            global_root=global_root,
            scope=scope,
            candidate_name=fill_golden_candidate_name,
            expected=fill_golden_expected or [],
            reason=golden_reason,
            write=write,
        )
    if reject_golden_candidate_name:
        golden_candidate_rejection = reject_golden_candidate(
            project_root=project_root,
            global_root=global_root,
            scope=scope,
            candidate_name=reject_golden_candidate_name,
            reason=golden_reason,
            write=write,
        )
    if promote_golden_candidate_name:
        if golden_case_registry is None:
            golden_case_registry = Path(__file__).resolve().parent / "docs" / "memorywiki-golden-cases.json"
        golden_candidate_promotion = promote_golden_candidate(
            project_root=project_root,
            global_root=global_root,
            scope=scope,
            candidate_name=promote_golden_candidate_name,
            registry_path=golden_case_registry,
            target_scope=golden_target_scope,
            write=write,
        )
    golden_candidate_backlog = summarize_golden_candidate_backlog(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
    )
    golden_candidate_actions = golden_candidate_action_guidance(
        backlog=golden_candidate_backlog,
        project_root=project_root,
        global_root=global_root,
        golden_case_registry=golden_case_registry,
    )
    review_inbox = build_review_inbox(
        health_issues=health["issues"],
        feedback_rows=feedback_rows,
        pending_candidates=pending_candidates,
        golden_proposals=golden_proposals,
        repair_proposals=repair_proposals,
        lifecycle_proposals=lifecycle["proposals"],
    )
    review_items = (
        len(review_inbox)
        + golden_candidate_write["written"]
        + (1 if golden_candidate_promotion else 0)
        + (1 if golden_candidate_fill else 0)
        + (1 if golden_candidate_rejection else 0)
    )
    return {
        "status": "review" if review_items or apply_payload else "ok",
        "scope": scope,
        "review_inbox_count": len(review_inbox),
        "review_inbox": review_inbox,
        "health": health,
        "health_issue_count": len(health["issues"]),
        "lifecycle": lifecycle,
        "lifecycle_proposal_count": len(lifecycle["proposals"]),
        "lifecycle_proposals": lifecycle["proposals"],
        "feedback_count": len(feedback_rows),
        "feedback": feedback_rows,
        "pending_candidate_count": len(pending_candidates),
        "pending_candidates": pending_candidates,
        "golden_proposals": golden_proposals,
        "golden_candidate_write": golden_candidate_write,
        "golden_candidate_promotion": golden_candidate_promotion,
        "golden_candidate_fill": golden_candidate_fill,
        "golden_candidate_rejection": golden_candidate_rejection,
        "golden_candidate_backlog": golden_candidate_backlog,
        "golden_candidate_actions": golden_candidate_actions,
        "repair_proposals": repair_proposals,
        "apply": apply_payload,
    }


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Memory Review",
        "",
        "Status: %s" % payload["status"],
        "Health issues: %s" % payload["health_issue_count"],
        "Lifecycle proposals: %s" % payload["lifecycle_proposal_count"],
        "Feedback rows: %s" % payload["feedback_count"],
        "Pending candidates: %s" % payload["pending_candidate_count"],
        "Golden proposals: %s" % len(payload["golden_proposals"]),
        "Golden candidate backlog: %s ready / %s total"
        % (
            payload["golden_candidate_backlog"]["ready_count"],
            payload["golden_candidate_backlog"]["candidate_count"],
        ),
        "Review inbox: %s" % payload["review_inbox_count"],
        "Golden candidate writes: %s" % payload["golden_candidate_write"]["written"],
        "Repair proposals: %s" % len(payload["repair_proposals"]),
        "",
    ]
    if payload["review_inbox"]:
        lines.append("## Review Inbox")
        for item in payload["review_inbox"][:15]:
            lines.append(
                "- [{severity}] {category}/{scope} {target}: {summary}".format(**item)
            )
        lines.append("")
    if payload["pending_candidates"]:
        lines.append("## Pending Candidates")
        for candidate in payload["pending_candidates"][:10]:
            lines.append("- [{kind}] {id}: {title}".format(**candidate))
        lines.append("")
    if payload["golden_proposals"]:
        lines.append("## Golden Eval Proposals")
        for proposal in payload["golden_proposals"][:10]:
            lines.append("- {name}: {query}".format(**proposal))
        lines.append("")
    if payload["golden_candidate_backlog"]["candidates"]:
        lines.append("## Golden Candidate Backlog")
        for candidate in payload["golden_candidate_backlog"]["candidates"][:10]:
            lines.append(
                "- [{status}] {name}: {query}".format(
                    status=candidate.get("status", ""),
                    name=candidate.get("name", ""),
                    query=candidate.get("query", ""),
                )
            )
        lines.append("")
    actions = payload.get("golden_candidate_actions", {})
    if actions.get("ready") or actions.get("needs_expected"):
        lines.append("## Golden Candidate Actions")
        for item in actions.get("ready", []):
            lines.append("- Promote {name}: {command}".format(**item))
        for item in actions.get("needs_expected", []):
            lines.append("- Fill {name}: {command}".format(**item))
        lines.append("- Reject template: %s" % actions.get("reject_template", ""))
        lines.append("")
    if payload["repair_proposals"]:
        lines.append("## Health Repair Proposals")
        for proposal in payload["repair_proposals"][:10]:
            lines.append("- {action}: {target}".format(**proposal))
        lines.append("")
    if payload["lifecycle_proposals"]:
        lines.append("## Lifecycle Proposals")
        for proposal in payload["lifecycle_proposals"][:10]:
            target = proposal.get("ledger") or proposal.get("backup_name", "")
            lines.append("- {code}: {scope} {target}".format(target=target, **proposal))
        lines.append("")
    if payload["apply"]:
        lines.append("## Candidate Apply")
        lines.append(json.dumps(payload["apply"], ensure_ascii=False, indent=2))
    if payload["golden_candidate_promotion"]:
        lines.append("## Golden Candidate Promotion")
        lines.append(
            json.dumps(
                payload["golden_candidate_promotion"],
                ensure_ascii=False,
                indent=2,
            )
        )
    if payload["golden_candidate_fill"]:
        lines.append("## Golden Candidate Fill")
        lines.append(json.dumps(payload["golden_candidate_fill"], ensure_ascii=False, indent=2))
    if payload["golden_candidate_rejection"]:
        lines.append("## Golden Candidate Rejection")
        lines.append(
            json.dumps(payload["golden_candidate_rejection"], ensure_ascii=False, indent=2)
        )
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review MemoryWiki health, feedback, and pending queues.")
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--scope", choices=("all", "project", "global"), default="all")
    parser.add_argument("--apply-candidate", help="Candidate id to apply from project _pending queue.")
    parser.add_argument("--write", action="store_true", help="Explicitly apply the selected candidate.")
    parser.add_argument("--replace", action="store_true", help="Replace an existing target memory item.")
    parser.add_argument(
        "--write-golden-candidates",
        action="store_true",
        help="Explicitly append feedback-derived golden eval candidates to _pending.",
    )
    parser.add_argument("--promote-golden-candidate", help="Promote one pending golden eval candidate by name.")
    parser.add_argument("--fill-golden-candidate", help="Fill expected targets for one pending golden eval candidate.")
    parser.add_argument(
        "--expected",
        action="append",
        default=[],
        help="Expected target for --fill-golden-candidate; may be repeated.",
    )
    parser.add_argument("--reject-golden-candidate", help="Reject one pending golden eval candidate by name.")
    parser.add_argument("--golden-reason", default="", help="Reason for fill/reject golden candidate actions.")
    parser.add_argument(
        "--golden-case-registry",
        default=str(Path(__file__).resolve().parent / "docs" / "memorywiki-golden-cases.json"),
        help="Golden case registry JSON to update when promoting a candidate.",
    )
    parser.add_argument(
        "--golden-target-scope",
        choices=("project", "global"),
        default="project",
        help="Registry section for --promote-golden-candidate.",
    )
    parser.add_argument("--hot-file-max-bytes", type=int, default=250_000)
    parser.add_argument("--low-confidence", type=float, default=0.4)
    parser.add_argument("--stale-days", type=int, default=365)
    parser.add_argument("--lifecycle-archive-after-days", type=int, default=90)
    parser.add_argument("--lifecycle-max-ledger-bytes", type=int, default=250_000)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_review(
            project_root=args.project_root,
            global_root=args.global_root,
            scope=args.scope,
            apply_candidate_id=args.apply_candidate,
            write=args.write,
            replace=args.replace,
            hot_file_max_bytes=args.hot_file_max_bytes,
            low_confidence=args.low_confidence,
            stale_days=args.stale_days,
            lifecycle_archive_after_days=args.lifecycle_archive_after_days,
            lifecycle_max_ledger_bytes=args.lifecycle_max_ledger_bytes,
            write_golden_candidates=args.write_golden_candidates,
            promote_golden_candidate_name=args.promote_golden_candidate,
            fill_golden_candidate_name=args.fill_golden_candidate,
            fill_golden_expected=args.expected,
            reject_golden_candidate_name=args.reject_golden_candidate,
            golden_reason=args.golden_reason,
            golden_case_registry=args.golden_case_registry,
            golden_target_scope=args.golden_target_scope,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
