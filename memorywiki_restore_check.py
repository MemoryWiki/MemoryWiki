from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any


SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
REQUIRED_FILES = (
    "memory_system/__init__.py",
    "memory_health.py",
    "memory_index_maintain.py",
    "memory_lifecycle.py",
    "memorywiki_knowledge_ops.py",
    "memorywiki_operator_env.py",
    "memorywiki_quality_report.py",
)


def _safe_backup_root(root: str | Path) -> Path:
    path = Path(root).expanduser()
    if not path.exists():
        raise ValueError("No backup source found under %s" % path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Backup root must be a real directory: %s" % path)
    for ancestor in path.parents:
        if ancestor.is_symlink():
            raise ValueError("Backup root may not be below a symlink: %s" % ancestor)
    return path


def _safe_restore_parent(root: str | Path | None) -> Path | None:
    if root is None:
        return None
    path = Path(root).expanduser()
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise ValueError("Restore parent must be a real directory: %s" % path)
    cursor = path
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError("Restore parent may not be below a symlink: %s" % cursor)
    for ancestor in cursor.parents:
        if ancestor.is_symlink():
            raise ValueError("Restore parent may not be below a symlink: %s" % ancestor)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str) -> str:
    if not SAFE_NAME_RE.fullmatch(name or ""):
        raise ValueError("Backup name may contain only letters, digits, dots, underscores, or dashes")
    return name


def _assert_safe_backup_path(path: Path, backup_root: Path) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError("Backup source may not be a symlink: %s" % path)
    try:
        path.resolve(strict=False).relative_to(backup_root.resolve(strict=True))
    except ValueError:
        raise ValueError("Backup source must stay below backup root: %s" % path)


def _select_backup_source(
    *,
    backup_root: str | Path,
    backup_name: str,
    source: str = "auto",
) -> tuple[str, Path]:
    root = _safe_backup_root(backup_root)
    name = _safe_name(backup_name)
    if source not in {"auto", "bundle", "remote"}:
        raise ValueError("source must be auto, bundle, or remote")
    bundle_candidates = []
    if source in {"auto", "bundle"}:
        bundle_candidates.extend(root.glob("%s-*.bundle" % name))
        bundle_candidates.append(root / ("%s.bundle" % name))
    bundle_candidates = [
        path
        for path in bundle_candidates
        if path.exists() and path.is_file() and not path.is_symlink()
    ]
    for path in bundle_candidates:
        _assert_safe_backup_path(path, root)
    if bundle_candidates:
        bundle = max(bundle_candidates, key=lambda item: item.stat().st_mtime)
        return "bundle", bundle
    remote = root / ("%s.git" % name)
    if source in {"auto", "remote"} and remote.exists():
        _assert_safe_backup_path(remote, root)
        if not remote.is_dir():
            raise ValueError("Backup remote must be a real directory: %s" % remote)
        return "remote", remote
    raise ValueError("No backup source found for %s under %s" % (name, root))


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )


def _remove_tree(path: Path) -> None:
    def _make_writable_and_retry(func, item, _exc_info):
        try:
            os.chmod(item, stat.S_IWRITE | stat.S_IREAD)
            func(item)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_make_writable_and_retry)


def _check_required_files(restored_root: Path) -> dict[str, Any]:
    missing = [item for item in REQUIRED_FILES if not (restored_root / item).is_file()]
    return {
        "name": "required-files",
        "argv": [],
        "returncode": 0 if not missing else 1,
        "stdout": "required files present" if not missing else "",
        "stderr": "missing: %s" % ", ".join(missing) if missing else "",
    }


