from pathlib import Path
import os

from memory_system.sanitizer import sanitize_text


MAX_OVERLAY_USER_BYTES = 2_000_000


class OverlayMemoryStore:
    def __init__(self, global_store, project_store, canonical_user_path=None):
        self.global_store = global_store
        self.project_store = project_store
        self.canonical_user_path = (
            Path(canonical_user_path).expanduser() if canonical_user_path else None
        )
        self._cache = {}

    def read_merged_core_memory(self):
        return self._read_merged(
            "core",
            [
                (self.global_store.paths.core_memory, self.global_store.read_core_memory),
                (self.project_store.paths.core_memory, self.project_store.read_core_memory),
            ],
        )

    def read_merged_user_memory(self):
        canonical_reader = self._canonical_user_reader()
        if canonical_reader is not None:
            readers = [
                canonical_reader,
                (self.project_store.paths.user_memory, self.project_store.read_user_memory),
            ]
        else:
            readers = [
                (self.global_store.paths.user_memory, self.global_store.read_user_memory),
                (self.project_store.paths.user_memory, self.project_store.read_user_memory),
            ]
        return self._read_merged(
            "user",
            readers,
        )

    def _canonical_user_reader(self):
        path = self.canonical_user_path
        if path is None:
            return None
        try:
            if (
                path.exists()
                and path.is_file()
                and not path.is_symlink()
                and path.stat().st_size <= MAX_OVERLAY_USER_BYTES
            ):
                return (path, lambda: sanitize_text(self._read_canonical_user(path)))
        except (OSError, UnicodeDecodeError):
            return None
        return None

    def _read_canonical_user(self, path: Path) -> str:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags)
        except OSError:
            return ""
        try:
            size = os.fstat(fd).st_size
            if size > MAX_OVERLAY_USER_BYTES:
                return ""
            return os.read(fd, size).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return ""
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def _read_merged(self, key, readers):
        mtimes = tuple(
            path.stat().st_mtime_ns if path.exists() else None for path, _ in readers
        )
        cached = self._cache.get(key)
        if cached and cached[0] == mtimes:
            return cached[1]
        merged = "\n\n".join(read().strip() for _, read in readers).strip()
        mtimes = tuple(
            path.stat().st_mtime_ns if path.exists() else None for path, _ in readers
        )
        self._cache[key] = (mtimes, merged)
        return merged
