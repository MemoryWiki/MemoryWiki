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


def test_memory_backup_does_not_repoint_existing_upstream(tmp_path):
    upstream = tmp_path / "upstream.git"
    subprocess.run(["git", "init", "--bare", str(upstream)], check=True, capture_output=True, text=True)
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=root, check=True)
    (root / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
    subprocess.run(["git", "add", "MEMORY.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(upstream)], cwd=root, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=root, check=True, capture_output=True, text=True)

    subprocess.run(
        [
            sys.executable,
            "memory_backup.py",
            "--root",
            str(root),
            "--backup-root",
            str(tmp_path / "backups"),
            "--name",
            "upstream-memory",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    upstream_after = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert upstream_after == "origin/main"


def test_memory_backup_bundles_detached_head_without_local_main(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=root, check=True)
    (root / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
    subprocess.run(["git", "add", "MEMORY.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True, text=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "checkout", "--detach", sha], cwd=root, check=True, capture_output=True, text=True)
    for branch in ("main", "master"):
        subprocess.run(["git", "branch", "-D", branch], cwd=root, capture_output=True, text=True)

    backup_root = tmp_path / "backups"
    result = subprocess.run(
        [
            sys.executable,
            "memory_backup.py",
            "--root",
            str(root),
            "--backup-root",
            str(backup_root),
            "--name",
            "detached-memory",
            "--message",
            "checkpoint detached",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Remote:" in result.stdout
    bundle = next(backup_root.glob("detached-memory-*.bundle"))
    restored = tmp_path / "restored"
    subprocess.run(["git", "clone", str(bundle), str(restored)], check=True, capture_output=True, text=True)
    assert (restored / "MEMORY.md").read_text(encoding="utf-8") == "# Memory\n"


def test_memory_backup_accepts_shallow_checkout(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=source, check=True)
    (source / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
    subprocess.run(["git", "add", "MEMORY.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=source, check=True, capture_output=True, text=True)
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth", "1", "file://%s" % source, str(shallow)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "checkout", "--detach", "HEAD"],
        cwd=shallow,
        check=True,
        capture_output=True,
        text=True,
    )
    assert subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=shallow,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "true"

    backup_root = tmp_path / "backups"
    result = subprocess.run(
        [
            sys.executable,
            "memory_backup.py",
            "--root",
            str(shallow),
            "--backup-root",
            str(backup_root),
            "--name",
            "shallow-memory",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert (backup_root / "shallow-memory.git").is_dir()
    assert '"bundle": null' in result.stdout
    assert list(backup_root.glob("shallow-memory-*.bundle")) == []
    restored = tmp_path / "restored"
    subprocess.run(
        ["git", "clone", str(backup_root / "shallow-memory.git"), str(restored)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (restored / "MEMORY.md").read_text(encoding="utf-8") == "# Memory\n"


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
