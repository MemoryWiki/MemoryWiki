from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memorywiki_release_manifest import (
    _latest_backup_bundle,
    _safe_file,
    _sha256_file,
)
from memorywiki_release_manifest import (
    write_manifest as write_release_manifest,
)

MAX_SKILL_ARCHIVE_BYTES = 50_000_000
SKILL_SOURCE_SKIP_DIRS = {
    ".agent_memory",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "release_manifests",
    "venv",
}
SKILL_SOURCE_SKIP_SUFFIXES = {".pyc", ".pyo"}


@dataclass
class ReleaseCommand:
    name: str
    argv: list[str]
    required: bool = True


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_skill_source_files(source_dir: str | Path) -> dict[str, dict[str, Any]]:
    source = Path(source_dir).expanduser()
    if not source.exists() or source.is_symlink() or not source.is_dir():
        raise ValueError(f"Skill source must be a real directory: {source}")
    for ancestor in source.parents:
        if ancestor.is_symlink():
            raise ValueError(f"Skill source may not be below a symlink: {ancestor}")
    rows: dict[str, dict[str, Any]] = {}
    for current, dirs, files in os.walk(source):
        current_path = Path(current)
        kept_dirs = []
        for dirname in sorted(dirs):
            if dirname in SKILL_SOURCE_SKIP_DIRS or dirname.endswith(".egg-info"):
                continue
            if (current_path / dirname).is_symlink():
                raise ValueError("Skill source may not contain symlinked directories: %s" % (current_path / dirname))
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs
        for filename in sorted(files):
            path = current_path / filename
            if path.is_symlink():
                raise ValueError(f"Skill source may not contain symlinked files: {path}")
            if not path.is_file():
                continue
            if path.suffix in SKILL_SOURCE_SKIP_SUFFIXES:
                continue
            if path.stat().st_size > MAX_SKILL_ARCHIVE_BYTES:
                raise ValueError(f"Skill source file exceeds safe hash limit: {path}")
            rel = path.relative_to(source).as_posix()
            data = path.read_bytes()
            rows[rel] = {"bytes": len(data), "sha256": _sha256_bytes(data)}
    if not rows:
        raise ValueError(f"Skill source contains no files: {source}")
    return rows


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def _safe_archive_rel(name: str, top_level: str) -> str | None:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../") or normalized == "..":
        raise ValueError(f"Unsafe skill archive entry: {name}")
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"Unsafe skill archive entry: {name}")
    if parts[0] != top_level:
        raise ValueError(f"Skill archive entry must stay under {top_level}/: {name}")
    if len(parts) == 1:
        return None
    return "/".join(parts[1:])


def _hash_zip_entry_capped(
    handle: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    remaining_limit: int,
) -> dict[str, Any]:
    digest = hashlib.sha256()
    total = 0
    with handle.open(info) as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SKILL_ARCHIVE_BYTES or total > remaining_limit:
                raise ValueError("Skill archive uncompressed content exceeds safe validation limit")
            digest.update(chunk)
    return {"bytes": total, "sha256": digest.hexdigest()}


def validate_skill_archive(skill_archive: str | Path, skill_source_dir: str | Path) -> dict[str, Any]:
    archive = Path(skill_archive).expanduser()
    source = Path(skill_source_dir).expanduser()
    if not archive.exists() or archive.is_symlink() or not archive.is_file():
        raise ValueError(f"Skill archive must be a real file: {archive}")
    if archive.stat().st_size > MAX_SKILL_ARCHIVE_BYTES:
        raise ValueError(f"Skill archive exceeds safe validation limit: {archive}")
    expected = _safe_skill_source_files(source)
    actual: dict[str, dict[str, Any]] = {}
    top_level = source.name
    with zipfile.ZipFile(archive) as handle:
        total_uncompressed = 0
        for info in handle.infolist():
            if _is_zip_symlink(info):
                raise ValueError(f"Skill archive may not contain symlinks: {info.filename}")
            rel = _safe_archive_rel(info.filename, top_level)
            if rel is None or info.is_dir():
                continue
            if rel in actual:
                raise ValueError(f"Skill archive contains duplicate file: {rel}")
            total_uncompressed += info.file_size
            if info.file_size > MAX_SKILL_ARCHIVE_BYTES or total_uncompressed > MAX_SKILL_ARCHIVE_BYTES:
                raise ValueError("Skill archive uncompressed content exceeds safe validation limit")
            actual[rel] = _hash_zip_entry_capped(
                handle,
                info,
                MAX_SKILL_ARCHIVE_BYTES - (total_uncompressed - info.file_size),
            )
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatched = sorted(
        rel
        for rel in set(expected).intersection(actual)
        if expected[rel]["bytes"] != actual[rel]["bytes"]
        or expected[rel]["sha256"] != actual[rel]["sha256"]
    )
    if missing or extra or mismatched:
        raise ValueError(
            f"Skill archive/source mismatch: missing={missing} extra={extra} mismatch={mismatched}"
        )
    return {
        "archive": str(archive.resolve()),
        "source_dir": str(source.resolve()),
        "file_count": len(actual),
        "status": "ok",
    }


