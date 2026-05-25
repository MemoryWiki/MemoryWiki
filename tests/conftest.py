from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_memory_store(
    root: Path,
    scope: str = "project",
    *,
    sanitize_on_write: bool = True,
    secure_permissions: bool = False,
) -> ScopedMemoryStore:
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=sanitize_on_write,
        secure_permissions=secure_permissions,
    )


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def memory_store_factory() -> Callable[..., ScopedMemoryStore]:
    return make_memory_store


@pytest.fixture
def allow_mcp_root_override(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_MCP_ALLOW_ROOT_OVERRIDE", "true")
