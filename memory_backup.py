from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import sys


DEFAULT_BACKUP_ROOT = Path.home() / ".memorywiki" / "backups"
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
DEFAULT_GITIGNORE = [
    ".INDEX_DIRTY",
    ".memory.lock",
    ".DS_Store",
    "__pycache__/",
    "*.tmp",
]


def _safe_root(root: str | Path) -> Path:
    path = Path(root).expanduser()
    if not path.exists() or path.is_symlink() or not path.is_dir():
        raise ValueError("Memory root must be a real directory: %s" % path)
    for ancestor in path.parents:
        if ancestor.is_symlink():
            raise ValueError("Memory root may not be below a symlink: %s" % ancestor)
    return path


def _safe_backup_root(root: str | Path) -> Path:
    path = Path(root).expanduser()
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise ValueError("Backup root must be a real directory: %s" % path)
    for component in [path, *path.parents]:
        if component.exists() and component.is_symlink():
            raise ValueError("Backup root may not be below a symlink: %s" % component)
    cursor = path
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.is_symlink():
        raise ValueError("Backup root may not be below a symlink: %s" % cursor)
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)
    return path


def _safe_name(name: str | None, root: Path) -> str:
    raw = name or root.name or "memory"
    cleaned = SAFE_NAME_RE.sub("-", raw).strip(".-")[:80]
    return cleaned or "memory"


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def _write_text_no_follow(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        if path.is_symlink():
            raise ValueError("Managed backup file may not be a symlink: %s" % path)
        raise
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def _ensure_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    if path.exists() and path.is_symlink():
        raise ValueError("Gitignore may not be a symlink: %s" % path)
    existing = path.read_text(encoding="utf-8") if path.exists() and not path.is_symlink() else ""
    lines = existing.splitlines()
    changed = False
    for item in DEFAULT_GITIGNORE:
        if item not in lines:
            lines.append(item)
            changed = True
    if changed:
        _write_text_no_follow(path, "\n".join(lines).rstrip() + "\n")


def _ensure_repo(root: Path) -> None:
    if not (root / ".git").exists():
        _run(["git", "init"], cwd=root)
        _run(["git", "branch", "-M", "main"], cwd=root, check=False)
    _ensure_gitignore(root)


def _ensure_remote_hooks_disabled(remote: Path) -> None:
    hooks_dir = remote / ".memorywiki-disabled-hooks"
    if hooks_dir.exists() and (hooks_dir.is_symlink() or not hooks_dir.is_dir()):
        raise ValueError("Backup remote hook guard must be a real directory: %s" % hooks_dir)
    hooks_dir.mkdir(exist_ok=True)
    if os.name != "nt":
        os.chmod(hooks_dir, 0o700)
    _run(["git", "--git-dir", str(remote), "config", "--local", "core.hooksPath", str(hooks_dir)])


def _ensure_remote(root: Path, backup_root: Path, name: str) -> Path:
    remote = backup_root / ("%s.git" % name)
    if not remote.exists():
        _run(["git", "init", "--bare", str(remote)])
    elif remote.is_symlink() or not remote.is_dir():
        raise ValueError("Backup remote must be a real directory: %s" % remote)
    _ensure_remote_hooks_disabled(remote)
    if os.name != "nt":
        for current, dirs, files in os.walk(remote):
            os.chmod(current, 0o700)
            for filename in files:
                os.chmod(Path(current) / filename, 0o600)
    current = _run(["git", "remote", "get-url", "memorywiki-local"], cwd=root, check=False)
    if current.returncode == 0:
        _run(["git", "remote", "set-url", "memorywiki-local", str(remote)], cwd=root)
    else:
        _run(["git", "remote", "add", "memorywiki-local", str(remote)], cwd=root)
    return remote


def _commit_if_needed(root: Path, message: str) -> tuple[bool, str]:
    _run(["git", "add", "-A"], cwd=root)
    status = _run(["git", "status", "--short"], cwd=root).stdout.strip()
    if not status:
        return False, ""
    _run(
        [
            "git",
            "-c",
            "user.name=MemoryWiki Backup",
            "-c",
            "user.email=memorywiki-backup@local",
            "commit",
            "-m",
            message,
        ],
        cwd=root,
    )
    sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=root).stdout.strip()
    return True, sha


def _bundle_refs(root: Path) -> list[str]:
    refs = ["HEAD"]
    main = _run(
        ["git", "rev-parse", "--verify", "--quiet", "main^{commit}"],
        cwd=root,
        check=False,
    )
    if main.returncode == 0:
        refs.append("main")
    return refs


def _push_backup_ref(root: Path) -> None:
    _run(["git", "push", "memorywiki-local", "HEAD:refs/heads/main"], cwd=root)


def backup_memory(
    root: str | Path,
    backup_root: str | Path = DEFAULT_BACKUP_ROOT,
    name: str | None = None,
    message: str = "chore: checkpoint memory",
    bundle: bool = True,
) -> dict:
    memory_root = _safe_root(root)
    backups = _safe_backup_root(backup_root)
    safe_name = _safe_name(name, memory_root)
    _ensure_repo(memory_root)
    remote = _ensure_remote(memory_root, backups, safe_name)
    committed, sha = _commit_if_needed(memory_root, message)
    if not sha:
        sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=memory_root, check=False).stdout.strip()
    _push_backup_ref(memory_root)
    _run(["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"], check=False)
    bundle_path = None
    if bundle:
        suffix = sha or datetime.now().strftime("%Y%m%d%H%M%S")
        bundle_path = backups / ("%s-%s.bundle" % (safe_name, suffix))
        if bundle_path.exists() and bundle_path.is_symlink():
            raise ValueError("Backup bundle may not be a symlink: %s" % bundle_path)
        _run(["git", "bundle", "create", str(bundle_path), *_bundle_refs(memory_root)], cwd=memory_root)
        if os.name != "nt":
            os.chmod(bundle_path, 0o600)
    return {
        "root": str(memory_root),
        "remote": str(remote),
        "committed": committed,
        "commit": sha,
        "bundle": str(bundle_path) if bundle_path else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Snapshot a MemoryWiki root to a local git backup remote.")
    parser.add_argument("--root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    parser.add_argument("--name")
    parser.add_argument("--message", default="chore: checkpoint memory")
    parser.add_argument("--no-bundle", action="store_true")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = backup_memory(
            root=args.root,
            backup_root=args.backup_root,
            name=args.name,
            message=args.message,
            bundle=not args.no_bundle,
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["committed"]:
            print("Committed %s" % result["commit"])
        else:
            print("No changes to commit; pushed existing HEAD.")
        print("Remote: %s" % result["remote"])
        if result.get("bundle"):
            print("Bundle: %s" % result["bundle"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