def _stage_release_artifact(source: str | Path | None, manifest_path: Path) -> Path | None:
    if not source:
        return None
    safe_source = _safe_file(source, "Release artifact")
    parent = manifest_path.expanduser().parent
    if not parent.exists() or parent.is_symlink() or not parent.is_dir():
        raise ValueError(f"Manifest output parent must be a real directory: {parent}")
    for ancestor in parent.parents:
        if ancestor.is_symlink():
            raise ValueError(f"Manifest output parent may not be below a symlink: {ancestor}")
    destination = (parent / safe_source.name).resolve()
    if destination == safe_source:
        return destination
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError(f"Release artifact destination is unsafe: {destination}")
        if destination.stat().st_size != safe_source.stat().st_size or _sha256_file(destination) != _sha256_file(safe_source):
            raise ValueError(f"Release artifact destination already exists with different content: {destination}")
        return destination
    shutil.copy2(safe_source, destination)
    return destination


def _stage_manifest_artifacts(
    *,
    manifest_path: Path,
    skill_archive: str | Path | None,
    backup_root: str | Path | None,
    backup_name: str,
) -> list[Path]:
    staged: list[Path] = []
    skill = _stage_release_artifact(skill_archive, manifest_path)
    if skill is not None:
        staged.append(skill)
    if backup_root:
        bundle = _latest_backup_bundle(backup_root, backup_name)
        backup = _stage_release_artifact(bundle, manifest_path)
        if backup is not None:
            staged.append(backup)
    return staged


