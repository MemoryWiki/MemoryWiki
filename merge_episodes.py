from __future__ import annotations

import argparse
import os
from pathlib import Path

from memory_system.paths import MemoryScopePaths, validate_episodic_date
from memory_system.store import MAX_MANAGED_READ_BYTES, ScopedMemoryStore


def _read_source_file(path: Path) -> str | None:
    if path.is_symlink():
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        size = os.fstat(fd).st_size
        if size > MAX_MANAGED_READ_BYTES:
            return None
        return os.read(fd, size).decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _safe_daily_files(src_dir: Path) -> list[Path]:
    if src_dir.is_symlink():
        raise ValueError("Source memory directory may not be a symlink: %s" % src_dir)
    if not src_dir.exists():
        return []
    if not src_dir.is_dir():
        raise ValueError("Source memory path must be a directory: %s" % src_dir)
    files = []
    for path in sorted(src_dir.glob("20??-??-??.md")):
        try:
            validate_episodic_date(path.stem)
            if (
                path.is_file()
                and not path.is_symlink()
                and path.stat().st_size <= MAX_MANAGED_READ_BYTES
            ):
                files.append(path)
        except (OSError, ValueError):
            continue
    return files


def merge_episodes(
    src_dir: str | Path,
    dst_root: str | Path,
    scope: str = "global",
    dry_run: bool = False,
) -> list[Path]:
    if scope not in {"global", "project"}:
        raise ValueError("scope must be 'global' or 'project'")
    src_path = Path(src_dir).expanduser()
    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(Path(dst_root).expanduser(), scope=scope),
        sanitize_on_write=True,
        secure_permissions=True,
    )
    imported = []
    for source_file in _safe_daily_files(src_path):
        date_text = source_file.stem
        marker = "source: cowork:%s" % date_text
        existing_episode = store.read_episode(date_text)
        if existing_episode is not None and marker in existing_episode.body:
            continue
        body = _read_source_file(source_file)
        if body is None:
            continue
        if not body:
            continue
        if dry_run:
            imported.append(store.paths.episode_for_date(date_text))
            continue
        imported_path = store.append_to_episode(
            date_text,
            "00:00 Cowork import",
            "<!-- %s -->\n\n%s" % (marker, body),
        )
        imported.append(imported_path)
    return imported


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge flat cowork daily memory files into v2 episodes/"
    )
    parser.add_argument("--src", required=True, help="Source cowork memory directory")
    parser.add_argument("--dst", required=True, help="Destination memory scope root")
    parser.add_argument("--scope", choices=["global", "project"], default="global")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    imported = merge_episodes(
        src_dir=args.src,
        dst_root=args.dst,
        scope=args.scope,
        dry_run=args.dry_run,
    )
    action = "Would import" if args.dry_run else "Imported"
    print("%s %s episode%s" % (action, len(imported), "" if len(imported) == 1 else "s"))
    for path in imported:
        print(path)


if __name__ == "__main__":
    main()
