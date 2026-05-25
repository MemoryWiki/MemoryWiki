"""Index hot-file refresh helpers for MemoryWiki scope roots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

MAX_INDEX_SOURCE_FILES = 1_000


def refresh_index_unlocked(store: Any) -> None:
    store.paths.root.mkdir(parents=True, exist_ok=True)
    legacy_episodic_paths = [
        path for path in store._iter_safe_managed_files(store.paths.root, "20??-??-??.md")
    ]
    episode_paths = [
        path
        for path in store._iter_safe_managed_files(store.paths.episodes_dir, "20??-??-??.md")
    ]
    session_paths = [
        path
        for path in store._iter_safe_managed_files(store.paths.sessions_dir, "session-*.md")
    ]
    semantic_paths = [
        path for path in store._iter_safe_managed_files(store.paths.semantic_dir, "*.md")
    ]
    procedure_paths = [
        path for path in store._iter_safe_managed_files(store.paths.procedures_dir, "*.md")
    ]
    source_paths = store.list_source_documents(limit=MAX_INDEX_SOURCE_FILES)

    lines = [
        f"# Memory Index — {store.paths.scope}",
        "",
        "*Last refreshed: {}*".format(datetime.now().astimezone().isoformat(timespec="minutes")),
        "",
        "> Auto-generated navigation hub for this memory scope.",
        "",
        "## Overview",
        "",
        "| Category | Count / Size | Location |",
        "|----------|--------------|----------|",
        f"| Core Memory | {store._file_char_count(store.paths.core_memory)} chars | MEMORY.md |",
        f"| User Memory | {store._file_char_count(store.paths.user_memory)} chars | USER.md |",
        f"| Project Profile | {store._file_char_count(store.paths.project_profile)} chars | PROJECT_PROFILE.md |",
        f"| Sources | {len(source_paths)} files | sources/ |",
        f"| Episodic Memory | {len(legacy_episodic_paths)} files | YYYY-MM-DD.md |",
        f"| Episodes | {len(episode_paths)} files | episodes/YYYY-MM-DD.md |",
        f"| History | {store._count_nonempty_lines(store.paths.history)} rows | history.jsonl |",
        f"| Token Usage | {store._count_nonempty_lines(store.paths.tokens)} rows | tokens.jsonl |",
        f"| Session Summaries | {store._count_nonempty_lines(store.paths.sessions)} rows | sessions.jsonl |",
        f"| Session Files | {len(session_paths)} files | sessions/session-*.md |",
        f"| Semantic Memories | {len(semantic_paths)} files | semantic/*.md |",
        f"| Procedures | {len(procedure_paths)} files | procedures/*.md |",
        f"| Audit Log | {store._count_nonempty_lines(store.paths.audit_log)} rows | audit.jsonl |",
        f"| Source Ingest Log | {store._count_nonempty_lines(store.paths.source_ingest_log)} rows | source_ingest.jsonl |",
        "",
        "## Episodes",
        "",
    ]
    _append_path_previews(store, lines, episode_paths[:14], empty="- No v2 episodes yet.")

    lines.extend(["", "## Legacy Episodes", ""])
    _append_path_previews(
        store,
        lines,
        legacy_episodic_paths[:7],
        empty="- No legacy episodic memory yet.",
    )

    recent_sessions = store.read_session_summaries(limit=5)
    lines.extend(["", "## Sessions", ""])
    if session_paths:
        _append_path_previews(store, lines, session_paths[:30])
    elif recent_sessions:
        for session in recent_sessions:
            lines.append(f"- **{session.session_id}**: {session.summary[:120]}")
    else:
        lines.append("- No session files yet.")

    lines.extend(["", "## Legacy Session Summaries", ""])
    if recent_sessions:
        for session in recent_sessions:
            lines.append(f"- **{session.session_id}**: {session.summary[:120]}")
    else:
        lines.append("- No legacy session summaries yet.")

    lines.extend(["", "## Semantic Memory", ""])
    _append_path_previews(
        store,
        lines,
        semantic_paths[:30],
        empty="- No semantic memories yet.",
    )

    lines.extend(["", "## Procedures", ""])
    _append_path_previews(store, lines, procedure_paths[:30], empty="- No procedures yet.")

    lines.extend(["", "## Read-Only Sources", ""])
    if source_paths:
        for path in source_paths[:30]:
            try:
                label = path.relative_to(store.paths.sources_dir).as_posix()
            except ValueError:
                label = path.name
            preview = store._preview_text(path)
            lines.append("- **{}**: {}".format(label, preview or "(empty)"))
    else:
        lines.append("- No read-only source documents yet.")

    lines.extend(
        [
            "",
            "## Hot Files",
            "",
            "- MEMORY.md",
            "- USER.md",
            "- PROJECT_PROFILE.md",
            "",
        ]
    )
    store._atomic_write_text_unlocked(store.paths.index, "\n".join(lines))
    store._clear_index_dirty_unlocked()


def _append_path_previews(
    store: Any,
    lines: list[str],
    paths: list,
    *,
    empty: str = "",
) -> None:
    if paths:
        for path in paths:
            preview = store._preview_text(path)
            lines.append("- **{}**: {}".format(path.stem, preview or "(empty)"))
    elif empty:
        lines.append(empty)
