from __future__ import annotations

from memory_system import store_lifecycle
from tests.conftest import make_memory_store


def test_sanitize_obeys_store_setting(tmp_path):
    sanitized = make_memory_store(tmp_path / "sanitized")
    raw = make_memory_store(tmp_path / "raw", sanitize_on_write=False)
    secret = "token sk-" + ("x" * 32)

    assert store_lifecycle.sanitize(sanitized, secret) == "token [REDACTED_OPENAI_KEY]"
    assert store_lifecycle.sanitize(raw, secret) == secret


def test_refresh_index_if_dirty_skips_clean_existing_index(tmp_path, monkeypatch):
    store = make_memory_store(tmp_path / "memory")
    store.read_index()
    called = False

    def fake_refresh():
        nonlocal called
        called = True

    monkeypatch.setattr(store, "_refresh_index_unlocked", fake_refresh)

    store_lifecycle.refresh_index_if_dirty_unlocked(store, force=False)

    assert called is False


def test_refresh_index_if_dirty_honors_force(tmp_path, monkeypatch):
    store = make_memory_store(tmp_path / "memory")
    store.read_index()
    called = False

    def fake_refresh():
        nonlocal called
        called = True

    monkeypatch.setattr(store, "_refresh_index_unlocked", fake_refresh)

    store_lifecycle.refresh_index_if_dirty_unlocked(store, force=True)

    assert called is True
