import subprocess
import sys
from pathlib import Path
import os


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_memory_backup_commits_pushes_and_bundles(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    (root / "MEMORY.md").write_text("# Memory\n\n- checkpoint me\n", encoding="utf-8")
    backup_root = tmp_path / "remotes"

    result = subprocess.run(
        [
            sys.executable,
            "memory_backup.py",
            "--root",
            str(root),
            "--backup-root",
            str(backup_root),
            "--name",
            "demo-memory",
            "--message",
            "checkpoint demo memory",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Committed" in result.stdout
    assert (backup_root / "demo-memory.git").is_dir()
    assert list(backup_root.glob("demo-memory-*.bundle"))
    assert subprocess.run(
        ["git", "-C", str(root), "status", "--short"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip() == ""


def test_memory_backup_noops_when_no_changes(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    (root / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
    backup_root = tmp_path / "remotes"
    base_cmd = [
        sys.executable,
        "memory_backup.py",
        "--root",
        str(root),
        "--backup-root",
        str(backup_root),
        "--name",
        "demo-memory",
    ]

    subprocess.run(base_cmd, cwd=REPO_ROOT, text=True, capture_output=True, check=True)
    result = subprocess.run(
        base_cmd, cwd=REPO_ROOT, text=True, capture_output=True, check=True
    )

    assert "No changes" in result.stdout


def test_memory_backup_rejects_symlinked_root(tmp_path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    link_root = tmp_path / "link"
    link_root.symlink_to(real_root, target_is_directory=True)

    result = subprocess.run(
        [
            sys.executable,
            "memory_backup.py",
            "--root",
            str(link_root),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "real directory" in result.stderr


def test_memory_backup_rejects_symlinked_gitignore(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("keep\n", encoding="utf-8")
    (root / ".gitignore").symlink_to(outside)

    result = subprocess.run(
        [
            sys.executable,
            "memory_backup.py",
            "--root",
            str(root),
            "--backup-root",
            str(tmp_path / "remotes"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert outside.read_text(encoding="utf-8") == "keep\n"


def test_memory_backup_disables_existing_bare_remote_external_hooks(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    (root / "MEMORY.md").write_text("# Memory\n\n- checkpoint me\n", encoding="utf-8")
    backup_root = tmp_path / "remotes"
    remote = backup_root / "demo-memory.git"
    remote.parent.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    external_hooks = tmp_path / "external-hooks"
    external_hooks.mkdir()
    marker = tmp_path / "hook-ran"
    hook = external_hooks / "pre-receive"
    hook.write_text("#!/bin/sh\nprintf ran > %s\n" % marker, encoding="utf-8")
    if os.name != "nt":
        hook.chmod(0o700)
    subprocess.run(
        ["git", "--git-dir", str(remote), "config", "core.hooksPath", str(external_hooks)],
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            sys.executable,
            "memory_backup.py",
            "--root",
            str(root),
            "--backup-root",
            str(backup_root),
            "--name",
            "demo-memory",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    configured_hooks = subprocess.run(
        ["git", "--git-dir", str(remote), "config", "core.hooksPath"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert configured_hooks == str(remote / ".memorywiki-disabled-hooks")
    assert not marker.exists()
