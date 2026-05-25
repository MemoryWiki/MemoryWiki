from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from memory_system.models import ProceduralMemory, SemanticMemory, SourceRef
from memory_system.sanitizer import sanitize_text
from memory_system.store_guard import build_scoped_store


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
    store = build_scoped_store(args.root, scope="project")
    answer = _answer_from_args(args)
    timestamp = args.now or _now()
    refs = _source_refs(args)

    if args.kind == "semantic":
        existing = store.read_semantic_memory(args.id)
        if existing is not None and not args.replace:
            raise ValueError(f"semantic memory already exists; use --replace: {args.id}")
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
                + [f"{timestamp} Update: Replaced from crystallized answer."]
                if existing
                else []
            ),
        )
        path = store.write_semantic_memory(item)
        affected = path.relative_to(store.paths.root).as_posix()
    else:
        existing = store.read_procedural_memory(args.id)
        if existing is not None and not args.replace:
            raise ValueError(f"procedure already exists; use --replace: {args.id}")
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
        print("Crystallized {}/{} -> {}".format(payload["kind"], payload["id"], payload["affected_path"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
