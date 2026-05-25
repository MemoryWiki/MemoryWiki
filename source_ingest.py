from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from memory_system.models import ProceduralMemory, SemanticMemory, SourceRef
from memory_system.sanitizer import sanitize_text
from memory_system.store import ScopedMemoryStore
from memory_system.store_guard import build_scoped_store

MAX_SOURCE_BYTES = 2_000_000


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _resolve_source(store: ScopedMemoryStore, source: str) -> Path:
    sources_dir = store.paths.sources_dir
    if not sources_dir.exists() or sources_dir.is_symlink() or not sources_dir.is_dir():
        raise ValueError(f"sources/ must be a real directory: {sources_dir}")
    candidate = Path(source).expanduser()
    if not candidate.is_absolute():
        candidate = sources_dir / candidate
    _assert_no_symlink_components(candidate, sources_dir)
    try:
        resolved_source = candidate.resolve(strict=True)
        resolved_root = sources_dir.resolve(strict=True)
        resolved_source.relative_to(resolved_root)
    except (OSError, ValueError):
        raise ValueError(f"Source must stay below sources/: {source}")
    if not resolved_source.is_file():
        raise ValueError(f"Source document must be a file: {candidate}")
    if resolved_source.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError(f"Source document is too large: {candidate}")
    return resolved_source


def _assert_no_symlink_components(path: Path, root: Path) -> None:
    cursor = path
    root_resolved = root.resolve(strict=True)
    checked = []
    while True:
        checked.append(cursor)
        if cursor == root:
            break
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    for item in checked:
        if item.exists() and item.is_symlink():
            raise ValueError(f"Source path may not include symlinks: {item}")
    for item in checked:
        try:
            item.resolve(strict=False).relative_to(root_resolved)
        except ValueError:
            raise ValueError(f"Source must stay below sources/: {path}")


def _read_source(path: Path) -> tuple[bytes, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        if path.is_symlink():
            raise ValueError(f"Source document may not be a symlink: {path}")
        raise
    try:
        size = os.fstat(fd).st_size
        if size > MAX_SOURCE_BYTES:
            raise ValueError(f"Source document is too large: {path}")
        raw = os.read(fd, size)
    finally:
        os.close(fd)
    return raw, sanitize_text(raw.decode("utf-8", errors="replace"))


def _relative_source_path(store: ScopedMemoryStore, path: Path) -> str:
    return f"sources/{path.relative_to(store.paths.sources_dir.resolve()).as_posix()}"


def _source_ref(store: ScopedMemoryStore, path: Path, digest: str, text: str) -> SourceRef:
    excerpt = " ".join(text.split())[:240] or None
    return SourceRef(
        kind="source",
        path=_relative_source_path(store, path),
        identifier=digest[:16],
        excerpt=excerpt,
    )


def ingest_source(args) -> dict:
    store = build_scoped_store(args.root, scope="project", must_exist=True)
    source_path = _resolve_source(store, args.source)
    raw, text = _read_source(source_path)
    digest = hashlib.sha256(raw).hexdigest()
    ref = _source_ref(store, source_path, digest, text)
    timestamp = args.now or _now()
    affected_paths: list[str] = []

    if args.conflict_with:
        note = args.conflict_note or args.summary or "New source conflicts with this memory."
        if not args.dry_run:
            store.append_semantic_update_log(
                args.conflict_with,
                note,
                source_refs=[ref],
                conflict=True,
                now=timestamp,
            )
        affected_paths.append(f"semantic/{args.conflict_with}.md")
    elif args.target_kind == "semantic":
        if not args.id or not args.title or not args.summary:
            raise ValueError("--id, --title, and --summary are required for semantic ingest")
        existing = store.read_semantic_memory(args.id)
        update_log = list(existing.update_log) if existing else []
        if existing:
            update_log.append(
                f"{timestamp} Update: Refreshed from {ref.path}"
            )
        item = SemanticMemory(
            id=args.id,
            scope="project",
            title=args.title,
            content=args.summary,
            concepts=args.concept or [],
            source_refs=store._merge_source_refs(existing.source_refs if existing else [], [ref]),
            confidence=args.confidence,
            strength=args.strength,
            last_accessed=None,
            created_at=existing.created_at if existing else timestamp,
            updated_at=timestamp,
            update_log=update_log,
        )
        if not args.dry_run:
            store.write_semantic_memory(item)
        affected_paths.append(f"semantic/{args.id}.md")
    else:
        if not args.id or not args.title:
            raise ValueError("--id and --title are required for procedure ingest")
        trigger = args.trigger or args.summary or text[:300]
        steps = args.step or ([args.summary] if args.summary else [])
        item = ProceduralMemory(
            id=args.id,
            scope="project",
            title=args.title,
            trigger=trigger,
            steps=steps,
            source_refs=[ref],
            confidence=args.confidence,
            strength=args.strength,
            last_accessed=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        if not args.dry_run:
            store.write_procedural_memory(item)
        affected_paths.append(f"procedures/{args.id}.md")

    ledger_row = {
        "ts": timestamp,
        "source_path": ref.path,
        "source_sha256": digest,
        "source_bytes": len(raw),
        "affected_paths": affected_paths,
        "dry_run": bool(args.dry_run),
    }
    if not args.dry_run:
        store.append_source_ingest(ledger_row)
        store.refresh_index()
    return ledger_row


def render_human(payload: dict) -> str:
    lines = [
        "Ingested {}".format(payload["source_path"]),
        "Digest: {}".format(payload["source_sha256"]),
        "Affected: {}".format(", ".join(payload["affected_paths"])),
    ]
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Incrementally ingest one read-only source into affected MemoryWiki wiki pages."
    )
    parser.add_argument("--root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--source", required=True, help="File below <root>/sources")
    parser.add_argument("--target-kind", choices=("semantic", "procedure"), default="semantic")
    parser.add_argument("--id", help="Target memory/procedure id")
    parser.add_argument("--title", help="Target title")
    parser.add_argument("--summary", help="Human-approved source summary or conclusion")
    parser.add_argument("--concept", action="append", default=[])
    parser.add_argument("--trigger")
    parser.add_argument("--step", action="append", default=[])
    parser.add_argument("--confidence", type=float, default=0.75)
    parser.add_argument("--strength", type=float, default=0.6)
    parser.add_argument("--conflict-with", help="Existing semantic memory id to annotate")
    parser.add_argument("--conflict-note", help="Conflict/update note to append")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--now", help="Override timestamp for tests")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = ingest_source(args)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
