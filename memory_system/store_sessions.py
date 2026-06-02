"""Session and episode file helpers for scoped stores."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from memory_system.models import EpisodeFile, SessionFile, SessionMeta
from memory_system.store_io import MAX_MANAGED_FILES


def write_session(store: Any, session: SessionFile) -> Path:
    path = cast(Path, store.paths.session_file(session.id))
    content = store._serialize_session_file(session)
    with store._file_lock():
        store._atomic_write_text_unlocked(path, content)
        store._mark_index_dirty_unlocked()
    return path


def read_session(store: Any, session_id: str) -> SessionFile | None:
    path = store.paths.session_file(session_id)
    store._assert_safe_managed_path(path)
    if not path.exists():
        return None
    return cast(SessionFile, store._parse_session_file(store._sanitize(store._read_text_bounded(path))))


def list_sessions(store: Any, limit: int = 30) -> list[SessionMeta]:
    sessions = []
    scan_limit = store._safe_file_limit(limit, default=30)
    for path in store._iter_safe_managed_files(
        store.paths.sessions_dir, "session-*.md", limit=scan_limit
    ):
        try:
            session = store._parse_session_file(
                store._sanitize(store._read_text_bounded(path))
            )
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        sessions.append(
            SessionMeta(
                id=session.id,
                title=session.title,
                started_at=session.date,
                ended_at=None,
            )
        )
        if len(sessions) >= limit:
            break
    sessions.sort(key=lambda item: item.started_at or item.id, reverse=True)
    return sessions


def append_to_episode(
    store: Any,
    date_text: str,
    section_title: str,
    body: str,
    session_meta: SessionMeta | None = None,
) -> Path:
    path = cast(Path, store.paths.episode_for_date(date_text))
    heading = store._episode_heading(section_title)
    body_block = f"{heading}\n\n{store._sanitize(body).strip()}"
    with store._file_lock():
        if path.exists():
            store._assert_safe_managed_path(path)
            episode = store._parse_episode_file(
                store._sanitize(store._read_text_bounded(path)),
                fallback_date=date_text,
            )
        else:
            episode = EpisodeFile(
                date=date_text,
                scope=store.paths.scope,
                sessions=[],
                body="",
            )
        if session_meta is not None and not any(
            item.id == session_meta.id for item in episode.sessions
        ):
            episode.sessions.append(
                SessionMeta(
                    id=store._sanitize(session_meta.id),
                    title=store._sanitize(session_meta.title),
                    started_at=store._sanitize(session_meta.started_at or "") or None,
                    ended_at=store._sanitize(session_meta.ended_at or "") or None,
                )
            )
        episode.body = (
            (episode.body.rstrip() + "\n\n" if episode.body.strip() else "")
            + body_block.strip()
            + "\n"
        )
        store._atomic_write_text_unlocked(path, store._serialize_episode_file(episode))
        store._mark_index_dirty_unlocked()
    return path


def read_episode(store: Any, date_text: str) -> EpisodeFile | None:
    path = store.paths.episode_for_date(date_text)
    store._assert_safe_managed_path(path)
    if not path.exists():
        return None
    return cast(EpisodeFile, store._parse_episode_file(
        store._sanitize(store._read_text_bounded(path)),
        fallback_date=date_text,
    ))


def list_episodes(store: Any, since: str | int | None = None) -> list[str]:
    dates = []
    limit = (
        store._safe_file_limit(since, default=MAX_MANAGED_FILES)
        if isinstance(since, int)
        else MAX_MANAGED_FILES
    )
    for path in store._iter_safe_managed_files(
        store.paths.episodes_dir, "20??-??-??.md", limit=limit
    ):
        dates.append(path.stem)
    if isinstance(since, str):
        dates = [date_text for date_text in dates if date_text >= since]
    return dates