def build_release_commands(
    *,
    python: str,
    test_python: str,
    repo_root: str,
    project_root: str,
    global_root: str,
    config: str,
    project_matrix_config: str = "",
    mcp_contract: str = "",
    golden_case_registry: str = "",
    ops_release_manifest: str = "",
    skill_archive: str = "",
    backup_root: str = "",
    backup_name: str = "memorywiki-core",
    max_backup_age_hours: int = 168,
    skip_tests: bool = False,
    skip_smoke: bool = False,
    skip_project_matrix: bool = False,
    skip_restore_check: bool = False,
    allow_dirty: bool = False,
) -> list[ReleaseCommand]:
    commands = [
        ReleaseCommand(
            "index-maintain",
            [
                python,
                "memory_index_maintain.py",
                "--project-root",
                project_root,
                "--global-root",
                global_root,
                "--scope",
                "all",
                "--format",
                "json",
            ],
        ),
        ReleaseCommand(
            "memory-health",
            [
                python,
                "memory_health.py",
                "--project-root",
                project_root,
                "--global-root",
                global_root,
                "--scope",
                "all",
                "--format",
                "json",
            ],
        ),
        ReleaseCommand(
            "memory-review",
            [
                python,
                "memory_review.py",
                "--project-root",
                project_root,
                "--global-root",
                global_root,
                "--scope",
                "all",
                "--format",
                "json",
            ],
        ),
        ReleaseCommand(
            "quality-report",
            [
                python,
                "memorywiki_quality_report.py",
                "--project-root",
                project_root,
                "--global-root",
                global_root,
                "--scope",
                "all",
                "--case-file",
                golden_case_registry or "docs/memorywiki-golden-cases.json",
                "--format",
                "json",
            ],
        ),
        ReleaseCommand(
            "memory-lifecycle",
            [
                python,
                "memory_lifecycle.py",
                "--project-root",
                project_root,
                "--global-root",
                global_root,
                "--scope",
                "all",
                "--format",
                "json",
            ]
            + (
                [
                    "--backup-root",
                    backup_root,
                    "--backup-name",
                    backup_name,
                    "--max-backup-age-hours",
                    str(max_backup_age_hours),
                    "--fail-on-backup-issue",
                ]
                if backup_root
                else []
            ),
        ),
    ]
    if backup_root and not skip_restore_check:
        commands.append(
            ReleaseCommand(
                "restore-check",
                [
                    python,
                    "memorywiki_restore_check.py",
                    "--backup-root",
                    backup_root,
                    "--backup-name",
                    backup_name,
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--python",
                    python,
                    "--format",
                    "json",
                ],
            )
        )
    commands.extend(
        [
            ReleaseCommand(
                "mcp-doctor",
                [
                    python,
                    "memorywiki_mcp_doctor.py",
                    "--python",
                    python,
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--config",
                    config,
                    "--format",
                    "json",
                ],
            ),
            ReleaseCommand(
                "mcp-contract",
                [
                    python,
                    "memorywiki_mcp_contract.py",
                    "--verify",
                    mcp_contract or "docs/memorywiki-mcp-v1-contract.json",
                    "--format",
                    "json",
                ],
            ),
            ReleaseCommand(
                "retrieval-golden-eval",
                [
                    python,
                    "retrieval_golden_eval.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--case-file",
                    golden_case_registry or "docs/memorywiki-golden-cases.json",
                    "--format",
                    "json",
                ],
            ),
            ReleaseCommand(
                "ops-dashboard",
                [
                    python,
                    "memorywiki_ops_dashboard.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--python",
                    python,
                    "--mcp-config",
                    config,
                    "--period",
                    "daily",
                    "--format",
                    "json",
                ]
                + (
                    [
                        "--project-matrix-config",
                        project_matrix_config,
                    ]
                    if project_matrix_config and not skip_project_matrix
                    else ["--skip-project-matrix"]
                )
                + (
                    [
                        "--release-manifest",
                        ops_release_manifest,
                    ]
                    if ops_release_manifest
                    else []
                ),
                required=False,
            ),
            ReleaseCommand(
                "knowledge-ops",
                [
                    python,
                    "memorywiki_knowledge_ops.py",
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--python",
                    python,
                    "--mcp-config",
                    config,
                    "--period",
                    "daily",
                    "--format",
                    "json",
                ]
                + (
                    [
                        "--project-matrix-config",
                        project_matrix_config,
                    ]
                    if project_matrix_config and not skip_project_matrix
                    else ["--skip-project-matrix"]
                )
                + (
                    [
                        "--release-manifest",
                        ops_release_manifest,
                    ]
                    if ops_release_manifest
                    else []
                ),
                required=False,
            ),
        ]
    )
    if not skip_smoke:
        commands.append(
            ReleaseCommand(
                "mcp-smoke",
                [
                    python,
                    "-m",
                    "memorywiki_mcp.smoke_client",
                    "--python",
                    python,
                    "--repo-root",
                    repo_root,
                    "--project-root",
                    project_root,
                    "--global-root",
                    global_root,
                    "--temp-write-check",
                ],
                required=False,
            )
        )
    if project_matrix_config and not skip_project_matrix:
        commands.append(
            ReleaseCommand(
                "project-matrix",
                [
                    python,
                    "memorywiki_project_matrix.py",
                    "--config",
                    project_matrix_config,
                    "--python",
                    python,
                    "--global-root",
                    global_root,
                    "--format",
                    "json",
                ],
                required=False,
            )
        )
    if skill_archive:
        commands.append(
            ReleaseCommand(
                "skill-archive",
                ["zip", "-T", skill_archive],
                required=False,
            )
        )
    if not skip_tests:
        commands.append(
            ReleaseCommand(
                "memorywiki-tests",
                [test_python, "-m", "pytest", "tests", "-q"],
            )
        )
    commands.extend(
        [
            ReleaseCommand(
                "compileall",
                [python, "-m", "compileall", "-q", "."],
            ),
            ReleaseCommand(
                "git-status",
                [
                    "git",
                    "status",
                    "--short",
                    ".",
                    "AGENTS.md",
                    ".mcp.json",
                    "pyproject.toml",
                ],
                required=not allow_dirty,
            ),
            ReleaseCommand(
                "backup-remote",
                ["git", "remote", "get-url", "origin"],
                required=False,
            ),
        ]
    )
    return commands


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    required_failures = [
        result for result in results if result.get("required") and result.get("returncode") != 0
    ]
    optional_failures = [
        result
        for result in results
        if not result.get("required") and result.get("returncode") != 0
    ]
    if required_failures:
        status = "fail"
    elif optional_failures:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "required_failures": [item["name"] for item in required_failures],
        "optional_failures": [item["name"] for item in optional_failures],
        "results": results,
    }


