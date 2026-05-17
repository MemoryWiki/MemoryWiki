from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from memory_system.sanitizer import sanitize_text


LEDGER_NAMES = ("retrieval_feedback.jsonl", "audit.jsonl", "source_ingest.jsonl")
MAX_LEDGER_READ_BYTES = 2_000_000
DEFAULT_MAX_LEDGER_BYTES = 250_000
DEFAULT_ARCHIVE_AFTER_DAYS = 90
MAX_LEDGER_ROWS = 20_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_now(value: str | None) -> datetime:
    if not value:
        return _now()
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_root(root: str | Path) -> Path:
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
    return path


def _assert_no_symlink_ancestors(path: Path, root: Path) -> None:
    root_resolved = root.resolve(strict=False)
    cursor = path
    checked = []
    while cursor != cursor.parent:
        checked.append(cursor)
        if cursor == root:
            break
        cursor = cursor.parent
    for item in checked:
        if item.exists() and item.is_symlink():
            raise ValueError("Lifecycle path may not include symlinks: %s" % item)
        try:
            item.resolve(strict=False).relative_to(root_resolved)
        except ValueError:
            raise ValueError("Lifecycle path must stay below memory root: %s" % path)


def _safe_ledger_path(root: Path, ledger: str) -> Path:
    if ledger.startswith("/") or "\\" in ledger:
        raise ValueError("Ledger must be a relative MemoryWiki ledger path: %s" % ledger)
    rel = Path(ledger)
    if any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError("Ledger must be a relative MemoryWiki ledger path: %s" % ledger)
    allowed = ledger in LEDGER_NAMES or (
        len(rel.parts) == 2 and rel.parts[0] == "_pending" and rel.name.endswith(".jsonl")
    )
    if not allowed:
        raise ValueError("Unsupported lifecycle ledger: %s" % ledger)
    path = root / rel
    _assert_no_symlink_ancestors(path, root)
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        raise ValueError("Ledger must stay below memory root: %s" % ledger)
    return path


def _safe_archive_name(ledger: str) -> str:
    name = ledger.replace("/", "__")
    return re.sub(r"[^A-Za-z0-9_.-]", "-", name)


