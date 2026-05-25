"""Guard helpers for requiring initialized scoped stores before writes."""

from __future__ import annotations

from pathlib import Path
from typing import Union

from memory_system.errors import MemoryRootError, MemoryStoreRequiredError
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore


def validate_memory_root(root: Union[str, Path], *, must_exist: bool = False) -> Path:
    path = Path(root).expanduser()
    if must_exist and not path.exists():
        raise MemoryRootError(
            f"Memory root must exist before this operation: {path}. "
            "Reason: this operation reads existing memory files. "
            "Fix: create or initialize the memory root first."
        )
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise MemoryRootError(
            f"Memory root must be a real directory: {path}. "
            "Reason: files or symlinks are not safe memory roots. "
            "Fix: choose a normal directory under your project or home folder."
        )

    cursor = path
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise MemoryRootError(
            f"Memory root may not be below a symlink: {cursor}. "
            "Reason: symlinked roots can redirect memory reads/writes. "
            "Fix: use a real directory path."
        )
    for parent in cursor.parents:
        if parent.is_symlink():
            raise MemoryRootError(
                f"Memory root may not be below a symlink: {parent}. "
                "Reason: symlinked ancestors can redirect memory reads/writes. "
                "Fix: use a real directory path."
            )
    return path


def build_scoped_store(
    root: Union[str, Path],
    *,
    scope: str = "project",
    must_exist: bool = False,
    sanitize_on_write: bool = True,
    secure_permissions: bool = True,
) -> ScopedMemoryStore:
    path = validate_memory_root(root, must_exist=must_exist)
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(path, scope),
        sanitize_on_write=sanitize_on_write,
        secure_permissions=secure_permissions,
    )


def build_existing_scoped_store(
    root: Union[str, Path],
    *,
    scope: str,
    sanitize_on_write: bool = True,
    secure_permissions: bool = True,
) -> ScopedMemoryStore | None:
    path = Path(root).expanduser()
    if not path.exists():
        return None
    return build_scoped_store(
        path,
        scope=scope,
        must_exist=True,
        sanitize_on_write=sanitize_on_write,
        secure_permissions=secure_permissions,
    )


def require_scoped_store(
    store: ScopedMemoryStore | None,
    *,
    root: Union[str, Path],
    operation: str,
) -> ScopedMemoryStore:
    if store is None:
        raise MemoryStoreRequiredError(
            f"{operation} requires an existing memory store at {Path(root).expanduser()}. "
            "Reason: write/apply mode cannot safely continue without a concrete store. "
            "Fix: create the memory root first or rerun in dry-run mode."
        )
    return store
