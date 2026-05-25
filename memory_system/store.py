"""Compatibility facade for the split MemoryWiki scoped store modules."""

from __future__ import annotations

from memory_system import store_documents, store_io
from memory_system.paths import MemoryPaths, MemoryScopePaths
from memory_system.store_facade import ScopedMemoryStoreFacade

CORE_MEMORY_TEMPLATE = store_documents.CORE_MEMORY_TEMPLATE
USER_MEMORY_TEMPLATE = store_documents.USER_MEMORY_TEMPLATE
INDEX_TEMPLATE = store_documents.INDEX_TEMPLATE
MAX_MANAGED_READ_BYTES = store_io.MAX_MANAGED_READ_BYTES
MAX_MANAGED_JSONL_ROWS = store_io.MAX_MANAGED_JSONL_ROWS
MAX_MANAGED_FILES = store_io.MAX_MANAGED_FILES


class ScopedMemoryStore(ScopedMemoryStoreFacade):
    def __init__(
        self,
        paths: MemoryScopePaths,
        sanitize_on_write: bool = True,
        secure_permissions: bool = True,
    ) -> None:
        self.paths = paths
        self.sanitize_on_write = sanitize_on_write
        self.secure_permissions = secure_permissions
        self._index_dirty_path = self.paths.root / ".INDEX_DIRTY"
        self._ensure_root()


class MemoryStore(ScopedMemoryStore):
    """Compatibility shim that now keeps the safer ScopedMemoryStore defaults.

    Prefer ScopedMemoryStore for new code so callers choose safety settings
    explicitly.
    """

    def __init__(self, paths: MemoryPaths) -> None:
        super().__init__(
            paths=MemoryScopePaths(root=paths.root, scope="project"),
            sanitize_on_write=True,
            secure_permissions=True,
        )
