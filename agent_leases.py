from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import uuid

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


DEFAULT_TTL_SECONDS = 3600
MAX_TASK_CHARS = 500
MAX_AGENT_CHARS = 120
MAX_KIND_CHARS = 80
CONFLICT_FIELDS = {"kind", "agent", "task", "any"}


def _utc_now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _plus_seconds(value: str, seconds: int) -> str:
    return (_parse_time(value) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _safe_root(root: str | Path) -> Path:
    path = Path(root).expanduser()
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise ValueError("Memory root must be a real directory: %s" % path)
    cursor = path
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.is_symlink():
        raise ValueError("Memory root may not be below a symlink: %s" % cursor)
    for ancestor in cursor.parents:
        if ancestor.is_symlink():
            raise ValueError("Memory root may not be below a symlink: %s" % ancestor)
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Memory root must be a real directory: %s" % path)
    return path


def _safe_ledger(root: Path) -> Path:
    directory = root / "agent_slots"
    if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
        raise ValueError("Agent slots path must be a real directory: %s" % directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "leases.jsonl"


@contextmanager
def _lease_lock(root: Path):
    ledger = _safe_ledger(root)
    lock_path = ledger.parent / "leases.lock"
    if lock_path.exists() and lock_path.is_symlink():
        raise ValueError("Lease lock may not be a symlink: %s" % lock_path)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    handle = None
    try:
        handle = os.fdopen(fd, "a+")
        fd = None
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        if handle is not None:
            handle.close()
        elif fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _sanitize(value: str, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _append_record(root: Path, record: dict) -> None:
    ledger = _safe_ledger(root)
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(ledger, flags, 0o600)
    except OSError:
        if ledger.is_symlink():
            raise ValueError("Lease ledger may not be a symlink: %s" % ledger)
        raise
    try:
        os.write(fd, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _read_records(root: Path) -> list[dict]:
    ledger = _safe_ledger(root)
    if not ledger.exists():
        return []
    if ledger.is_symlink():
        raise ValueError("Lease ledger may not be a symlink: %s" % ledger)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(ledger, flags)
    try:
        rows = os.read(fd, min(os.fstat(fd).st_size, 2_000_000)).decode("utf-8")
    finally:
        os.close(fd)
    records = []
    for line in rows.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("lease_id"):
            records.append(payload)
    return records


def _latest_by_lease(records: list[dict]) -> dict[str, dict]:
    latest = {}
    for record in records:
        latest[str(record["lease_id"])] = record
    return latest


def _is_expired(record: dict, now: str) -> bool:
    expires_at = record.get("expires_at")
    if not expires_at:
        return False
    try:
        return _parse_time(expires_at) <= _parse_time(now)
    except ValueError:
        return False


def _find_active_conflict(
    records: list[dict],
    request: dict,
    conflicts_on: str,
    now: str,
) -> dict | None:
    if conflicts_on not in CONFLICT_FIELDS:
        raise ValueError("Unsupported lease conflict field: %s" % conflicts_on)
    for record in _latest_by_lease(records).values():
        if record.get("status") != "active" or _is_expired(record, now):
            continue
        if conflicts_on == "any" or record.get(conflicts_on) == request.get(conflicts_on):
            return record
    return None


def acquire_lease(
    root: str | Path,
    agent: str,
    task: str,
    kind: str = "general",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    pid: int | None = None,
    now: str | None = None,
    exclusive: bool = False,
    conflicts_on: str = "kind",
) -> dict:
    memory_root = _safe_root(root)
    timestamp = now or _utc_now_iso()
    ttl = max(1, int(ttl_seconds))
    record = {
        "lease_id": "lease-%s" % uuid.uuid4().hex[:16],
        "status": "active",
        "agent": _sanitize(agent, MAX_AGENT_CHARS) or "unknown-agent",
        "task": _sanitize(task, MAX_TASK_CHARS) or "unspecified task",
        "kind": _sanitize(kind, MAX_KIND_CHARS) or "general",
        "pid": int(pid) if pid else None,
        "started_at": timestamp,
        "expires_at": _plus_seconds(timestamp, ttl),
        "updated_at": timestamp,
        "reason": "",
    }
    with _lease_lock(memory_root):
        if exclusive:
            conflict = _find_active_conflict(
                _read_records(memory_root),
                request=record,
                conflicts_on=conflicts_on,
                now=timestamp,
            )
            if conflict is not None:
                raise ValueError(
                    "Active lease conflict on %s=%s: %s (%s)"
                    % (
                        conflicts_on,
                        "active lease" if conflicts_on == "any" else record.get(conflicts_on, ""),
                        conflict.get("lease_id", ""),
                        conflict.get("task", ""),
                    )
                )
        _append_record(memory_root, record)
    return record


def release_lease(
    root: str | Path,
    lease_id: str,
    reason: str = "released",
    now: str | None = None,
) -> dict:
    memory_root = _safe_root(root)
    timestamp = now or _utc_now_iso()
    with _lease_lock(memory_root):
        current = _latest_by_lease(_read_records(memory_root)).get(lease_id)
        if current is None:
            raise ValueError("Unknown lease id: %s" % lease_id)
        record = dict(current)
        record.update(
            {
                "status": "released",
                "updated_at": timestamp,
                "released_at": timestamp,
                "reason": _sanitize(reason, MAX_TASK_CHARS),
            }
        )
        _append_record(memory_root, record)
    return record


def cleanup_expired_leases(root: str | Path, now: str | None = None) -> list[dict]:
    memory_root = _safe_root(root)
    timestamp = now or _utc_now_iso()
    cleaned = []
    with _lease_lock(memory_root):
        for record in _latest_by_lease(_read_records(memory_root)).values():
            if record.get("status") != "active" or not _is_expired(record, timestamp):
                continue
            expired = dict(record)
            expired.update(
                {
                    "status": "expired",
                    "updated_at": timestamp,
                    "expired_at": timestamp,
                    "reason": "ttl expired",
                }
            )
            _append_record(memory_root, expired)
            cleaned.append(expired)
    return cleaned


def current_leases(
    root: str | Path,
    include_inactive: bool = False,
    now: str | None = None,
) -> list[dict]:
    memory_root = _safe_root(root)
    timestamp = now or _utc_now_iso()
    leases = []
    for record in _latest_by_lease(_read_records(memory_root)).values():
        effective = dict(record)
        if effective.get("status") == "active" and _is_expired(effective, timestamp):
            effective["status"] = "expired"
        if include_inactive or effective.get("status") == "active":
            leases.append(effective)
    leases.sort(key=lambda item: (item.get("status") != "active", item.get("updated_at", "")))
    return leases


def render_human(leases: list[dict]) -> str:
    if not leases:
        return "No active agent leases.\n"
    lines = ["# Agent Leases", ""]
    for lease in leases:
        lines.append(
            "- `%s` [%s] %s: %s (expires %s)"
            % (
                lease.get("lease_id", ""),
                lease.get("status", ""),
                lease.get("agent", ""),
                lease.get("task", ""),
                lease.get("expires_at", ""),
            )
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track local MemoryWiki agent leases.")
    def add_common_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--root",
            default=argparse.SUPPRESS,
            help="Memory root containing agent_slots/leases.jsonl",
        )
        command_parser.add_argument(
            "--format",
            choices=("human", "json"),
            default=argparse.SUPPRESS,
        )

    parser.add_argument(
        "--root",
        default=str(Path.cwd() / ".agent_memory" / "project"),
        help="Memory root containing agent_slots/leases.jsonl",
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire = subparsers.add_parser("acquire")
    add_common_options(acquire)
    acquire.add_argument("--agent", required=True)
    acquire.add_argument("--task", required=True)
    acquire.add_argument("--kind", default="general")
    acquire.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    acquire.add_argument("--pid", type=int)
    acquire.add_argument("--exclusive", action="store_true")
    acquire.add_argument(
        "--conflicts-on",
        choices=sorted(CONFLICT_FIELDS),
        default="kind",
        help="When --exclusive is set, reject active leases matching this field.",
    )

    release = subparsers.add_parser("release")
    add_common_options(release)
    release.add_argument("--lease-id", required=True)
    release.add_argument("--reason", default="released")

    cleanup = subparsers.add_parser("cleanup")
    add_common_options(cleanup)

    list_cmd = subparsers.add_parser("list")
    add_common_options(list_cmd)
    list_cmd.add_argument("--include-inactive", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "acquire":
            payload = {
                "lease": acquire_lease(
                    root=args.root,
                    agent=args.agent,
                    task=args.task,
                    kind=args.kind,
                    ttl_seconds=args.ttl_seconds,
                    pid=args.pid,
                    exclusive=args.exclusive,
                    conflicts_on=args.conflicts_on,
                )
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        elif args.command == "release":
            payload = {
                "lease": release_lease(
                    root=args.root,
                    lease_id=args.lease_id,
                    reason=args.reason,
                )
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        elif args.command == "cleanup":
            payload = {"expired": cleanup_expired_leases(root=args.root)}
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        else:
            leases = current_leases(
                root=args.root,
                include_inactive=args.include_inactive,
            )
            if args.format == "json":
                text = json.dumps({"leases": leases}, ensure_ascii=False, indent=2) + "\n"
            else:
                text = render_human(leases)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
