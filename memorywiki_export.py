"""Read-only MemoryWiki export helpers for portable backups and reviews."""

from __future__ import annotations

import argparse
import csv
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from memory_system.models import ProceduralMemory, SemanticMemory, SourceRef
from memory_system.paths import MemoryScopePaths
from memory_system.sanitizer import neutralize_instruction_text, sanitize_text
from memory_system.store import ScopedMemoryStore

ExportKind = Literal[
    "all",
    "hot",
    "semantic",
    "procedural",
    "procedure",
    "session",
    "episode",
    "source",
]


@dataclass
class ExportItem:
    scope: str
    kind: str
    identifier: str
    title: str
    path: str
    content: str
    metadata: dict[str, Any]
    truncated: bool = False


def _safe_text(value: str | None) -> str:
    return neutralize_instruction_text(sanitize_text(value or ""))


def _source_refs_to_dicts(refs: list[SourceRef]) -> list[dict[str, Any]]:
    return [asdict(ref) for ref in refs]


def _clip_text(text: str, *, max_chars: int, full: bool) -> tuple[str, bool]:
    safe = _safe_text(text)
    if full or len(safe) <= max_chars:
        return safe, False
    return safe[:max_chars].rstrip() + "\n\n[truncated]", True


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


def _relative_path(store: ScopedMemoryStore, path: Path) -> str:
    try:
        return path.relative_to(store.paths.root).as_posix()
    except ValueError:
        return path.name


def _read_optional_file(store: ScopedMemoryStore, path: Path) -> str | None:
    if not path.exists():
        return None
    store._assert_safe_managed_path(path)
    return store._sanitize(store._read_text_bounded(path))


def _hot_items(
    store: ScopedMemoryStore,
    *,
    max_chars: int,
    full: bool,
) -> list[ExportItem]:
    rows = []
    for identifier, title, path in [
        ("MEMORY", "Core Memory", store.paths.core_memory),
        ("USER", "User Memory", store.paths.user_memory),
        ("INDEX", "Readable Index", store.paths.index),
    ]:
        content = _read_optional_file(store, path)
        if content is None:
            continue
        clipped, truncated = _clip_text(content, max_chars=max_chars, full=full)
        rows.append(
            ExportItem(
                scope=store.paths.scope,
                kind="hot",
                identifier=identifier,
                title=title,
                path=_relative_path(store, path),
                content=clipped,
                metadata={},
                truncated=truncated,
            )
        )
    return rows


def _semantic_item(
    store: ScopedMemoryStore,
    item: SemanticMemory,
    *,
    max_chars: int,
    full: bool,
) -> ExportItem:
    content, truncated = _clip_text(item.content, max_chars=max_chars, full=full)
    return ExportItem(
        scope=item.scope,
        kind="semantic",
        identifier=item.id,
        title=item.title,
        path=_relative_path(store, store.paths.semantic_file(item.id)),
        content=content,
        metadata={
            "concepts": item.concepts,
            "source_refs": _source_refs_to_dicts(item.source_refs),
            "confidence": item.confidence,
            "strength": item.strength,
            "last_accessed": item.last_accessed,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "update_log": item.update_log,
        },
        truncated=truncated,
    )


def _procedural_item(
    store: ScopedMemoryStore,
    item: ProceduralMemory,
    *,
    max_chars: int,
    full: bool,
) -> ExportItem:
    content, truncated = _clip_text(
        "\n".join(f"{index + 1}. {step}" for index, step in enumerate(item.steps)),
        max_chars=max_chars,
        full=full,
    )
    return ExportItem(
        scope=item.scope,
        kind="procedural",
        identifier=item.id,
        title=item.title,
        path=_relative_path(store, store.paths.procedure_file(item.id)),
        content=content,
        metadata={
            "trigger": item.trigger,
            "source_refs": _source_refs_to_dicts(item.source_refs),
            "confidence": item.confidence,
            "strength": item.strength,
            "last_accessed": item.last_accessed,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        },
        truncated=truncated,
    )


