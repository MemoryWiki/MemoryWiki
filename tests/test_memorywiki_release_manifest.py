from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from memorywiki_release_manifest import (
    MAX_HASH_BYTES,
    build_manifest,
    verify_manifest,
    write_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _seed_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    memorywiki = repo
    (memorywiki / "memory_system").mkdir(parents=True)
    (memorywiki / "memory_system" / "__init__.py").write_text("# package\n", encoding="utf-8")
    (memorywiki / "memory_health.py").write_text("print('health')\n", encoding="utf-8")
    (memorywiki / "README.md").write_text("# MemoryWiki\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "seed",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo, memorywiki


def test_release_manifest_records_artifacts_and_verifies(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    skill = tmp_path / "memorywiki-v0.1.0.skill"
    skill.write_text("skill archive bytes\n", encoding="utf-8")
    bundle = tmp_path / "memorywiki-core.bundle"
    bundle.write_text("backup bundle bytes\n", encoding="utf-8")
    release_check = {
        "status": "ok",
        "required_failures": [],
        "optional_failures": [],
        "results": [{"name": "memorywiki-tests", "returncode": 0, "required": True}],
    }

    manifest = build_manifest(
        repo_root=repo,
        memorywiki_root=memorywiki,
        skill_archive=skill,
        backup_bundle=bundle,
        release_check=release_check,
        now="2026-05-16T00:00:00+00:00",
    )
    path = write_manifest(
        out=tmp_path / "manifest.json",
        repo_root=repo,
        memorywiki_root=memorywiki,
        skill_archive=skill,
        backup_bundle=bundle,
        release_check=release_check,
        now="2026-05-16T00:00:00+00:00",
    )
    verify = verify_manifest(path)

    assert manifest["schema"] == "memorywiki-release-manifest-v1"
    assert manifest["repo"]["commit"]
    assert manifest["repo"]["root"] == "."
    assert manifest["memorywiki"]["file_count"] >= 3
    assert len(manifest["memorywiki"]["files_sha256"]) == 64
    assert len(manifest["artifacts"]["skill_archive"]["sha256"]) == 64
    assert len(manifest["artifacts"]["backup_bundle"]["sha256"]) == 64
    assert manifest["release_check"]["status"] == "ok"
    assert verify["status"] == "ok"


def test_release_manifest_records_retrieval_baseline_and_compares_previous(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    previous = tmp_path / "previous.json"
    previous.write_text(
        json.dumps(
            {
                "schema": "memorywiki-release-manifest-v1",
                "retrieval_baseline": {
                    "current": {
                        "cases": {
                            "core": {
                                "passed": True,
                                "rank": 1,
                                "failure_reason": "",
                                "required": True,
                                "min_rank": 2,
                            },
                            "optional": {
                                "passed": True,
                                "rank": 2,
                                "failure_reason": "",
                                "required": False,
                            },
                        },
                        "mean_reciprocal_rank": 0.75,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    release_check = {
        "status": "ok",
        "required_failures": [],
        "optional_failures": [],
        "results": [
            {
                "name": "retrieval-golden-eval",
                "returncode": 0,
                "required": True,
                "json": {
                    "status": "pass",
                    "mean_reciprocal_rank": 0.5,
                    "cases": [
                        {
                            "name": "core",
                            "passed": False,
                            "rank": 3,
                            "failure_reason": "matched at rank 3 exceeds min_rank 2",
                            "required": True,
                            "min_rank": 2,
                            "severity": "core",
                        },
                        {
                            "name": "optional",
                            "passed": True,
                            "rank": 4,
                            "failure_reason": "",
                            "required": False,
                            "severity": "watch",
                        },
                    ],
                },
            }
        ],
    }

    manifest = build_manifest(
        repo_root=repo,
        memorywiki_root=memorywiki,
        release_check=release_check,
        previous_manifest=previous,
        now="2026-05-16T00:00:00+00:00",
    )
    comparison = manifest["retrieval_baseline"]["comparison"]

    assert manifest["retrieval_baseline"]["current"]["case_count"] == 2
    assert comparison["status"] == "fail"
    assert comparison["previous_manifest"] == previous.name
    assert any(item["case"] == "core" and item["level"] == "fail" for item in comparison["regressions"])
    assert any(item["case"] == "optional" and item["level"] == "warn" for item in comparison["regressions"])


def test_release_manifest_limits_repo_status_to_memorywiki_release_scope(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    (repo / "README.md").write_text("unrelated repo change\n", encoding="utf-8")
    (repo / "scratch.txt").write_text("untracked unrelated file\n", encoding="utf-8")
    (memorywiki / "README.md").write_text("# MemoryWiki changed\n", encoding="utf-8")

    manifest = build_manifest(repo_root=repo, memorywiki_root=memorywiki, now="2026-05-16T00:00:00+00:00")
    status = "\n".join(manifest["repo"]["status_short"])

    assert manifest["repo"]["dirty"] is True
    assert "README.md" in status
    assert "scratch.txt" not in status
    assert "README.md" not in status.replace("README.md", "")
    assert manifest["repo"]["omitted_status_count"] >= 1


def test_release_manifest_verify_detects_tampered_skill_archive(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    skill = repo / "memorywiki-v0.1.0.skill"
    skill.write_text("skill archive bytes\n", encoding="utf-8")
    bundle = repo / "memorywiki-core.bundle"
    bundle.write_text("backup bundle bytes\n", encoding="utf-8")
    path = write_manifest(
        out=tmp_path / "manifest.json",
        repo_root=repo,
        memorywiki_root=memorywiki,
        skill_archive=skill,
        backup_bundle=bundle,
        release_check={"status": "ok", "results": []},
    )
    skill.write_text("tampered\n", encoding="utf-8")

    verify = verify_manifest(path)

    assert verify["status"] == "fail"
    assert any(check["target"] == "skill_archive" for check in verify["checks"])


def test_release_manifest_verify_checks_external_artifact_hashes(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    skill = tmp_path / "memorywiki-v0.1.0.skill"
    skill.write_text("skill archive bytes\n", encoding="utf-8")
    path = write_manifest(
        out=tmp_path / "manifest.json",
        repo_root=repo,
        memorywiki_root=memorywiki,
        skill_archive=skill,
        release_check={"status": "ok", "results": []},
    )

    skill.write_text("tampered external archive\n", encoding="utf-8")
    verify = verify_manifest(path)

    assert verify["status"] == "fail"
    assert any(
        check["target"] == "skill_archive" and check["status"] == "changed"
        for check in verify["checks"]
    )


def test_release_manifest_verify_fails_missing_external_artifact(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    skill = tmp_path / "memorywiki-v0.1.0.skill"
    skill.write_text("skill archive bytes\n", encoding="utf-8")
    path = write_manifest(
        out=tmp_path / "manifest.json",
        repo_root=repo,
        memorywiki_root=memorywiki,
        skill_archive=skill,
        release_check={"status": "ok", "results": []},
    )

    skill.unlink()
    verify = verify_manifest(path)

    assert verify["status"] == "fail"
    assert any(
        check["target"] == "skill_archive" and check["status"] == "missing"
        for check in verify["checks"]
    )


def test_release_manifest_uses_public_safe_paths_for_external_artifacts(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    skill = tmp_path / "memorywiki-v0.1.0.skill"
    skill.write_text("skill archive bytes\n", encoding="utf-8")
    manifest = build_manifest(
        repo_root=repo,
        memorywiki_root=memorywiki,
        skill_archive=skill,
        release_check={"status": "ok", "results": []},
    )
    encoded = json.dumps(manifest)

    assert str(tmp_path) not in encoded
    assert manifest["repo"]["root"] == "."
    assert manifest["artifacts"]["skill_archive"]["path"] == skill.name
    assert manifest["artifacts"]["skill_archive"]["path_kind"] == "external-basename"


def test_release_manifest_cli_generates_and_verifies(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    skill = tmp_path / "memorywiki-v0.1.0.skill"
    skill.write_text("skill archive bytes\n", encoding="utf-8")
    bundle = tmp_path / "memorywiki-core.bundle"
    bundle.write_text("backup bundle bytes\n", encoding="utf-8")
    release_check = tmp_path / "release-check.json"
    release_check.write_text(json.dumps({"status": "ok", "results": []}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"

    result = subprocess.run(
        [
            sys.executable,
            "memorywiki_release_manifest.py",
            "--repo-root",
            str(repo),
            "--memorywiki-root",
            str(memorywiki),
            "--skill-archive",
            str(skill),
            "--backup-bundle",
            str(bundle),
            "--release-check-json",
            str(release_check),
            "--out",
            str(manifest),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    verify = subprocess.run(
        [
            sys.executable,
            "memorywiki_release_manifest.py",
            "--verify",
            str(manifest),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout)["manifest_path"] == str(manifest)
    assert json.loads(verify.stdout)["status"] == "ok"


def test_release_manifest_rejects_symlinked_artifact(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    outside = tmp_path / "outside.skill"
    outside.write_text("outside\n", encoding="utf-8")
    link = tmp_path / "linked.skill"
    link.symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        build_manifest(repo_root=repo, memorywiki_root=memorywiki, skill_archive=link)


def test_release_manifest_rejects_symlinked_output_parent(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    real_dir = tmp_path / "real-manifests"
    real_dir.mkdir()
    link_dir = tmp_path / "linked-manifests"
    link_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        write_manifest(out=link_dir / "manifest.json", repo_root=repo, memorywiki_root=memorywiki)


def test_release_manifest_verify_rejects_oversized_artifact_without_hashing(tmp_path):
    repo, _ = _seed_repo(tmp_path)
    big = tmp_path / "oversized.skill"
    with big.open("wb") as handle:
        handle.truncate(MAX_HASH_BYTES + 1)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "memorywiki-release-manifest-v1",
                "repo": {"root": str(repo)},
                "memorywiki": {"files": [], "files_sha256": ""},
                "artifacts": {
                    "skill_archive": {
                        "path": str(big),
                        "bytes": big.stat().st_size,
                        "sha256": "0" * 64,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    verify = verify_manifest(manifest)

    assert verify["status"] == "fail"
    assert any(
        check["target"] == "skill_archive" and check["status"] == "unsafe"
        for check in verify["checks"]
    )


def test_release_manifest_verify_rejects_oversized_expected_file_without_hashing(tmp_path):
    repo, memorywiki = _seed_repo(tmp_path)
    big = memorywiki / "oversized.bin"
    with big.open("wb") as handle:
        handle.truncate(MAX_HASH_BYTES + 1)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "memorywiki-release-manifest-v1",
                "repo": {"root": str(repo)},
                "memorywiki": {
                    "root": ".",
                    "files": [
                        {
                            "path": "oversized.bin",
                            "bytes": big.stat().st_size,
                            "sha256": "0" * 64,
                        }
                    ],
                    "files_sha256": "0" * 64,
                },
                "artifacts": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    verify = verify_manifest(manifest)

    assert verify["status"] == "fail"
    assert any(
        check["target"] == "oversized.bin" and check["status"] == "unsafe"
        for check in verify["checks"]
    )
