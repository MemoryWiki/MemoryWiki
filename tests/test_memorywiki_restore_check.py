from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from memory_backup import backup_memory
from memorywiki_restore_check import run_restore_check

REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_memorywiki_source(dst: Path) -> None:
    ignore = shutil.ignore_patterns(
        ".git",
        "__pycache__",
        ".pytest_cache",
        "*.pyc",
        ".INDEX_DIRTY",
        ".memory.lock",
    )
    shutil.copytree(REPO_ROOT, dst, ignore=ignore)


def test_restore_check_clones_latest_bundle_and_runs_restored_memorywiki_checks(tmp_path):
    source = tmp_path / "memorywiki-source"
    _copy_memorywiki_source(source)
    backup_root = tmp_path / "remotes"
    backup_memory(
        root=source,
        backup_root=backup_root,
        name="memorywiki-core",
        message="checkpoint memorywiki source",
    )
    project = tmp_path / "project-memory"
    global_root = tmp_path / "global-memory"
    project.mkdir()
    global_root.mkdir()

    payload = run_restore_check(
        backup_root=backup_root,
        backup_name="memorywiki-core",
        project_root=project,
        global_root=global_root,
        python=sys.executable,
        restore_parent=tmp_path / "restore",
        execute_restored_code=True,
    )

    assert payload["status"] == "ok"
    assert payload["source_kind"] == "bundle"
    assert {check["name"] for check in payload["checks"]} == {
        "git-clone",
        "required-files",
        "compileall",
        "memory-health",
        "index-maintain",
        "memory-lifecycle",
        "quality-report",
        "knowledge-ops",
    }
    assert all(check["returncode"] == 0 for check in payload["checks"])
    assert not Path(payload["restored_root"]).exists()


def test_restore_check_does_not_execute_restored_code_by_default(tmp_path):
    source = tmp_path / "memorywiki-source"
    _copy_memorywiki_source(source)
    marker = tmp_path / "restored-code-ran"
    (source / "memory_health.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    backup_root = tmp_path / "remotes"
    backup_memory(
        root=source,
        backup_root=backup_root,
        name="memorywiki-core",
        message="checkpoint untrusted memorywiki source",
    )
    project = tmp_path / "project-memory"
    global_root = tmp_path / "global-memory"
    project.mkdir()
    global_root.mkdir()

    payload = run_restore_check(
        backup_root=backup_root,
        backup_name="memorywiki-core",
        project_root=project,
        global_root=global_root,
        python=sys.executable,
        restore_parent=tmp_path / "restore",
    )

    assert payload["status"] == "ok"
    assert payload["execute_restored_code"] is False
    assert not marker.exists()
    assert {check["name"] for check in payload["checks"]} == {
        "git-clone",
        "required-files",
        "compileall",
        "restored-code-execution",
    }


def test_restore_check_rejects_missing_backup(tmp_path):
    with pytest.raises(ValueError, match="No backup source found"):
        run_restore_check(
            backup_root=tmp_path / "missing-remotes",
            backup_name="memorywiki-core",
            project_root=tmp_path / "project",
            global_root=tmp_path / "global",
            python=sys.executable,
        )


def test_restore_check_rejects_symlinked_backup_root(tmp_path):
    real_root = tmp_path / "real-remotes"
    real_root.mkdir()
    link_root = tmp_path / "link-remotes"
    link_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(ValueError, match="real directory"):
        run_restore_check(
            backup_root=link_root,
            backup_name="memorywiki-core",
            project_root=tmp_path / "project",
            global_root=tmp_path / "global",
            python=sys.executable,
        )


def test_restore_check_rejects_unsafe_backup_name(tmp_path):
    backup_root = tmp_path / "remotes"
    backup_root.mkdir()

    with pytest.raises(ValueError, match="Backup name"):
        run_restore_check(
            backup_root=backup_root,
            backup_name="../memorywiki-core",
            project_root=tmp_path / "project",
            global_root=tmp_path / "global",
            python=sys.executable,
        )


def test_restore_check_cli_outputs_json(tmp_path):
    source = tmp_path / "memorywiki-source"
    _copy_memorywiki_source(source)
    backup_root = tmp_path / "remotes"
    backup_memory(
        root=source,
        backup_root=backup_root,
        name="memorywiki-core",
        message="checkpoint memorywiki source",
    )
    project = tmp_path / "project-memory"
    global_root = tmp_path / "global-memory"
    project.mkdir()
    global_root.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "memorywiki_restore_check.py",
            "--backup-root",
            str(backup_root),
            "--backup-name",
            "memorywiki-core",
            "--project-root",
            str(project),
            "--global-root",
            str(global_root),
            "--restore-parent",
            str(tmp_path / "restore"),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["source_kind"] == "bundle"