def _scope_items(
    *,
    root: str | Path,
    scope: str,
    kind: ExportKind,
    limit: int,
    max_chars: int,
    full: bool,
    include_source_bodies: bool,
) -> list[ExportItem]:
    store = _store_if_exists(root, scope)
    if store is None:
        return []
    normalized_kind = "procedural" if kind == "procedure" else kind
    rows: list[ExportItem] = []

    if normalized_kind in {"all", "hot"}:
        rows.extend(_hot_items(store, max_chars=max_chars, full=full))

    if normalized_kind in {"all", "semantic"}:
        for semantic_item in store.list_semantic_memories(limit=limit):
            rows.append(_semantic_item(store, semantic_item, max_chars=max_chars, full=full))

    if normalized_kind in {"all", "procedural"}:
        for procedural_item in store.list_procedural_memories(limit=limit):
            rows.append(
                _procedural_item(store, procedural_item, max_chars=max_chars, full=full)
            )

    if normalized_kind in {"all", "session"}:
        for meta in store.list_sessions(limit=limit):
            session = store.read_session(meta.id)
            if session is None:
                continue
            content, truncated = _clip_text(session.body, max_chars=max_chars, full=full)
            rows.append(
                ExportItem(
                    scope=session.scope,
                    kind="session",
                    identifier=session.id,
                    title=session.title,
                    path=_relative_path(store, store.paths.session_file(session.id)),
                    content=content,
                    metadata={
                        "date": session.date,
                        "keypoints": session.keypoints,
                        "actions": session.actions,
                        "pending": session.pending,
                        "duration_seconds": session.duration_seconds,
                    },
                    truncated=truncated,
                )
            )

    if normalized_kind in {"all", "episode"}:
        for date_text in store.list_episodes(limit):
            episode = store.read_episode(date_text)
            if episode is None:
                continue
            content, truncated = _clip_text(episode.body, max_chars=max_chars, full=full)
            rows.append(
                ExportItem(
                    scope=episode.scope,
                    kind="episode",
                    identifier=episode.date,
                    title=episode.date,
                    path=_relative_path(store, store.paths.episode_for_date(episode.date)),
                    content=content,
                    metadata={"sessions": [asdict(session) for session in episode.sessions]},
                    truncated=truncated,
                )
            )

    if normalized_kind in {"all", "source"}:
        for source_path in store.list_source_documents(limit=limit):
            content = ""
            truncated = False
            if include_source_bodies:
                raw_content = _read_optional_file(store, source_path) or ""
                content, truncated = _clip_text(
                    raw_content,
                    max_chars=max_chars,
                    full=full,
                )
            rows.append(
                ExportItem(
                    scope=scope,
                    kind="source",
                    identifier=_relative_path(store, source_path),
                    title=source_path.name,
                    path=_relative_path(store, source_path),
                    content=content,
                    metadata={"body_included": include_source_bodies},
                    truncated=truncated,
                )
            )

    return rows[:limit]


def export_memories(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: Literal["all", "project", "global"] = "project",
    kind: ExportKind = "all",
    limit: int = 100,
    max_chars: int = 12000,
    full: bool = False,
    include_source_bodies: bool = False,
) -> list[ExportItem]:
    """Collect memory items from existing roots without mutating the memory store."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    roots: list[tuple[str, str | Path]] = []
    if scope in {"all", "global"}:
        roots.append(("global", global_root))
    if scope in {"all", "project"}:
        roots.append(("project", project_root))
    rows: list[ExportItem] = []
    for scope_name, root in roots:
        rows.extend(
            _scope_items(
                root=root,
                scope=scope_name,
                kind=kind,
                limit=limit,
                max_chars=max_chars,
                full=full,
                include_source_bodies=include_source_bodies,
            )
        )
    return rows[:limit]


def export_payload(items: list[ExportItem], *, scope: str, kind: str) -> dict[str, Any]:
    return {
        "schema_version": "memorywiki.export.v1",
        "scope": scope,
        "kind": kind,
        "items": [asdict(item) for item in items],
    }


def render_export(
    items: list[ExportItem],
    *,
    scope: str,
    kind: str,
    format_name: Literal["json", "markdown", "csv"],
) -> str:
    payload = export_payload(items, scope=scope, kind=kind)
    if format_name == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if format_name == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "scope",
                "kind",
                "identifier",
                "title",
                "path",
                "truncated",
                "metadata",
                "content",
            ],
        )
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "scope": item.scope,
                    "kind": item.kind,
                    "identifier": item.identifier,
                    "title": item.title,
                    "path": item.path,
                    "truncated": str(item.truncated).lower(),
                    "metadata": json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                    "content": item.content,
                }
            )
        return output.getvalue()

    lines = [
        "# MemoryWiki Export",
        "",
        f"- Scope: `{scope}`",
        f"- Kind: `{kind}`",
        f"- Items: `{len(items)}`",
        "",
    ]
    for item in items:
        lines.extend(
            [
                f"## {item.scope}/{item.kind}: {item.title}",
                "",
                f"- ID: `{item.identifier}`",
                f"- Path: `{item.path}`",
                f"- Truncated: `{str(item.truncated).lower()}`",
                "",
                item.content.strip() or "_No exported body._",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _write_output(path: str | Path, text: str) -> None:
    output_path = Path(path).expanduser()
    if output_path.exists() and output_path.is_symlink():
        raise ValueError(f"Output path may not be a symlink: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export MemoryWiki data for review, migration, or portable backups."
    )
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--scope", choices=("all", "project", "global"), default="project")
    parser.add_argument(
        "--kind",
        choices=("all", "hot", "semantic", "procedural", "procedure", "session", "episode", "source"),
        default="all",
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--full", action="store_true", help="Export full bodies instead of clipping.")
    parser.add_argument(
        "--include-source-bodies",
        action="store_true",
        help="Include raw sources/* bodies; off by default to avoid accidental large exports.",
    )
    parser.add_argument("--format", choices=("json", "markdown", "csv"), default="json")
    parser.add_argument("--out", help="Optional output file. Defaults to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    items = export_memories(
        project_root=args.project_root,
        global_root=args.global_root,
        scope=args.scope,
        kind=args.kind,
        limit=args.limit,
        max_chars=args.max_chars,
        full=args.full,
        include_source_bodies=args.include_source_bodies,
    )
    rendered = render_export(items, scope=args.scope, kind=args.kind, format_name=args.format)
    if args.out:
        _write_output(args.out, rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