def _mcp_extra_supported(python: str) -> bool:
    completed = subprocess.run(
        [
            python,
            "-c",
            "import sys; print('%d.%d' % sys.version_info[:2])",
        ],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        # Let the actual smoke command expose an invalid Python path.
        return True
    try:
        major, minor = completed.stdout.strip().split(".", 1)
        return (int(major), int(minor)) >= (3, 10)
    except (TypeError, ValueError):
        return True


def run_release_check(
    *,
    python: str,
    test_python: str,
    repo_root: str | Path,
    project_root: str | Path,
    global_root: str | Path,
    config: str | Path,
    project_matrix_config: str | Path | None = None,
    mcp_contract: str | Path | None = None,
    golden_case_registry: str | Path | None = None,
    ops_release_manifest: str | Path | None = None,
    skill_archive: str | Path | None = None,
    backup_root: str | Path | None = None,
    backup_name: str = "memorywiki-core",
    max_backup_age_hours: int = 168,
    manifest_out: str | Path | None = None,
    skip_tests: bool = False,
    skip_smoke: bool = False,
    skip_project_matrix: bool = False,
    skip_restore_check: bool = False,
    allow_dirty: bool = False,
    skill_source_dir: str | Path | None = None,
) -> dict[str, Any]:
    repo = Path(repo_root).expanduser().resolve()
    env = None
    commands = build_release_commands(
        python=str(python),
        test_python=str(test_python),
        repo_root=str(repo),
        project_root=str(Path(project_root).expanduser()),
        global_root=str(Path(global_root).expanduser()),
        config=str(Path(config).expanduser()),
        project_matrix_config=(
            str(Path(project_matrix_config).expanduser()) if project_matrix_config else ""
        ),
        mcp_contract=str(Path(mcp_contract).expanduser()) if mcp_contract else "",
        golden_case_registry=(
            str(Path(golden_case_registry).expanduser()) if golden_case_registry else ""
        ),
        ops_release_manifest=(
            str(Path(ops_release_manifest).expanduser()) if ops_release_manifest else ""
        ),
        skill_archive=str(Path(skill_archive).expanduser()) if skill_archive else "",
        backup_root=str(Path(backup_root).expanduser()) if backup_root else "",
        backup_name=backup_name,
        max_backup_age_hours=max_backup_age_hours,
        skip_tests=skip_tests,
        skip_smoke=skip_smoke,
        skip_project_matrix=skip_project_matrix,
        skip_restore_check=skip_restore_check,
        allow_dirty=allow_dirty,
    )
    results: list[dict[str, Any]] = []
    for command in commands:
        if command.name == "mcp-smoke" and not _mcp_extra_supported(str(python)):
            results.append(
                {
                    "name": command.name,
                    "argv": command.argv,
                    "required": command.required,
                    "returncode": 0,
                    "stdout": "Skipped: MemoryWiki MCP smoke requires Python >=3.10 because the mcp extra is only installed on supported runtimes.",
                    "stderr": "",
                    "skipped": True,
                }
            )
            continue
        completed = subprocess.run(
            command.argv,
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
        )
        result = {
            "name": command.name,
            "argv": command.argv,
            "required": command.required,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
        if command.name == "git-status" and completed.returncode == 0 and completed.stdout.strip():
            if allow_dirty:
                result["stderr"] = (result["stderr"] + "\n" if result["stderr"] else "") + (
                    "Scoped git status is dirty allowed by --allow-dirty."
                )
            else:
                result["returncode"] = 1
                result["stderr"] = (result["stderr"] + "\n" if result["stderr"] else "") + (
                    "Scoped git status is dirty; commit changes or pass --allow-dirty."
                )
        if command.name in {
            "retrieval-golden-eval",
            "quality-report",
            "ops-dashboard",
            "knowledge-ops",
        }:
            try:
                result["json"] = json.loads(completed.stdout or "{}")
            except json.JSONDecodeError:
                pass
        results.append(result)
        if command.required and completed.returncode != 0:
            break
        if command.required and result["returncode"] != 0:
            break
    if skill_archive:
        if not skill_source_dir:
            results.append(
                {
                    "name": "skill-archive-source",
                    "argv": [
                        "internal:validate_skill_archive",
                        str(skill_archive),
                        "<required --skill-source-dir>",
                    ],
                    "required": True,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "--skill-source-dir is required when --skill-archive is provided.",
                }
            )
        else:
            source_dir = skill_source_dir
            try:
                validation = validate_skill_archive(skill_archive, source_dir)
                results.append(
                    {
                        "name": "skill-archive-source",
                        "argv": ["internal:validate_skill_archive", str(skill_archive), str(source_dir)],
                        "required": True,
                        "returncode": 0,
                        "stdout": json.dumps(validation, ensure_ascii=False),
                        "stderr": "",
                    }
                )
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                results.append(
                    {
                        "name": "skill-archive-source",
                        "argv": ["internal:validate_skill_archive", str(skill_archive), str(source_dir)],
                        "required": True,
                        "returncode": 1,
                        "stdout": "",
                        "stderr": str(exc),
                    }
                )
    summary = summarize_results(results)
    if manifest_out:
        manifest_path = Path(manifest_out).expanduser()
        try:
            staged_artifacts = _stage_manifest_artifacts(
                manifest_path=manifest_path,
                skill_archive=Path(skill_archive).expanduser() if skill_archive else None,
                backup_root=Path(backup_root).expanduser() if backup_root else None,
                backup_name=backup_name,
            )
            if staged_artifacts:
                results.append(
                    {
                        "name": "release-artifacts-stage",
                        "argv": ["internal:stage_release_artifacts", str(manifest_path.parent)],
                        "required": True,
                        "returncode": 0,
                        "stdout": json.dumps([path.name for path in staged_artifacts]),
                        "stderr": "",
                    }
                )
                summary = summarize_results(results)
            written = write_release_manifest(
                out=manifest_path,
                repo_root=repo,
                memorywiki_root=repo,
                skill_archive=Path(skill_archive).expanduser() if skill_archive else None,
                backup_root=Path(backup_root).expanduser() if backup_root else None,
                backup_name=backup_name,
                release_check=summary,
            )
            results.append(
                {
                    "name": "release-manifest",
                    "argv": ["internal:memorywiki_release_manifest", str(written)],
                    "required": True,
                    "returncode": 0,
                    "stdout": str(written),
                    "stderr": "",
                }
            )
            try:
                manifest_payload = json.loads(Path(written).read_text(encoding="utf-8"))
                baseline_status = (
                    manifest_payload.get("retrieval_baseline", {})
                    .get("comparison", {})
                    .get("status", "")
                )
            except (OSError, json.JSONDecodeError, AttributeError):
                baseline_status = ""
            if baseline_status in {"warn", "fail"}:
                results.append(
                    {
                        "name": "retrieval-baseline",
                        "argv": ["internal:retrieval_baseline", str(written)],
                        "required": baseline_status == "fail",
                        "returncode": 1,
                        "stdout": baseline_status,
                        "stderr": "",
                    }
                )
            summary = summarize_results(results)
            summary["manifest_path"] = str(written)
            if baseline_status in {"warn", "fail"}:
                written = write_release_manifest(
                    out=manifest_path,
                    repo_root=repo,
                    memorywiki_root=repo,
                    skill_archive=Path(skill_archive).expanduser() if skill_archive else None,
                    backup_root=Path(backup_root).expanduser() if backup_root else None,
                    backup_name=backup_name,
                    release_check=summary,
                )
        except (OSError, ValueError) as exc:
            results.append(
                {
                    "name": "release-manifest",
                    "argv": ["internal:memorywiki_release_manifest", str(manifest_path)],
                    "required": True,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": str(exc),
                }
            )
            summary = summarize_results(results)
            summary["manifest_path"] = None
    return summary


def render_human(payload: dict[str, Any]) -> str:
    lines = ["# MemoryWiki Release Check", "", "Status: {}".format(payload["status"]), ""]
    for result in payload["results"]:
        marker = "PASS" if result["returncode"] == 0 else "FAIL"
        required = "required" if result["required"] else "optional"
        lines.append("- [{}] {} ({})".format(marker, result["name"], required))
    if payload["required_failures"]:
        lines.append("")
        lines.append("Required failures: {}".format(", ".join(payload["required_failures"])))
    if payload["optional_failures"]:
        lines.append("")
        lines.append("Optional failures: {}".format(", ".join(payload["optional_failures"])))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MemoryWiki release/ops checklist.")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--test-python",
        default="python3",
        help="Python executable with pytest installed for the MemoryWiki test suite.",
    )
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--config", default=str(Path.cwd() / ".mcp.json"))
    parser.add_argument(
        "--project-matrix-config",
        default=str(Path(__file__).resolve().parent / "examples" / "project-matrix.example.json"),
        help="Optional project matrix config for cross-project ops checks.",
    )
    parser.add_argument(
        "--mcp-contract",
        default=str(Path(__file__).resolve().parent / "docs" / "memorywiki-mcp-v1-contract.json"),
        help="MCP v1 contract JSON to verify during release checks.",
    )
    parser.add_argument(
        "--golden-case-registry",
        default=str(Path(__file__).resolve().parent / "docs" / "memorywiki-golden-cases.json"),
        help="Golden eval case registry JSON used by quality report and retrieval eval.",
    )
    parser.add_argument(
        "--ops-release-manifest",
        help="Optional previous release manifest used as the ops dashboard retrieval baseline.",
    )
    parser.add_argument(
        "--skill-archive",
        help="Optional .skill archive to validate for zip integrity and source equivalence.",
    )
    parser.add_argument(
        "--skill-source-dir",
        help="Skill/source directory that the optional .skill archive must exactly match.",
    )
    parser.add_argument(
        "--backup-root",
        default=str(Path.home() / ".memorywiki" / "backups"),
        help="Backup root checked by memory_lifecycle.py before release.",
    )
    parser.add_argument("--backup-name", default="memorywiki-core")
    parser.add_argument("--max-backup-age-hours", type=int, default=168)
    parser.add_argument("--manifest-out", help="Optional path for a MemoryWiki release manifest JSON.")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--skip-project-matrix", action="store_true")
    parser.add_argument("--skip-restore-check", action="store_true")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow non-empty scoped git status; default fails release checks on dirty MemoryWiki files.",
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_release_check(
        python=args.python,
        test_python=args.test_python,
        repo_root=args.repo_root,
        project_root=args.project_root,
        global_root=args.global_root,
        config=args.config,
        project_matrix_config=args.project_matrix_config,
        mcp_contract=args.mcp_contract,
        golden_case_registry=args.golden_case_registry,
        ops_release_manifest=args.ops_release_manifest,
        skill_archive=args.skill_archive,
        skill_source_dir=args.skill_source_dir,
        backup_root=args.backup_root,
        backup_name=args.backup_name,
        max_backup_age_hours=args.max_backup_age_hours,
        manifest_out=args.manifest_out,
        skip_tests=args.skip_tests,
        skip_smoke=args.skip_smoke,
        skip_project_matrix=args.skip_project_matrix,
        skip_restore_check=args.skip_restore_check,
        allow_dirty=args.allow_dirty,
    )
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0 if payload["status"] in {"ok", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
