from __future__ import annotations

import pytest

from memory_system.errors import MemoryRootError, MemoryStoreRequiredError
from memory_system.store_guard import (
    build_existing_scoped_store,
    build_scoped_store,
    require_scoped_store,
)


def test_build_scoped_store_rejects_file_root(tmp_path):
    root = tmp_path / "memory-file"
    root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(MemoryRootError, match="real directory"):
        build_scoped_store(root)


def test_build_scoped_store_can_require_existing_root(tmp_path):
    root = tmp_path / "missing-memory"

    with pytest.raises(MemoryRootError, match="must exist"):
        build_scoped_store(root, must_exist=True)

    assert not root.exists()


def test_build_existing_scoped_store_returns_none_for_missing_root(tmp_path):
    assert build_existing_scoped_store(tmp_path / "missing", scope="project") is None


def test_require_scoped_store_raises_actionable_error(tmp_path):
    with pytest.raises(MemoryStoreRequiredError, match="dry-run mode"):
        require_scoped_store(None, root=tmp_path / "missing", operation="test write")