def _open_read_no_follow(path: Path) -> tuple[int, bytes]:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("Lifecycle ledger must be a real file: %s" % path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        size = os.fstat(fd).st_size
        if size > MAX_LEDGER_READ_BYTES:
            raise ValueError("Lifecycle ledger exceeds safe read limit: %s" % path)
        raw = os.read(fd, size)
    finally:
        os.close(fd)
    return size, raw


def _read_ledger(root: Path, ledger: str) -> dict[str, Any]:
    path = _safe_ledger_path(root, ledger)
    if not path.exists():
        return {
            "path": path,
            "bytes": 0,
            "rows": [],
            "row_count": 0,
            "invalid_rows": 0,
            "old_rows": [],
            "duplicates": [],
        }
    size, raw = _open_read_no_follow(path)
    rows: list[dict[str, Any]] = []
    invalid_rows = 0
    seen: dict[str, int] = {}
    duplicates: list[int] = []
    for index, line in enumerate(raw.decode("utf-8", errors="replace").splitlines()):
        if not line.strip():
            continue
        if len(rows) >= MAX_LEDGER_ROWS:
            break
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid_rows += 1
            payload = None
        if isinstance(payload, dict):
            clean_payload = _clean_json(payload)
            key = json.dumps(clean_payload, ensure_ascii=False, sort_keys=True)
            if key in seen:
                duplicates.append(index)
            else:
                seen[key] = index
            rows.append(
                {
                    "line": line,
                    "payload": clean_payload,
                    "ts": _parse_ts(clean_payload.get("ts") or clean_payload.get("timestamp")),
                }
            )
        else:
            invalid_rows += 1
            rows.append({"line": line, "payload": None, "ts": None})
    return {
        "path": path,
        "bytes": size,
        "rows": rows,
        "row_count": len(rows),
        "invalid_rows": invalid_rows,
        "duplicates": duplicates,
    }


def _clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {sanitize_text(str(k))[:120]: _clean_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_json(item) for item in value[:100]]
    if isinstance(value, str):
        return sanitize_text(value)[:5000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return sanitize_text(str(value))[:5000]


def _scan_ledgers(root: Path) -> list[str]:
    ledgers = list(LEDGER_NAMES)
    pending = root / "_pending"
    if pending.exists():
        if pending.is_symlink() or not pending.is_dir():
            raise ValueError("_pending must be a real directory: %s" % pending)
        for path in sorted(pending.glob("*.jsonl")):
            if path.is_symlink() or not path.is_file():
                raise ValueError("Pending ledger must be a real file: %s" % path)
            ledgers.append("_pending/%s" % path.name)
    return ledgers


def _ledger_summary(
    *,
    scope: str,
    root: Path,
    ledger: str,
    cutoff: datetime,
    max_ledger_bytes: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = _read_ledger(root, ledger)
    rows = data["rows"]
    old_rows = [row for row in rows if row["ts"] is not None and row["ts"] < cutoff]
    archive = _archive_status(root, ledger)
    summary = {
        "scope": scope,
        "root": str(root),
        "ledger": ledger,
        "bytes": data["bytes"],
        "row_count": data["row_count"],
        "old_row_count": len(old_rows),
        "duplicate_row_count": len(data["duplicates"]),
        "invalid_row_count": data["invalid_rows"],
        "archive": archive,
    }
    proposals: list[dict[str, Any]] = []
    if data["bytes"] > max_ledger_bytes:
        proposals.append(
            {
                "code": "ledger-large",
                "scope": scope,
                "root": str(root),
                "ledger": ledger,
                "bytes": data["bytes"],
                "max_bytes": max_ledger_bytes,
                "action": "review archive candidates before explicit --write rotation",
            }
        )
    if old_rows:
        proposals.append(
            {
                "code": "ledger-old-rows",
                "scope": scope,
                "root": str(root),
                "ledger": ledger,
                "old_row_count": len(old_rows),
                "cutoff": cutoff.isoformat(),
                "action": "archive old rows with --write --apply-scope %s --apply-ledger %s"
                % (scope, ledger),
            }
        )
    if data["duplicates"]:
        proposals.append(
            {
                "code": "ledger-duplicates",
                "scope": scope,
                "root": str(root),
                "ledger": ledger,
                "duplicate_row_count": len(data["duplicates"]),
                "action": "review duplicates; lifecycle does not auto-dedupe without a future explicit policy",
            }
        )
    if data["invalid_rows"]:
        proposals.append(
            {
                "code": "ledger-invalid-rows",
                "scope": scope,
                "root": str(root),
                "ledger": ledger,
                "invalid_row_count": data["invalid_rows"],
                "action": "inspect invalid JSONL rows before any archive",
            }
        )
    return summary, proposals


def _archive_status(root: Path, ledger: str) -> dict[str, Any]:
    archive_root = root / "archive"
    if not archive_root.exists():
        return {"months": [], "latest_mtime": None, "path_count": 0}
    if archive_root.is_symlink() or not archive_root.is_dir():
        raise ValueError("Lifecycle archive must be a real directory: %s" % archive_root)
    safe_name = _safe_archive_name(ledger)
    paths = []
    for month_dir in sorted(archive_root.glob("????-??")):
        if month_dir.is_symlink() or not month_dir.is_dir():
            raise ValueError("Lifecycle archive month must be a real directory: %s" % month_dir)
        path = month_dir / safe_name
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ValueError("Lifecycle archive file must be a real file: %s" % path)
            paths.append(path)
    latest = max((path.stat().st_mtime for path in paths), default=0)
    return {
        "months": [path.parent.name for path in paths],
        "latest_mtime": latest or None,
        "path_count": len(paths),
    }


def _write_text_no_follow(path: Path, text: str, mode: int = 0o600) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError("Lifecycle write target may not be a symlink: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, mode)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def _append_text_no_follow(path: Path, text: str, mode: int = 0o600) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError("Lifecycle write target may not be a symlink: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, mode)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def _archive_ledger(
    *,
    root: Path,
    scope: str,
    ledger: str,
    cutoff: datetime,
    write: bool,
    now: datetime,
) -> dict[str, Any]:
    data = _read_ledger(root, ledger)
    rows = data["rows"]
    archive_rows = [row for row in rows if row["ts"] is not None and row["ts"] < cutoff]
    keep_rows = [row for row in rows if row not in archive_rows]
    by_month: dict[str, list[dict[str, Any]]] = {}
    for row in archive_rows:
        month = row["ts"].strftime("%Y-%m")
        by_month.setdefault(month, []).append(row)
    affected = [
        "archive/%s/%s" % (month, _safe_archive_name(ledger))
        for month in sorted(by_month)
    ]
    payload = {
        "dry_run": not write,
        "scope": scope,
        "root": str(root),
        "ledger": ledger,
        "cutoff": cutoff.isoformat(),
        "archived_row_count": len(archive_rows),
        "remaining_row_count": len(keep_rows),
        "affected_paths": affected,
    }
    if not write or not archive_rows:
        return payload
    archive_root = root / "archive"
    _assert_no_symlink_ancestors(archive_root, root)
    ledger_path = _safe_ledger_path(root, ledger)
    _assert_no_symlink_ancestors(ledger_path, root)
    for month, month_rows in sorted(by_month.items()):
        archive_dir = archive_root / month
        _assert_no_symlink_ancestors(archive_dir, root)
        archive_path = archive_dir / _safe_archive_name(ledger)
        _assert_no_symlink_ancestors(archive_path, root)
        _append_text_no_follow(
            archive_path,
            "".join(row["line"].rstrip("\n") + "\n" for row in month_rows),
        )
        index_line = (
            "- %s: archived %s rows from `%s`; remaining active rows: %s; cutoff: %s\n"
            % (
                now.isoformat(timespec="seconds"),
                len(month_rows),
                ledger,
                len(keep_rows),
                cutoff.isoformat(timespec="seconds"),
            )
        )
        index_path = archive_dir / "INDEX.md"
        if not index_path.exists():
            _write_text_no_follow(index_path, "# MemoryWiki Lifecycle Archive %s\n\n" % month)
        _append_text_no_follow(index_path, index_line, mode=0o644)
    _write_text_no_follow(
        ledger_path,
        "".join(row["line"].rstrip("\n") + "\n" for row in keep_rows),
    )
    return payload


def _selected_roots(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str,
) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    if scope in ("all", "global"):
        roots.append(("global", _safe_root(global_root)))
    if scope in ("all", "project"):
        roots.append(("project", _safe_root(project_root)))
    return roots


def _backup_status(
    *,
    scope: str,
    root: Path,
    backup_root: str | Path | None,
    backup_name: str | None,
    now: datetime,
    max_backup_age_hours: int | None = None,
) -> dict[str, Any] | None:
    if backup_root is None:
        return None
    base = Path(backup_root).expanduser()
    name = backup_name or re.sub(r"[^A-Za-z0-9_.-]", "-", root.name or scope)
    candidates = [
        base / ("%s.git" % name),
        base / ("%s.bundle" % name),
    ]
    if base.exists() and base.is_dir() and not base.is_symlink():
        candidates.extend(sorted(base.glob("%s-*.bundle" % name)))
        candidates.extend(sorted(base.glob("%s-*.git" % name)))
    existing = [path for path in candidates if path.exists() and not path.is_symlink()]
    latest = max((path.stat().st_mtime for path in existing), default=0)
    age_hours = None
    status = "missing"
    if existing:
        age_hours = max(0.0, (now.timestamp() - latest) / 3600)
        if max_backup_age_hours is not None and age_hours > max_backup_age_hours:
            status = "stale"
        else:
            status = "ok"
    return {
        "scope": scope,
        "root": str(root),
        "backup_root": str(base),
        "backup_name": name,
        "status": status,
        "candidates": [str(path) for path in existing],
        "latest_mtime": latest or None,
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "max_backup_age_hours": max_backup_age_hours,
    }


def run_lifecycle(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str = "all",
    archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
    max_ledger_bytes: int = DEFAULT_MAX_LEDGER_BYTES,
    apply_scope: str | None = None,
    apply_ledger: str | None = None,
    write: bool = False,
    backup_root: str | Path | None = None,
    backup_name: str | None = None,
    max_backup_age_hours: int | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _parse_now(now)
    cutoff = timestamp - timedelta(days=archive_after_days)
    if write and (not apply_scope or not apply_ledger):
        raise ValueError("--write requires --apply-scope and --apply-ledger")
    roots = _selected_roots(project_root=project_root, global_root=global_root, scope=scope)
    ledger_summaries: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    backup_payload: dict[str, Any] = {}
    for selected_scope, root in roots:
        for ledger in _scan_ledgers(root):
            summary, ledger_proposals = _ledger_summary(
                scope=selected_scope,
                root=root,
                ledger=ledger,
                cutoff=cutoff,
                max_ledger_bytes=max_ledger_bytes,
            )
            ledger_summaries.append(summary)
            proposals.extend(ledger_proposals)
        backup = _backup_status(
            scope=selected_scope,
            root=root,
            backup_root=backup_root,
            backup_name=backup_name,
            now=timestamp,
            max_backup_age_hours=max_backup_age_hours,
        )
        if backup is not None:
            backup_payload[selected_scope] = backup
            if backup["status"] != "ok":
                code = "backup-snapshot-stale" if backup["status"] == "stale" else "backup-snapshot-needed"
                proposals.append(
                    {
                        "code": code,
                        "scope": selected_scope,
                        "root": str(root),
                        "backup_root": backup["backup_root"],
                        "backup_name": backup["backup_name"],
                        "action": "run memory_backup.py before release or destructive maintenance",
                    }
                )
    apply_payload = None
    if apply_scope or apply_ledger:
        if not apply_scope or not apply_ledger:
            raise ValueError("--apply-scope and --apply-ledger must be provided together")
        matching_roots = [item for item in roots if item[0] == apply_scope]
        if not matching_roots:
            raise ValueError("apply scope is not part of selected scope: %s" % apply_scope)
        apply_payload = _archive_ledger(
            root=matching_roots[0][1],
            scope=apply_scope,
            ledger=apply_ledger,
            cutoff=cutoff,
            write=write,
            now=timestamp,
        )
    return {
        "status": "proposals" if proposals or apply_payload else "ok",
        "scope": scope,
        "generated_at": timestamp.isoformat(timespec="seconds"),
        "archive_after_days": archive_after_days,
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "max_ledger_bytes": max_ledger_bytes,
        "ledger_count": len(ledger_summaries),
        "ledgers": ledger_summaries,
        "proposal_count": len(proposals),
        "proposals": proposals,
        "backup": backup_payload,
        "apply": apply_payload,
    }


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Memory Lifecycle",
        "",
        "Status: %s" % payload["status"],
        "Ledgers scanned: %s" % payload["ledger_count"],
        "Proposals: %s" % payload["proposal_count"],
        "Cutoff: %s" % payload["cutoff"],
        "",
    ]
    if payload["proposals"]:
        lines.append("## Proposals")
        for proposal in payload["proposals"][:20]:
            target = proposal.get("ledger") or proposal.get("backup_name", "")
            lines.append("- {code}: {scope} {target}".format(target=target, **proposal))
        lines.append("")
    if payload["apply"]:
        lines.append("## Apply")
        lines.append(json.dumps(payload["apply"], ensure_ascii=False, indent=2))
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report and explicitly archive MemoryWiki append-only lifecycle ledgers."
    )
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--scope", choices=("all", "project", "global"), default="all")
    parser.add_argument("--archive-after-days", type=int, default=DEFAULT_ARCHIVE_AFTER_DAYS)
    parser.add_argument("--max-ledger-bytes", type=int, default=DEFAULT_MAX_LEDGER_BYTES)
    parser.add_argument("--apply-scope", choices=("project", "global"))
    parser.add_argument("--apply-ledger")
    parser.add_argument("--write", action="store_true", help="Archive the selected old rows.")
    parser.add_argument("--backup-root", help="Optional backup root to verify before release.")
    parser.add_argument("--backup-name", help="Expected backup name below --backup-root.")
    parser.add_argument("--max-backup-age-hours", type=int)
    parser.add_argument(
        "--fail-on-backup-issue",
        action="store_true",
        help="Exit nonzero when an explicit backup check is missing or stale.",
    )
    parser.add_argument("--now", help="Override current time for tests.")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_lifecycle(
            project_root=args.project_root,
            global_root=args.global_root,
            scope=args.scope,
            archive_after_days=args.archive_after_days,
            max_ledger_bytes=args.max_ledger_bytes,
            apply_scope=args.apply_scope,
            apply_ledger=args.apply_ledger,
            write=args.write,
            backup_root=args.backup_root,
            backup_name=args.backup_name,
            max_backup_age_hours=args.max_backup_age_hours,
            now=args.now,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    if args.fail_on_backup_issue and any(
        item.get("status") != "ok" for item in payload.get("backup", {}).values()
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
