from __future__ import annotations

from memory_system import store_sessions
from memory_system.models import SessionFile, SessionMeta
from tests.conftest import make_memory_store


def _session(session_id: str, date: str, title: str) -> SessionFile:
    return SessionFile(
        id=session_id,
        date=date,
        scope="project",
        title=title,
        keypoints=["key"],
        actions=["action"],
        pending=[],
        duration_seconds=10,
        body="Session body.",
    )


def test_session_file_roundtrips_and_lists_newest_first(tmp_path):
    store = make_memory_store(tmp_path / "memory")

    store_sessions.write_session(store, _session("session-old", "2026-05-23", "Old"))
    store_sessions.write_session(store, _session("session-new", "2026-05-24", "New"))

    assert store_sessions.read_session(store, "session-new").title == "New"
    assert [item.id for item in store_sessions.list_sessions(store)] == [
        "session-new",
        "session-old",
    ]


def test_episode_append_deduplicates_session_meta(tmp_path):
    store = make_memory_store(tmp_path / "memory")
    meta = SessionMeta(
        id="session-1",
        title="Session One",
        started_at="2026-05-24T10:00:00+08:00",
    )

    store_sessions.append_to_episode(store, "2026-05-24", "First", "Body", meta)
    store_sessions.append_to_episode(store, "2026-05-24", "Second", "More", meta)

    episode = store_sessions.read_episode(store, "2026-05-24")
    assert episode is not None
    assert [item.id for item in episode.sessions] == ["session-1"]
    assert "First" in episode.body
    assert "Second" in episode.body


def test_list_episodes_supports_since_filter_and_limit(tmp_path):
    store = make_memory_store(tmp_path / "memory")
    for date_text in ["2026-05-22", "2026-05-23", "2026-05-24"]:
        store_sessions.append_to_episode(store, date_text, "Session", "Body")

    assert store_sessions.list_episodes(store, since="2026-05-23") == [
        "2026-05-24",
        "2026-05-23",
    ]
    assert len(store_sessions.list_episodes(store, since=2)) == 2
