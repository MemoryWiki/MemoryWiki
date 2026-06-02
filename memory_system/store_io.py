"""Low-level safe filesystem and JSONL operations for scoped stores."""

from __future__ import annotations

import json
import os
import tempfile
import warnings
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from memory_system.sanitizer import neutralize_instruction_text

fcntl: Any
try:
    import fcntl as fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

MAX_MANAGED_READ_BYTES = 2_000_000
MAX_MANAGED_JSONL_ROWS = 10_000
MAX_MANAGED_FILES = 1_000


def read_or_create(store: Any, path: Path, template: str) -> str:
    store._assert_safe_managed_path(path)
    if not path.exists():
        with store._file_lock():
            store._assert_safe_managed_path(path)
            if not path.exists():
                store._atomic_write_text_unlocked(path, template)
            if path != store.paths.index:
                store._mark_index_dirty_unlocked()
    return str(store._read_text_bounded(path))


def append_jsonl(store: Any, path: Path, row: dict) -> None:
    with store._file_lock():
        store._append_text_unlocked(path, json.dumps(row, ensure_ascii=False) + "\n")
        store._mark_index_dirty_unlocked()


def atomic_write_text(store: Any, path: Path, content: str) -> None:
    with store._file_lock():
        store._atomic_write_text_unlocked(path, content)
        if path != store.paths.index:
            store._mark_index_dirty_unlocked()


