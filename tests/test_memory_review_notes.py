from pathlib import Path


def test_review_followup_notes_record_deferred_architecture_items():
    text = Path("docs/internal/memory_review_followups.md").read_text(
        encoding="utf-8"
    )

    assert "history rotation" in text
    assert "SQLite FTS" in text
    assert "not implemented in this pass" in text
