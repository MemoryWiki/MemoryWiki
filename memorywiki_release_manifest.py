from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


SCHEMA = "memorywiki-release-manifest-v1"
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "release_manifests"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
MAX_HASH_BYTES = 50_000_000
REPO_STATUS_PREFIXES = (
    "memory_system/",
    "memorywiki_mcp/",
    "tests/",
    "docs/",
    "examples/",
    "README.md",
    "README.zh.md",
    "pyproject.toml",
    ".gitignore",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_dir(path: str | Path, label: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.exists() or resolved.is_symlink() or not resolved.is_dir():
        raise ValueError("%s must be a real directory: %s" % (label, resolved))
    for ancestor in resolved.parents:
        if ancestor.is_symlink():
            raise ValueError("%s may not be below a symlink: %s" % (label, ancestor))
    return resolved.resolve()


def _safe_file(path: str | Path, label: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.exists() or resolved.is_symlink() or not resolved.is_file():
        raise ValueError("%s must be a real file and not a symlink: %s" % (label, resolved))
    for ancestor in resolved.parents:
        if ancestor.is_symlink():
            raise ValueError("%s may not be below a symlink: %s" % (label, ancestor))
    if resolved.stat().st_size > MAX_HASH_BYTES:
        raise ValueError("%s exceeds safe hash limit: %s" % (label, resolved))
    return resolved.resolve()


def _safe_name(name: str) -> str:
    if not SAFE_NAME_RE.fullmatch(name or ""):
        raise ValueError("Backup name may contain only letters, digits, dots, underscores, or dashes")
    return name


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_repo_relative_path(repo: Path, rel: str, label: str) -> Path:
    if rel in {"", "."}:
        return repo
    target = Path(rel)
    if target.is_absolute() or any(part in {"", ".", ".."} for part in target.parts):
        raise ValueError("%s must be a safe repo-relative path: %s" % (label, rel))
    resolved = (repo / target).resolve(strict=False)
    try:
        resolved.relative_to(repo.resolve())
    except ValueError:
        raise ValueError("%s escapes repo root: %s" % (label, rel))
    return repo / target


def _git(repo: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git"] + args,
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _git_status(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.rstrip("\n")


def _git_info(repo: Path) -> dict[str, Any]:
    status = _git_status(repo)
    status_lines = status.splitlines()
    relevant_status = [line for line in status_lines if _is_relevant_repo_status(line)]
    return {
        "root": ".",
        "root_name": repo.name,
        "branch": _git(repo, ["branch", "--show-current"]),
        "commit": _git(repo, ["rev-parse", "HEAD"]),
        "dirty": bool(status),
        "status_scope": list(REPO_STATUS_PREFIXES),
        "status_short": relevant_status[:200],
        "omitted_status_count": max(0, len(status_lines) - len(relevant_status)),
    }


def _status_path(line: str) -> str:
    if len(line) >= 4:
        return line[3:].strip()
    return line.strip()


def _is_relevant_repo_status(line: str) -> bool:
    path = _status_path(line)
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in REPO_STATUS_PREFIXES)


def _iter_memorywiki_files(repo: Path, memorywiki_root: Path) -> list[dict[str, Any]]:
    try:
        memorywiki_root.relative_to(repo)
    except ValueError:
        raise ValueError("MemoryWiki root must stay below repo root: %s" % memorywiki_root)
    rows: list[dict[str, Any]] = []
    for current, dirs, files in os.walk(memorywiki_root):
        current_path = Path(current)
        dirs[:] = sorted(dirname for dirname in dirs if dirname not in SKIP_DIRS)
        for filename in sorted(files):
            path = current_path / filename
            if path.suffix in SKIP_SUFFIXES or path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_size > MAX_HASH_BYTES:
                raise ValueError("MemoryWiki file exceeds safe hash limit: %s" % path)
            relative = path.relative_to(repo).as_posix()
            rows.append(
                {
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return rows


def _files_digest(files: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in files:
        digest.update(item["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(item["sha256"].encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item["bytes"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _public_path(path: Path | None, repo: Path | None = None) -> str:
    if path is None:
        return ""
    if repo is not None:
        try:
            return path.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def _artifact(path: str | Path | None, label: str, repo: Path) -> dict[str, Any] | None:
    if not path:
        return None
    safe = _safe_file(path, label)
    path_kind = "repo-relative"
    try:
        safe.relative_to(repo)
    except ValueError:
        path_kind = "external-basename"
    return {
        "path": _public_path(safe, repo),
        "path_kind": path_kind,
        "bytes": safe.stat().st_size,
        "sha256": _sha256_file(safe),
    }


def _latest_backup_bundle(backup_root: str | Path | None, backup_name: str) -> Path | None:
    if not backup_root:
        return None
    root = _safe_dir(backup_root, "Backup root")
    name = _safe_name(backup_name)
    candidates = [
        path
        for path in list(root.glob("%s-*.bundle" % name)) + [root / ("%s.bundle" % name)]
        if path.exists() and path.is_file() and not path.is_symlink()
    ]
    if not candidates:
        raise ValueError("No backup bundle found for %s under %s" % (name, root))
    return max(candidates, key=lambda item: item.stat().st_mtime).resolve()


def _read_release_check(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    safe = _safe_file(path, "Release check JSON")
    try:
        payload = json.loads(safe.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Release check JSON is invalid: %s" % safe) from exc
    if not isinstance(payload, dict):
        raise ValueError("Release check JSON must be an object: %s" % safe)
    return payload


def _summarize_release_check(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    results = payload.get("results", [])
    clean_results = []
    if isinstance(results, list):
        for item in results[:100]:
            if not isinstance(item, dict):
                continue
            clean_results.append(
                {
                    "name": str(item.get("name", ""))[:120],
                    "required": bool(item.get("required", False)),
                    "returncode": int(item.get("returncode", 0) or 0),
                }
            )
    return {
        "status": str(payload.get("status", ""))[:40],
        "required_failures": list(payload.get("required_failures", []))[:50]
        if isinstance(payload.get("required_failures", []), list)
        else [],
        "optional_failures": list(payload.get("optional_failures", []))[:50]
        if isinstance(payload.get("optional_failures", []), list)
        else [],
        "result_count": len(results) if isinstance(results, list) else 0,
        "results": clean_results,
    }


def _json_from_release_result(item: dict[str, Any]) -> dict[str, Any] | None:
    payload = item.get("json")
    if isinstance(payload, dict):
        return payload
    stdout = item.get("stdout", "")
    if not isinstance(stdout, str) or not stdout.strip():
        return None
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_retrieval_eval(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    results = payload.get("results", [])
    if not isinstance(results, list):
        return None
    selected = None
    for item in results:
        if not isinstance(item, dict):
            continue
        if item.get("name") == "retrieval-golden-eval":
            selected = _json_from_release_result(item)
            break
        if item.get("name") == "quality-report":
            quality = _json_from_release_result(item)
            if isinstance(quality, dict) and isinstance(quality.get("golden_eval"), dict):
                selected = quality["golden_eval"]
    if not isinstance(selected, dict):
        return None
    cases: dict[str, dict[str, Any]] = {}
    for item in selected.get("cases", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))[:200]
        if not name:
            continue
        cases[name] = {
            "passed": bool(item.get("passed", False)),
            "found": bool(item.get("found", item.get("rank") is not None)),
            "rank": item.get("rank"),
            "top_k": item.get("top_k"),
            "reciprocal_rank": item.get("reciprocal_rank", 0.0),
            "failure_reason": str(item.get("failure_reason", ""))[:500],
            "required": bool(item.get("required", True)),
            "min_rank": item.get("min_rank"),
            "severity": str(item.get("severity", ""))[:80],
            "owner": str(item.get("owner", ""))[:120],
            "project": str(item.get("project", ""))[:120],
        }
    return {
        "status": str(selected.get("status", ""))[:40],
        "pass_rate": selected.get("pass_rate"),
        "top_k_pass_rate": selected.get("top_k_pass_rate"),
        "mean_reciprocal_rank": selected.get("mean_reciprocal_rank"),
        "required_pass_rate": selected.get("required_pass_rate"),
        "required_failed": selected.get("required_failed"),
        "optional_failed": selected.get("optional_failed"),
        "case_count": len(cases),
        "cases": cases,
    }


def _read_previous_retrieval_baseline(path: str | Path | None) -> tuple[Path | None, dict[str, Any] | None]:
    if not path:
        return None, None
    safe = _safe_file(path, "Previous release manifest")
    payload = json.loads(safe.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return safe, None
    baseline = payload.get("retrieval_baseline", {})
    if not isinstance(baseline, dict):
        return safe, None
    current = baseline.get("current")
    return safe, current if isinstance(current, dict) else None


def _compare_retrieval_baseline(
    *,
    current: dict[str, Any] | None,
    previous_path: Path | None,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    if current is None:
        return {
            "status": "unavailable",
            "previous_manifest": _public_path(previous_path),
            "regressions": [],
        }
    if previous is None:
        return {
            "status": "no-baseline",
            "previous_manifest": _public_path(previous_path),
            "regressions": [],
        }
    regressions: list[dict[str, Any]] = []
    current_cases = current.get("cases", {}) if isinstance(current.get("cases"), dict) else {}
    previous_cases = previous.get("cases", {}) if isinstance(previous.get("cases"), dict) else {}
    for name, case in sorted(current_cases.items()):
        if not isinstance(case, dict):
            continue
        previous_case = previous_cases.get(name)
        if not isinstance(previous_case, dict):
            continue
        required = bool(case.get("required", True))
        level = "fail" if required else "warn"
        reasons: list[str] = []
        if previous_case.get("passed", False) and not case.get("passed", False):
            reasons.append("case regressed from pass to fail")
        previous_rank = previous_case.get("rank")
        current_rank = case.get("rank")
        if isinstance(previous_rank, int) and isinstance(current_rank, int) and current_rank > previous_rank:
            reasons.append("rank worsened from %s to %s" % (previous_rank, current_rank))
        min_rank = case.get("min_rank")
        if isinstance(min_rank, int) and isinstance(current_rank, int) and current_rank > min_rank:
            reasons.append("rank %s exceeds min_rank %s" % (current_rank, min_rank))
        if reasons:
            regressions.append(
                {
                    "case": name,
                    "level": level,
                    "required": required,
                    "previous_rank": previous_rank,
                    "current_rank": current_rank,
                    "reasons": reasons,
                    "failure_reason": case.get("failure_reason", ""),
                }
            )
    if any(item["level"] == "fail" for item in regressions):
        status = "fail"
    elif regressions:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "previous_manifest": _public_path(previous_path),
        "regressions": regressions,
    }


def _find_previous_manifest(out: Path) -> Path | None:
    parent = out.parent
    if not parent.exists() or parent.is_symlink() or not parent.is_dir():
        return None
    candidates = [
        path
        for path in parent.glob("memorywiki-v*.json")
        if path.resolve(strict=False) != out.resolve(strict=False)
        and path.is_file()
        and not path.is_symlink()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def build_manifest(
    *,
    repo_root: str | Path,
    memorywiki_root: str | Path | None = None,
    skill_archive: str | Path | None = None,
    backup_bundle: str | Path | None = None,
    backup_root: str | Path | None = None,
    backup_name: str = "memorywiki-core",
    release_check: dict[str, Any] | None = None,
    release_check_json: str | Path | None = None,
    previous_manifest: str | Path | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    repo = _safe_dir(repo_root, "Repo root")
    memorywiki = _safe_dir(memorywiki_root or repo, "MemoryWiki root")
    files = _iter_memorywiki_files(repo, memorywiki)
    bundle = Path(backup_bundle).expanduser() if backup_bundle else _latest_backup_bundle(backup_root, backup_name)
    release_payload = release_check if release_check is not None else _read_release_check(release_check_json)
    previous_path, previous_retrieval = _read_previous_retrieval_baseline(previous_manifest)
    current_retrieval = _extract_retrieval_eval(release_payload)
    return {
        "schema": SCHEMA,
        "generated_at": now or _now(),
        "repo": _git_info(repo),
        "memorywiki": {
            "root": memorywiki.relative_to(repo).as_posix(),
            "file_count": len(files),
            "files_sha256": _files_digest(files),
            "files": files,
        },
        "artifacts": {
            "skill_archive": _artifact(skill_archive, "Skill archive", repo),
            "backup_bundle": _artifact(bundle, "Backup bundle", repo),
        },
        "release_check": _summarize_release_check(release_payload),
        "retrieval_baseline": {
            "current": current_retrieval,
            "comparison": _compare_retrieval_baseline(
                current=current_retrieval,
                previous_path=previous_path,
                previous=previous_retrieval,
            ),
        },
    }


def _write_json_no_follow(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError("Manifest output may not be a symlink: %s" % path)
    _assert_no_symlink_output_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _assert_no_symlink_output_parent(path: Path) -> None:
    parent = path.parent
    cursor = parent
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError("Manifest output parent may not be a symlink: %s" % cursor)
    for ancestor in [parent] + list(parent.parents):
        if ancestor.exists() and ancestor.is_symlink():
            raise ValueError("Manifest output parent may not be below a symlink: %s" % ancestor)


def write_manifest(
    *,
    out: str | Path,
    repo_root: str | Path,
    memorywiki_root: str | Path | None = None,
    skill_archive: str | Path | None = None,
    backup_bundle: str | Path | None = None,
    backup_root: str | Path | None = None,
    backup_name: str = "memorywiki-core",
    release_check: dict[str, Any] | None = None,
    release_check_json: str | Path | None = None,
    previous_manifest: str | Path | None = None,
    now: str | None = None,
) -> Path:
    path = Path(out).expanduser()
    selected_previous = previous_manifest or _find_previous_manifest(path)
    manifest = build_manifest(
        repo_root=repo_root,
        memorywiki_root=memorywiki_root,
        skill_archive=skill_archive,
        backup_bundle=backup_bundle,
        backup_root=backup_root,
        backup_name=backup_name,
        release_check=release_check,
        release_check_json=release_check_json,
        previous_manifest=selected_previous,
        now=now,
    )
    if path.exists() and path.is_symlink():
        raise ValueError("Manifest output may not be a symlink: %s" % path)
    _write_json_no_follow(path, manifest)
    return path


def verify_manifest(manifest_path: str | Path) -> dict[str, Any]:
    path = _safe_file(manifest_path, "Manifest")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("Unsupported manifest schema: %s" % path)
    checks: list[dict[str, Any]] = []
    expected_files = payload.get("memorywiki", {}).get("files", [])
    actual_files = []
    if not isinstance(expected_files, list):
        expected_files = []
    repo = _resolve_manifest_repo_root(payload, path, expected_files)
    for item in expected_files:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path", ""))
        try:
            target = _safe_repo_relative_path(repo, rel, "Manifest MemoryWiki file")
        except ValueError as exc:
            checks.append({"target": rel, "status": "unsafe", "error": str(exc)})
            continue
        if not target.exists() or target.is_symlink() or not target.is_file():
            checks.append({"target": rel, "status": "missing"})
            continue
        try:
            safe_target = _safe_file(target, "Manifest MemoryWiki file")
        except ValueError as exc:
            checks.append({"target": rel, "status": "unsafe", "error": str(exc)})
            continue
        actual = {
            "path": rel,
            "bytes": safe_target.stat().st_size,
            "sha256": _sha256_file(safe_target),
        }
        actual_files.append(actual)
        checks.append(
            {
                "target": rel,
                "status": "ok"
                if actual["bytes"] == item.get("bytes") and actual["sha256"] == item.get("sha256")
                else "changed",
            }
        )
    expected_digest = payload.get("memorywiki", {}).get("files_sha256", "")
    actual_digest = _files_digest(actual_files)
    checks.append(
        {
            "target": "memorywiki.files_sha256",
            "status": "ok" if actual_digest == expected_digest else "changed",
        }
    )
    memorywiki_root_text = payload.get("memorywiki", {}).get("root", "")
    if memorywiki_root_text:
        try:
            memorywiki_root = _safe_repo_relative_path(repo, str(memorywiki_root_text), "Manifest MemoryWiki root")
            current_files = _iter_memorywiki_files(repo, memorywiki_root)
            checks.append(
                {
                    "target": "memorywiki.current_files_sha256",
                    "status": "ok" if _files_digest(current_files) == expected_digest else "changed",
                }
            )
        except ValueError as exc:
            checks.append({"target": "memorywiki.current_files_sha256", "status": "unsafe", "error": str(exc)})
    artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
    for label in ("skill_archive", "backup_bundle"):
        artifact = artifacts.get(label)
        if not artifact:
            continue
        if artifact.get("path_kind") == "external-basename":
            checks.append({"target": label, "status": "reference-only"})
            continue
        artifact_path = Path(str(artifact.get("path", ""))).expanduser()
        if not artifact_path.is_absolute():
            artifact_path = repo / artifact_path
        if not artifact_path.exists() or artifact_path.is_symlink() or not artifact_path.is_file():
            checks.append({"target": label, "status": "missing"})
            continue
        try:
            safe_artifact = _safe_file(artifact_path, "Manifest artifact %s" % label)
        except ValueError as exc:
            checks.append({"target": label, "status": "unsafe", "error": str(exc)})
            continue
        checks.append(
            {
                "target": label,
                "status": "ok"
                if safe_artifact.stat().st_size == artifact.get("bytes")
                and _sha256_file(safe_artifact) == artifact.get("sha256")
                else "changed",
            }
        )
    status = (
        "ok"
        if all(check["status"] in {"ok", "reference-only"} for check in checks)
        else "fail"
    )
    return {
        "status": status,
        "manifest_path": str(path),
        "checks": checks,
    }


def _resolve_manifest_repo_root(
    payload: dict[str, Any],
    manifest_path: Path,
    expected_files: list[Any],
) -> Path:
    repo_payload = payload.get("repo", {}) if isinstance(payload.get("repo", {}), dict) else {}
    repo_root_text = str(repo_payload.get("root", "."))
    root_name = str(repo_payload.get("root_name", "")).strip()
    root_path = Path(repo_root_text).expanduser()
    candidates: list[Path] = []
    if root_path.is_absolute():
        candidates.append(root_path)
    else:
        candidates.append((Path.cwd() / root_path).resolve())
        candidates.append((manifest_path.parent / root_path).resolve())
        if root_name:
            candidates.append((manifest_path.parent / root_name).resolve())
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen or not candidate.exists():
            continue
        seen.add(key)
        if expected_files and not _candidate_matches_manifest_files(candidate, expected_files):
            continue
        return _safe_dir(candidate, "Repo root")
    for candidate in candidates:
        if candidate.exists():
            return _safe_dir(candidate, "Repo root")
    return _safe_dir(candidates[0], "Repo root")


def _candidate_matches_manifest_files(candidate: Path, expected_files: list[Any]) -> bool:
    checked = 0
    for item in expected_files:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        path = candidate / str(item["path"])
        if not path.exists() or not path.is_file() or path.is_symlink():
            return False
        try:
            if path.stat().st_size != item.get("bytes") or _sha256_file(path) != item.get("sha256"):
                return False
        except OSError:
            return False
        checked += 1
        if checked >= 10:
            break
    return checked > 0


def render_human(payload: dict[str, Any]) -> str:
    if payload.get("schema") == SCHEMA:
        return (
            "# MemoryWiki Release Manifest\n\n"
            "Commit: {commit}\n"
            "MemoryWiki files: {count}\n"
            "MemoryWiki digest: {digest}\n"
        ).format(
            commit=payload["repo"]["commit"],
            count=payload["memorywiki"]["file_count"],
            digest=payload["memorywiki"]["files_sha256"],
        )
    lines = ["# MemoryWiki Release Manifest Verify", "", "Status: %s" % payload["status"], ""]
    for check in payload["checks"]:
        lines.append("- [{status}] {target}".format(**check))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate or verify a MemoryWiki release manifest.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--memorywiki-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--skill-archive")
    parser.add_argument("--backup-root")
    parser.add_argument("--backup-name", default="memorywiki-core")
    parser.add_argument("--backup-bundle")
    parser.add_argument("--release-check-json")
    parser.add_argument("--previous-manifest")
    parser.add_argument("--out")
    parser.add_argument("--now")
    parser.add_argument("--verify", help="Verify an existing manifest path instead of generating.")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify:
            payload = verify_manifest(args.verify)
            if args.format == "json":
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(render_human(payload), end="")
            return 0 if payload["status"] == "ok" else 1
        if args.out:
            path = write_manifest(
                out=args.out,
                repo_root=args.repo_root,
                memorywiki_root=args.memorywiki_root,
                skill_archive=args.skill_archive,
                backup_bundle=args.backup_bundle,
                backup_root=args.backup_root,
                backup_name=args.backup_name,
                release_check_json=args.release_check_json,
                previous_manifest=args.previous_manifest,
                now=args.now,
            )
            payload = {
                "manifest_path": str(path),
                "manifest": json.loads(path.read_text(encoding="utf-8")),
            }
        else:
            payload = build_manifest(
                repo_root=args.repo_root,
                memorywiki_root=args.memorywiki_root,
                skill_archive=args.skill_archive,
                backup_bundle=args.backup_bundle,
                backup_root=args.backup_root,
                backup_name=args.backup_name,
                release_check_json=args.release_check_json,
                previous_manifest=args.previous_manifest,
                now=args.now,
            )
        if args.format == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_human(payload.get("manifest", payload)), end="")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