def _restored_env(restored_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(restored_root)
    env.setdefault("MEMORY_BACKEND", "local")
    return env


def _run_restored_checks(
    *,
    restored_root: Path,
    project_root: str | Path,
    global_root: str | Path,
    python: str,
    execute_restored_code: bool = False,
) -> list[dict[str, Any]]:
    env = _restored_env(restored_root)
    checks = [_check_required_files(restored_root)]
    command_specs = [
        ("compileall", [python, "-m", "compileall", "-q", str(restored_root)]),
    ]
    if execute_restored_code:
        command_specs.extend(
            [
        (
            "memory-health",
            [
                python,
                str(restored_root / "memory_health.py"),
                "--project-root",
                str(Path(project_root).expanduser()),
                "--global-root",
                str(Path(global_root).expanduser()),
                "--scope",
                "all",
                "--format",
                "json",
            ],
        ),
        (
            "index-maintain",
            [
                python,
                str(restored_root / "memory_index_maintain.py"),
                "--project-root",
                str(Path(project_root).expanduser()),
                "--global-root",
                str(Path(global_root).expanduser()),
                "--scope",
                "all",
                "--format",
                "json",
            ],
        ),
        (
            "memory-lifecycle",
            [
                python,
                str(restored_root / "memory_lifecycle.py"),
                "--project-root",
                str(Path(project_root).expanduser()),
                "--global-root",
                str(Path(global_root).expanduser()),
                "--scope",
                "all",
                "--format",
                "json",
            ],
        ),
        (
            "quality-report",
            [
                python,
                str(restored_root / "memorywiki_quality_report.py"),
                "--project-root",
                str(Path(project_root).expanduser()),
                "--global-root",
                str(Path(global_root).expanduser()),
                "--scope",
                "all",
                "--skip-golden",
                "--format",
                "json",
            ],
        ),
        (
            "knowledge-ops",
            [
                python,
                str(restored_root / "memorywiki_knowledge_ops.py"),
                "--project-root",
                str(Path(project_root).expanduser()),
                "--global-root",
                str(Path(global_root).expanduser()),
                "--skip-golden",
                "--skip-project-matrix",
                "--format",
                "json",
            ],
        ),
            ]
        )
    else:
        command_specs.append(
            (
                "restored-code-execution",
                [],
            )
        )
    for name, argv in command_specs:
        if not argv:
            checks.append(
                {
                    "name": name,
                    "argv": [],
                    "returncode": 0,
                    "stdout": "skipped; pass --execute-restored-code to run restored scripts",
                    "stderr": "",
                }
            )
            continue
        completed = _run(argv, cwd=restored_root, env=env)
        checks.append(
            {
                "name": name,
                "argv": argv,
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            }
        )
        if completed.returncode != 0:
            break
    return checks


def run_restore_check(
    *,
    backup_root: str | Path,
    backup_name: str = "memorywiki-core",
    project_root: str | Path,
    global_root: str | Path,
    python: str = sys.executable,
    restore_parent: str | Path | None = None,
    source: str = "auto",
    keep_restore: bool = False,
    execute_restored_code: bool = False,
) -> dict[str, Any]:
    source_kind, source_path = _select_backup_source(
        backup_root=backup_root,
        backup_name=backup_name,
        source=source,
    )
    parent = _safe_restore_parent(restore_parent)
    temp_root = Path(tempfile.mkdtemp(prefix="memorywiki-restore-", dir=str(parent) if parent else None))
    restored_root = temp_root / "memorywiki"
    checks: list[dict[str, Any]] = []
    try:
        clone = _run(["git", "clone", "--quiet", str(source_path), str(restored_root)])
        checks.append(
            {
                "name": "git-clone",
                "argv": ["git", "clone", "--quiet", str(source_path), str(restored_root)],
                "returncode": clone.returncode,
                "stdout": clone.stdout[-4000:],
                "stderr": clone.stderr[-4000:],
            }
        )
        if clone.returncode == 0:
            checks.extend(
                _run_restored_checks(
                    restored_root=restored_root,
                    project_root=project_root,
                    global_root=global_root,
                    python=python,
                    execute_restored_code=execute_restored_code,
                )
            )
        status = "ok" if checks and all(check["returncode"] == 0 for check in checks) else "fail"
        return {
            "status": status,
            "backup_root": str(Path(backup_root).expanduser()),
            "backup_name": backup_name,
            "source_kind": source_kind,
            "source_path": str(source_path),
            "restored_root": str(restored_root),
            "kept_restore": keep_restore,
            "execute_restored_code": execute_restored_code,
            "checks": checks,
        }
    finally:
        if not keep_restore:
            _remove_tree(temp_root)


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Restore Check",
        "",
        "Status: %s" % payload["status"],
        "Source: %s %s" % (payload["source_kind"], payload["source_path"]),
        "Restored root: %s" % payload["restored_root"],
        "",
    ]
    for check in payload["checks"]:
        marker = "PASS" if check["returncode"] == 0 else "FAIL"
        lines.append("- [%s] %s" % (marker, check["name"]))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore a MemoryWiki backup into a temporary directory and run read-only checks."
    )
    parser.add_argument("--backup-root", default=str(Path.home() / ".memorywiki" / "backups"))
    parser.add_argument("--backup-name", default="memorywiki-core")
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--restore-parent")
    parser.add_argument("--source", choices=("auto", "bundle", "remote"), default="auto")
    parser.add_argument("--keep-restore", action="store_true")
    parser.add_argument(
        "--execute-restored-code",
        action="store_true",
        help=(
            "Explicitly run Python scripts from the restored backup. Default restore "
            "checks are structural and compile-only."
        ),
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_restore_check(
            backup_root=args.backup_root,
            backup_name=args.backup_name,
            project_root=args.project_root,
            global_root=args.global_root,
            python=args.python,
            restore_parent=args.restore_parent,
            source=args.source,
            keep_restore=args.keep_restore,
            execute_restored_code=args.execute_restored_code,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