def atomic_write_text_unlocked(store: Any, path: Path, content: str) -> None:
    store._assert_mutable_managed_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o600 if store.secure_permissions and os.name != "nt" else 0o666
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=False,
    )
    temp_path = Path(temp_name)
    try:
        if os.name != "nt":
            os.chmod(temp_path, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content.encode("utf-8"))
        os.replace(temp_path, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temp_path.unlink(missing_ok=True)
        raise
    secure_path(store, path)


def append_text(store: Any, path: Path, content: str) -> None:
    with store._file_lock():
        store._append_text_unlocked(path, content)
        if path != store.paths.index:
            store._mark_index_dirty_unlocked()


def append_text_unlocked(store: Any, path: Path, content: str) -> None:
    store._assert_mutable_managed_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    mode = 0o600 if store.secure_permissions and os.name != "nt" else 0o666
    try:
        fd = os.open(path, flags, mode)
    except OSError:
        if path.is_symlink():
            raise ValueError(f"Managed memory files may not be symlinks: {path}")
        raise
    try:
        with os.fdopen(fd, "ab") as handle:
            handle.write(content.encode("utf-8"))
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    secure_path(store, path)


def index_is_dirty(store: Any) -> bool:
    return bool(store._index_dirty_path.exists())


def mark_index_dirty_unlocked(store: Any) -> None:
    store._atomic_write_text_unlocked(
        store._index_dirty_path,
        datetime.now().astimezone().isoformat(timespec="seconds") + "\n",
    )


def clear_index_dirty_unlocked(store: Any) -> None:
    store._assert_safe_managed_path(store._index_dirty_path)
    if store._index_dirty_path.exists():
        if store._index_dirty_path.is_symlink():
            raise ValueError(
                f"Managed memory files may not be symlinks: {store._index_dirty_path}"
            )
        store._index_dirty_path.unlink()


@contextmanager
def file_lock(store: Any):
    store.paths.root.mkdir(parents=True, exist_ok=True)
    store._assert_safe_managed_path(store.paths.lock_file)
    mode = 0o600 if store.secure_permissions and os.name != "nt" else 0o666
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(store.paths.lock_file, flags, mode)
    except OSError:
        if store.paths.lock_file.is_symlink():
            raise ValueError(
                f"Managed memory files may not be symlinks: {store.paths.lock_file}"
            )
        raise
    try:
        if os.name != "nt":
            os.chmod(store.paths.lock_file, mode)
        with os.fdopen(fd, "a+") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    secure_path(store, store.paths.lock_file)


def file_char_count(store: Any, path: Path) -> int:
    try:
        if not store._is_safe_readable_file(path):
            return 0
        return len(store._read_text_bounded(path))
    except (OSError, UnicodeDecodeError, ValueError):
        return 0


def count_nonempty_lines(store: Any, path: Path) -> int:
    try:
        if not store._is_safe_readable_file(path):
            return 0
        return sum(1 for line in store._read_lines_bounded(path) if line)
    except (OSError, UnicodeDecodeError, ValueError):
        return 0


def preview_text(store: Any, path: Path) -> str:
    try:
        if not store._is_safe_readable_file(path):
            return ""
        text = store._read_text_bounded(path)
    except (OSError, UnicodeDecodeError, ValueError):
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return neutralize_instruction_text(store._sanitize(stripped))[:120]
    return ""


def iter_safe_managed_files(
    store: Any, directory: Path, pattern: str, limit: int = MAX_MANAGED_FILES
) -> list[Path]:
    limit = safe_file_limit(limit, default=MAX_MANAGED_FILES)
    try:
        if directory == store.paths.root:
            if store.paths.root.is_symlink():
                return []
        else:
            store._assert_safe_managed_path(directory)
    except ValueError:
        return []
    if limit <= 0 or not directory.exists() or not directory.is_dir():
        return []
    safe_paths = []
    for path in sorted(directory.glob(pattern), reverse=True):
        if not store._is_safe_readable_file(path):
            continue
        safe_paths.append(path)
        if len(safe_paths) >= limit:
            break
    return safe_paths


def safe_file_limit(limit: Any, default: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return min(max(value, 1), MAX_MANAGED_FILES)


def ensure_root(store: Any) -> None:
    for component in [store.paths.root, *store.paths.root.parents]:
        if component.exists() and component.is_symlink():
            raise ValueError(
                f"Memory root may not be or be below a symlinked directory: {component}"
            )
    missing_dirs = []
    current = store.paths.root
    while not current.exists():
        missing_dirs.append(current)
        current = current.parent
    if current.is_symlink():
        raise ValueError(
            f"Memory root may not be created below a symlinked directory: {current}"
        )
    store.paths.root.mkdir(parents=True, exist_ok=True)
    if store.paths.root.is_symlink():
        raise ValueError(f"Memory root may not be a symlink: {store.paths.root}")
    if store.secure_permissions and os.name != "nt":
        for path in reversed(missing_dirs):
            os.chmod(path, 0o700)
        os.chmod(store.paths.root, 0o700)


def secure_path(store: Any, path: Path) -> None:
    if store.secure_permissions and os.name != "nt" and path.exists():
        os.chmod(path, 0o600)


def assert_safe_managed_path(store: Any, path: Path) -> None:
    if store.paths.root.is_symlink():
        raise ValueError(f"Memory root may not be a symlink: {store.paths.root}")
    if path.is_symlink():
        raise ValueError(f"Managed memory files may not be symlinks: {path}")
    root = store.paths.root.resolve(strict=True)
    parent = path.parent.resolve(strict=False)
    try:
        parent.relative_to(root)
    except ValueError:
        raise ValueError(f"Managed memory path must stay within memory root: {path}")


def assert_mutable_managed_path(store: Any, path: Path) -> None:
    store._assert_safe_managed_path(path)
    try:
        resolved_path = path.resolve(strict=False)
        resolved_sources = store.paths.sources_dir.resolve(strict=False)
        resolved_path.relative_to(resolved_sources)
    except (OSError, ValueError):
        return
    raise ValueError(f"sources/ is read-only for MemoryWiki writes: {path}")


def is_safe_readable_file(store: Any, path: Path) -> bool:
    try:
        store._assert_safe_managed_path(path)
    except ValueError:
        return False
    return path.exists() and path.is_file() and path.stat().st_size <= MAX_MANAGED_READ_BYTES


def read_text_bounded(store: Any, path: Path) -> str:
    store._assert_safe_managed_path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        if path.is_symlink():
            raise ValueError(f"Managed memory files may not be symlinks: {path}")
        raise
    try:
        size = os.fstat(fd).st_size
        if size > MAX_MANAGED_READ_BYTES:
            raise ValueError(f"Managed memory file exceeds safe read limit: {path}")
        data = os.read(fd, size)
        return data.decode("utf-8")
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def read_lines_bounded(
    store: Any, path: Path, max_rows: int = MAX_MANAGED_JSONL_ROWS
) -> list[str]:
    lines = str(store._read_text_bounded(path)).splitlines()
    if len(lines) > max_rows:
        warnings.warn(
            f"Managed JSONL file exceeds safe row limit; truncating to {max_rows} rows: {path}",
            RuntimeWarning,
            stacklevel=2,
        )
    return lines[:max_rows]
