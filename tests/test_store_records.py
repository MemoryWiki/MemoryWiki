from __future__ import annotations

import json

from memory_system import store_records
from memory_system.models import AuditEntry, ChatMessage, SessionSummary
from tests.conftest import make_memory_store


def test_append_history_sanitizes_secret_before_jsonl_write(tmp_path):
    store = make_memory_store(tmp_path / "memory")

    store_records.append_history(
        store,
        ChatMessage(
            ts="2026-05-24T10:00:00+08:00",
            role="user",
            content="token sk-" + ("x" * 32),
        ),
    )

    row = json.loads(store.paths.history.read_text(encoding="utf-8").strip())
    assert row["content"] == "token [REDACTED_OPENAI_KEY]"


def test_audit_records_roundtrip_and_ignore_corrupt_rows(tmp_path):
    store = make_memory_store(tmp_path / "memory")
    store.paths.audit_log.parent.mkdir(parents=True, exist_ok=True)
    store.paths.audit_log.write_text("{broken}\n", encoding="utf-8")

    store_records.append_audit(
        store,
        AuditEntry(
            ts="2026-05-24T10:00:00+08:00",
            action="forget",
            target_kind="semantic",
            target_id="secret",
            reason="token sk-" + ("x" * 32),
            dry_run=False,
            details={"note": "password=super-secret"},
        ),
    )

    rows = store_records.read_audit(store)
    assert len(rows) == 1
    assert rows[0].reason == "token [REDACTED_OPENAI_KEY]"
    assert rows[0].details["note"] == "password=[REDACTED_PASSWORD]"


def test_session_summaries_sort_newest_first_and_normalize_bad_lists(tmp_path):
    store = make_memory_store(tmp_path / "memory")
    store.paths.sessions.parent.mkdir(parents=True, exist_ok=True)
    store.paths.sessions.write_text(
        json.dumps(
            {
                "ts": "2026-05-23T10:00:00+08:00",
                "session_id": "old",
                "summary": "old",
                "key_points": "bad",
                "actions_taken": ["ok"],
                "pending_tasks": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    store_records.append_session_summary(
        store,
        SessionSummary(
            ts="2026-05-24T10:00:00+08:00",
            session_id="new",
            summary="new",
            key_points=["stable"],
            actions_taken=["done"],
            pending_tasks=[],
        ),
    )

    rows = store_records.read_session_summaries(store)
    assert [row.session_id for row in rows] == ["new", "old"]
    assert rows[1].key_points == []
    assert rows[1].pending_tasks == []


def test_list_source_documents_returns_safe_files_only(tmp_path):
    store = make_memory_store(tmp_path / "memory")
    (store.paths.sources_dir / "a").mkdir(parents=True)
    first = store.paths.sources_dir / "a" / "first.md"
    second = store.paths.sources_dir / "second.md"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")

    assert store_records.list_source_documents(store, limit=1) == [first]
