import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_leases import acquire_lease, cleanup_expired_leases, current_leases, release_lease

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_agent_lease_acquire_release_and_cleanup(tmp_path):
    root = tmp_path / "memory"

    active = acquire_lease(
        root=root,
        agent="audit-worker",
        task="security audit",
        kind="audit",
        ttl_seconds=60,
        now="2026-05-13T10:00:00+08:00",
    )
    expired = acquire_lease(
        root=root,
        agent="old-worker",
        task="old audit",
        kind="audit",
        ttl_seconds=1,
        now="2026-05-13T09:00:00+08:00",
    )

    released = release_lease(
        root=root,
        lease_id=active["lease_id"],
        reason="done",
        now="2026-05-13T10:01:00+08:00",
    )
    cleaned = cleanup_expired_leases(root=root, now="2026-05-13T10:02:00+08:00")
    current = current_leases(root=root, include_inactive=True)

    assert released["status"] == "released"
    assert [item["lease_id"] for item in cleaned] == [expired["lease_id"]]
    assert {item["status"] for item in current} == {"released", "expired"}
    assert not current_leases(root=root)


def test_agent_leases_cli_lists_active_json(tmp_path):
    root = tmp_path / "memory"

    subprocess.run(
        [
            sys.executable,
            "agent_leases.py",
            "acquire",
            "--root",
            str(root),
            "--agent",
            "codex",
            "--task",
            "project profile",
            "--ttl-seconds",
            "120",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    result = subprocess.run(
        [
            sys.executable,
            "agent_leases.py",
            "list",
            "--root",
            str(root),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["leases"][0]["agent"] == "codex"
    assert payload["leases"][0]["task"] == "project profile"


def test_agent_lease_exclusive_conflicts_on_kind(tmp_path):
    root = tmp_path / "memory"

    acquire_lease(
        root=root,
        agent="worker-one",
        task="security audit one",
        kind="audit",
        ttl_seconds=60,
        now="2026-05-15T10:00:00+08:00",
    )

    with pytest.raises(ValueError, match="Active lease conflict"):
        acquire_lease(
            root=root,
            agent="worker-two",
            task="security audit two",
            kind="audit",
            ttl_seconds=60,
            now="2026-05-15T10:00:30+08:00",
            exclusive=True,
            conflicts_on="kind",
        )


def test_agent_lease_exclusive_ignores_released_same_kind(tmp_path):
    root = tmp_path / "memory"

    first = acquire_lease(
        root=root,
        agent="worker-one",
        task="index rebuild one",
        kind="retrieval-index",
        ttl_seconds=60,
        now="2026-05-15T10:00:00+08:00",
        exclusive=True,
        conflicts_on="kind",
    )
    release_lease(
        root=root,
        lease_id=first["lease_id"],
        reason="complete",
        now="2026-05-15T10:00:10+08:00",
    )

    second = acquire_lease(
        root=root,
        agent="worker-two",
        task="index rebuild two",
        kind="retrieval-index",
        ttl_seconds=60,
        now="2026-05-15T10:00:20+08:00",
        exclusive=True,
        conflicts_on="kind",
    )

    assert second["status"] == "active"


def test_agent_leases_cli_exclusive_conflict_returns_error(tmp_path):
    root = tmp_path / "memory"

    subprocess.run(
        [
            sys.executable,
            "agent_leases.py",
            "acquire",
            "--root",
            str(root),
            "--agent",
            "worker-one",
            "--task",
            "security audit one",
            "--kind",
            "audit",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    result = subprocess.run(
        [
            sys.executable,
            "agent_leases.py",
            "acquire",
            "--root",
            str(root),
            "--agent",
            "worker-two",
            "--task",
            "security audit two",
            "--kind",
            "audit",
            "--exclusive",
            "--conflicts-on",
            "kind",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "Active lease conflict" in result.stderr


def test_agent_leases_reject_symlinked_root(tmp_path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    link_root = tmp_path / "link"
    link_root.symlink_to(real_root, target_is_directory=True)

    result = subprocess.run(
        [
            sys.executable,
            "agent_leases.py",
            "list",
            "--root",
            str(link_root),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "real directory" in result.stderr
