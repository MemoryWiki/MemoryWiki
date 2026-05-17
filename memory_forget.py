from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys

from memory_system.models import AuditEntry
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore


def build_store(root: Path, scope: str, *, create: bool = True) -> ScopedMemoryStore | None:
    root = root.expanduser()
    if not root.exists():
        if not create:
            return None
    elif root.is_symlink() or not root.is_dir():
        raise ValueError("Memory root must be a real directory: %s" % root)
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=True,
    )


def target_path(store: ScopedMemoryStore, kind: str, identifier: str) -> Path:
    return target_path_for_paths(store.paths, kind, identifier)


def target_path_for_paths(paths: MemoryScopePaths, kind: str, identifier: str) -> Path:
    if kind == "semantic":
        return paths.semantic_file(identifier)
    if kind == "procedure":
        return paths.procedure_file(identifier)
    if kind == "session":
        return paths.session_file(identifier)
    if kind == "episode":
        return paths.episode_for_date(identifier)
    raise ValueError("Unsupported memory kind: %s" % kind)


def delete_target(store: ScopedMemoryStore, path: Path) -> bool:
    with store._file_lock():
        store._assert_safe_managed_path(path)
        if not path.exists():
            return False
        if not path.is_file():
            raise ValueError("Forget target must be a file: %s" % path)
        path.unlink()
        store._mark_index_dirty_unlocked()
        return True


def forget(args) -> dict:
    if not args.reason or not args.reason.strip():
        raise ValueError("--reason is required for forget operations")
    root = Path(args.root).expanduser()
    store = build_store(root, args.scope, create=bool(args.apply))
    if store is None:
        paths = MemoryScopePaths.from_root(root, scope=args.scope)
        path = target_path_for_paths(paths, args.kind, args.id)
        exists = False
        relative_path = str(path.relative_to(paths.root))
    else:
        path = target_path(store, args.kind, args.id)
        store._assert_safe_managed_path(path)
        exists = path.exists() and path.is_file()
        relative_path = str(path.relative_to(store.paths.root))
    deleted = False
    if args.apply:
        assert store is not None
        deleted = delete_target(store, path)
    entry = AuditEntry(
        ts=datetime.now().astimezone().isoformat(timespec="seconds"),
        action="forget",
        target_kind=args.kind,
        target_id=args.id,
        reason=args.reason,
        dry_run=not args.apply,
        details={
            "path": relative_path,
            "existed": exists,
            "deleted": deleted,
        },
    )
    if args.apply:
        assert store is not None
        store.append_audit(entry)
    return {
        "target_kind": args.kind,
        "target_id": args.id,
        "dry_run": not args.apply,
        "existed": exists,
        "deleted": deleted,
        "audit": asdict(entry),
    }


def render_human(payload: dict) -> str:
    mode = "DRY RUN" if payload["dry_run"] else "APPLIED"
    status = "deleted" if payload["deleted"] else "not deleted"
    return (
        "%s forget %s/%s: %s\n"
        % (mode, payload["target_kind"], payload["target_id"], status)
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Forget a local memory item with dry-run and audit logging."
    )
    parser.add_argument("--root", required=True, help="Memory root")
    parser.add_argument("--scope", choices=("project", "global"), default="project")
    parser.add_argument(
        "--kind",
        choices=("semantic", "procedure", "session", "episode"),
        required=True,
        help="Memory kind to forget",
    )
    parser.add_argument("--id", required=True, help="Target memory identifier")
    parser.add_argument("--reason", help="Required reason for audit log")
    parser.add_argument("--apply", action="store_true", help="Actually delete target")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = forget(args)
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
