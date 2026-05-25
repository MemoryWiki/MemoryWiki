from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from memory_system.paths import MemoryScopePaths
from memory_system.sanitizer import neutralize_instruction_text, sanitize_text
from memory_system.store import ScopedMemoryStore

MemoryKind = Literal["all", "semantic", "procedural", "procedure", "session", "episode"]


@dataclass
class MemoryListEntry:
    scope: str
    kind: str
    identifier: str
    title: str
    created_at: str = ""
    updated_at: str = ""
    concepts: list[str] | None = None
    confidence: float | None = None
    strength: float | None = None


def _safe_text(value: str | None) -> str:
    return neutralize_instruction_text(sanitize_text(value or ""))


def _store_if_exists(root: str | Path, scope: str) -> ScopedMemoryStore | None:
    path = Path(root).expanduser()
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"Memory root must be a real directory: {path}")
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(path, scope=scope),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def _matches_concepts(item_concepts: list[str], required: list[str]) -> bool:
    if not required:
        return True
    available = {concept.lower() for concept in item_concepts}
    return all(concept.lower() in available for concept in required)


def _list_scope(
    *,
    root: str | Path,
    scope: str,
    kind: MemoryKind,
    concepts: list[str],
    limit: int,
) -> list[MemoryListEntry]:
    store = _store_if_exists(root, scope)
    if store is None:
        return []
    rows: list[MemoryListEntry] = []
    normalized_kind = "procedural" if kind == "procedure" else kind

    if normalized_kind in {"all", "semantic"}:
        for semantic_item in store.list_semantic_memories(limit=limit):
            if not _matches_concepts(semantic_item.concepts, concepts):
                continue
            rows.append(
                MemoryListEntry(
                    scope=scope,
                    kind="semantic",
                    identifier=semantic_item.id,
                    title=semantic_item.title,
                    created_at=semantic_item.created_at,
                    updated_at=semantic_item.updated_at,
                    concepts=list(semantic_item.concepts),
                    confidence=semantic_item.confidence,
                    strength=semantic_item.strength,
                )
            )

    if normalized_kind in {"all", "procedural"}:
        for procedural_item in store.list_procedural_memories(limit=limit):
            if concepts:
                continue
            rows.append(
                MemoryListEntry(
                    scope=scope,
                    kind="procedural",
                    identifier=procedural_item.id,
                    title=procedural_item.title,
                    created_at=procedural_item.created_at,
                    updated_at=procedural_item.updated_at,
                    concepts=[],
                    confidence=procedural_item.confidence,
                    strength=procedural_item.strength,
                )
            )

    if normalized_kind in {"all", "session"} and not concepts:
        for session_item in store.list_sessions(limit=limit):
            rows.append(
                MemoryListEntry(
                    scope=scope,
                    kind="session",
                    identifier=session_item.id,
                    title=session_item.title,
                    created_at=session_item.started_at or "",
                    updated_at=session_item.ended_at or session_item.started_at or "",
                    concepts=[],
                )
            )

    if normalized_kind in {"all", "episode"} and not concepts:
        for date_text in store.list_episodes(limit):
            rows.append(
                MemoryListEntry(
                    scope=scope,
                    kind="episode",
                    identifier=date_text,
                    title=date_text,
                    created_at=date_text,
                    updated_at=date_text,
                    concepts=[],
                )
            )

    rows.sort(key=lambda row: (row.updated_at or row.created_at or row.identifier), reverse=True)
    return rows[:limit]


def list_memories(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: Literal["all", "project", "global"] = "project",
    kind: MemoryKind = "all",
    concepts: list[str] | None = None,
    limit: int = 100,
) -> list[MemoryListEntry]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    concept_filter = concepts or []
    roots: list[tuple[str, str | Path]] = []
    if scope in {"all", "global"}:
        roots.append(("global", global_root))
    if scope in {"all", "project"}:
        roots.append(("project", project_root))
    rows: list[MemoryListEntry] = []
    for scope_name, root in roots:
        rows.extend(
            _list_scope(
                root=root,
                scope=scope_name,
                kind=kind,
                concepts=concept_filter,
                limit=limit,
            )
        )
    rows.sort(key=lambda row: (row.updated_at or row.created_at or row.identifier), reverse=True)
    return rows[:limit]


def entries_to_dicts(entries: list[MemoryListEntry]) -> list[dict[str, Any]]:
    rows = []
    for entry in entries:
        payload = asdict(entry)
        payload["scope"] = _safe_text(payload["scope"])
        payload["kind"] = _safe_text(payload["kind"])
        payload["identifier"] = _safe_text(payload["identifier"])
        payload["title"] = _safe_text(payload["title"])
        payload["created_at"] = _safe_text(payload["created_at"])
        payload["updated_at"] = _safe_text(payload["updated_at"])
        payload["concepts"] = [_safe_text(concept) for concept in payload["concepts"] or []]
        rows.append(payload)
    return rows


def render_table(entries: list[MemoryListEntry]) -> str:
    rows = entries_to_dicts(entries)
    if not rows:
        return "No memories found.\n"
    lines = ["scope\tkind\tid\ttitle\tupdated\tconcepts"]
    for row in rows:
        lines.append(
            "{}\t{}\t{}\t{}\t{}\t{}".format(
                row["scope"],
                row["kind"],
                row["identifier"],
                row["title"],
                row["updated_at"],
                ",".join(row["concepts"]),
            )
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List MemoryWiki memories by scope, kind, or concept.")
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--scope", choices=("all", "project", "global"), default="project")
    parser.add_argument(
        "--kind",
        choices=("all", "semantic", "procedural", "procedure", "session", "episode"),
        default="all",
    )
    parser.add_argument("--concept", action="append", default=[], help="Require a semantic concept.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    entries = list_memories(
        project_root=args.project_root,
        global_root=args.global_root,
        scope=args.scope,
        kind=args.kind,
        concepts=args.concept,
        limit=args.limit,
    )
    if args.format == "json":
        print(json.dumps({"memories": entries_to_dicts(entries)}, ensure_ascii=False, indent=2))
    else:
        print(render_table(entries), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
