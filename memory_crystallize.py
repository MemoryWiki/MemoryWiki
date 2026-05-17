from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from memory_system.models import ProceduralMemory, SemanticMemory, SourceRef
from memory_system.paths import MemoryScopePaths
from memory_system.sanitizer import sanitize_text
from memory_system.store import ScopedMemoryStore


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_store(root: str | Path) -> ScopedMemoryStore:
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
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(path, scope="project"),
        sanitize_on_write=True,
        secure_permissions=True,
    )


def _answer_from_args(args) -> str:
    answer = args.answer
    if answer is None and not sys.stdin.isatty():
        answer = sys.stdin.read()
    answer = sanitize_text(answer or "").strip()
    if not answer:
        raise ValueError("--answer or stdin content is required")
    return answer


def _source_refs(args) -> list[SourceRef]:
    if not args.source_path:
        return []
    return [
        SourceRef(
            kind=args.source_kind,
            path=args.source_path,
            identifier=args.source_id,
            excerpt=None,
        )
    ]


def crystallize(args) -> dict:
    store = _safe_store(args.root)
    answer = _answer_from_args(args)
    timestamp = args.now or _now()
    refs = _source_refs(args)

    if args.kind == "semantic":
        existing = store.read_semantic_memory(args.id)
        if existing is not None and not args.replace:
            raise ValueError("semantic memory already exists; use --replace: %s" % args.id)
        item = SemanticMemory(
            id=args.id,
            scope="project",
            title=args.title,
            content=answer,
            concepts=args.concept or [],
            source_refs=refs if existing is None else store._merge_source_refs(existing.source_refs, refs),
            confidence=args.confidence,
            strength=args.strength,
            last_accessed=None,
            created_at=existing.created_at if existing else timestamp,
            updated_at=timestamp,
            update_log=(
                list(existing.update_log)
                + ["%s Update: Replaced from crystallized answer." % timestamp]
                if existing
                else []
            ),
        )
        path = store.write_semantic_memory(item)
        affected = path.relative_to(store.paths.root).as_posix()
    else:
        existing = store.read_procedural_memory(args.id)
        if existing is not None and not args.replace:
            raise ValueError("procedure already exists; use --replace: %s" % args.id)
        steps = args.step or [line.strip("- ").strip() for line in answer.splitlines() if line.strip()]
        item = ProceduralMemory(
            id=args.id,
            scope="project",
            title=args.title,
            trigger=args.trigger or answer[:240],
            steps=steps,
            source_refs=refs if existing is None else store._merge_source_refs(existing.source_refs, refs),
            confidence=args.confidence,
            strength=args.strength,
            last_accessed=None,
            created_at=existing.created_at if existing else timestamp,
            updated_at=timestamp,
        )
        path = store.write_procedural_memory(item)
        affected = path.relative_to(store.paths.root).as_posix()

    store.refresh_index()
    return {
        "kind": args.kind,
        "id": args.id,
        "affected_path": affected,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crystallize a good answer into explicit MemoryWiki semantic/procedural memory."
    )
    parser.add_argument("--root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--kind", choices=("semantic", "procedure"), default="semantic")
    parser.add_argument("--id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--answer")
    parser.add_argument("--concept", action="append", default=[])
    parser.add_argument("--trigger")
    parser.add_argument("--step", action="append", default=[])
    parser.add_argument("--source-kind", default="manual")
    parser.add_argument("--source-path")
    parser.add_argument("--source-id")
    parser.add_argument("--confidence", type=float, default=0.8)
    parser.add_argument("--strength", type=float, default=0.7)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--now", help="Override timestamp for tests")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = crystallize(args)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("Crystallized %s/%s -> %s" % (payload["kind"], payload["id"], payload["affected_path"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
