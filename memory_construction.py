from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from memory_system.sanitizer import neutralize_instruction_text, sanitize_text
from memory_system.store_guard import build_existing_scoped_store
from memory_system.store_io import MAX_MANAGED_READ_BYTES

REPORT_SCHEMA = "memorywiki-construction-report-v1"
TOPIC_BUNDLE_SCHEMA = "memorywiki-construction-topic-bundle-v1"
TOPIC_BUNDLE_QUEUE = "construction_topic_bundles.jsonl"
GENERATOR_VERSION = "memorywiki-construction-v1"
COMPRESSOR_VERSION = "rule-compressor-v1"
SEGMENTER_VERSION = "lexical-topic-segmenter-v1"
MAX_REPORT_ITEMS = 500
MAX_LABELS = 5

STOPWORDS = {
    "about",
    "after",
    "agent",
    "and",
    "before",
    "candidate",
    "from",
    "into",
    "memory",
    "project",
    "session",
    "should",
    "source",
    "system",
    "that",
    "the",
    "this",
    "with",
}

CRITICAL_LINE_RE = re.compile(
    r"("
    r"\d{4}-\d{2}-\d{2}|"
    r"\b(?:action|blocker|command|conflict|decision|forget|hash|pending|procedure|"
    r"source|tombstone|update|warning)\b|"
    r"(?:^|\s)(?:python3|pytest|memorywiki|mw|git|npm|uv|ruff|mypy|bandit|pip-audit)\s|"
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|"
    r"\b[a-f0-9]{16,}\b"
    r")",
    re.IGNORECASE,
)

BOILERPLATE_RE = re.compile(
    r"^(?:#\s*)?(?:memory index|core memory|user memory|stable facts|sources?:)\s*$",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _selected_roots(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str,
) -> list[tuple[str, Path]]:
    roots = []
    if scope in ("all", "global"):
        roots.append(("global", Path(global_root).expanduser()))
    if scope in ("all", "project"):
        roots.append(("project", Path(project_root).expanduser()))
    return roots


def _parse_since(value: str | None, *, now: datetime | None = None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    timestamp = now or datetime.now(timezone.utc)
    match = re.fullmatch(r"(\d+)([hdw])", text, re.IGNORECASE)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "h":
            return timestamp - timedelta(hours=amount)
        if unit == "d":
            return timestamp - timedelta(days=amount)
        return timestamp - timedelta(weeks=amount)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            parsed = datetime.fromisoformat(text + "T00:00:00+00:00")
        else:
            raise ValueError("--since must be an ISO timestamp/date or duration like 24h, 7d, 2w")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4)


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _read_managed_text_and_hash(store: Any, path: Path) -> tuple[str, str]:
    store._assert_safe_managed_path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        if path.is_symlink():
            raise ValueError(f"Managed memory files may not be symlinks: {path}")
        raise
    try:
        size = os.fstat(fd).st_size
        if size > MAX_MANAGED_READ_BYTES:
            raise ValueError(f"Managed memory file exceeds safe read limit: {path}")
        raw = os.read(fd, size)
    finally:
        os.close(fd)
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def _line_ids(text: str) -> list[str]:
    ids = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            ids.append(f"L{idx}")
    return ids[:50]


def _section_ids(text: str) -> list[str]:
    sections = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = re.sub(r"[^A-Za-z0-9_.-]+", "-", stripped.lstrip("# ").lower()).strip("-")
            if heading:
                sections.append(heading[:80])
    return sections[:20]


def _sanitize_for_construction(text: str) -> tuple[str, dict[str, Any]]:
    sanitized = sanitize_text(text or "")
    neutralized_lines = []
    instruction_like_count = 0
    for line in sanitized.splitlines():
        neutralized = neutralize_instruction_text(line)
        if neutralized != line:
            instruction_like_count += 1
        neutralized_lines.append(neutralized)
    return (
        "\n".join(neutralized_lines),
        {
            "sensitive_text_redacted": sanitized != (text or ""),
            "instruction_like_neutralized": instruction_like_count > 0,
            "instruction_like_count": instruction_like_count,
        },
    )


def _compress_for_construction(text: str) -> dict[str, Any]:
    sanitized, sanitizer_status = _sanitize_for_construction(text)
    seen = set()
    kept: list[str] = []
    skipped_duplicate = 0
    skipped_boilerplate = 0
    for line in sanitized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        normalized = re.sub(r"\s+", " ", stripped).lower()
        if normalized in seen:
            skipped_duplicate += 1
            continue
        seen.add(normalized)
        if BOILERPLATE_RE.match(stripped):
            skipped_boilerplate += 1
            continue
        if CRITICAL_LINE_RE.search(stripped) or len(kept) < 24:
            kept.append(stripped[:500])
    compressed_text = "\n".join(kept)
    raw_tokens = _estimate_tokens(sanitized)
    compressed_tokens = _estimate_tokens(compressed_text)
    return {
        "raw_token_estimate": raw_tokens,
        "compressed_token_estimate": compressed_tokens,
        "reduction_ratio": round(1 - min(compressed_tokens, raw_tokens) / max(raw_tokens, 1), 4),
        "line_count": len([line for line in sanitized.splitlines() if line.strip()]),
        "kept_line_count": len(kept),
        "skipped_duplicate_lines": skipped_duplicate,
        "skipped_boilerplate_lines": skipped_boilerplate,
        "sanitizer_status": sanitizer_status,
        "compressed_text_hash_sha256": hashlib.sha256(
            compressed_text.encode("utf-8")
        ).hexdigest(),
    }


def _topic_labels(*texts: str, fallback: str) -> list[str]:
    joined = " ".join(sanitize_text(text) for text in texts if text)
    labels: list[str] = []
    lowered = joined.lower()
    markers = [
        ("stable-decision", "stable decision" in lowered or "decision" in lowered),
        ("procedure", "procedure" in lowered or "workflow" in lowered),
        ("conflict", "conflict" in lowered),
        ("source-provenance", "source" in lowered or "provenance" in lowered),
        ("security", "security" in lowered or "prompt-injection" in lowered),
    ]
    for label, present in markers:
        if present and label not in labels:
            labels.append(label)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", joined):
        label = word.lower().strip("-_")
        if label in STOPWORDS or label in labels:
            continue
        labels.append(label[:40])
        if len(labels) >= MAX_LABELS:
            break
    if not labels:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", fallback.lower()).strip("-")
        labels.append((safe or hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:10])[:40])
    return labels[:MAX_LABELS]


def _input_row(
    *,
    scope: str,
    root: Path,
    path: Path,
    source_type: str,
    item_id: str,
    title: str,
    text: str,
    digest: str,
) -> dict[str, Any]:
    rel = _relative_path(root, path)
    artifact = _compress_for_construction(text)
    label_text = "" if source_type == "source" else text
    labels = _topic_labels(title, label_text, fallback=path.stem)
    return {
        "scope": scope,
        "canonical_source_type": source_type,
        "canonical_path": rel,
        "canonical_hash_sha256": digest,
        "source_digest_algorithm": "sha256",
        "item_id": item_id,
        "title": sanitize_text(title).strip()[:160] or item_id,
        "topic_labels": labels,
        "input_span_ids": _line_ids(text),
        "canonical_section_ids": _section_ids(text),
        "token_estimates": {
            "raw": artifact["raw_token_estimate"],
            "compressed": artifact["compressed_token_estimate"],
        },
        "construction_artifact": artifact,
        "warnings": [],
    }


def _session_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.lstrip("# ").strip()
    return fallback


def _collect_scope_inputs(
    *,
    root: Path,
    scope: str,
    limit: int,
    since_dt: datetime | None,
) -> dict[str, Any]:
    store = build_existing_scoped_store(root, scope=scope)
    if store is None:
        return {
            "scope": scope,
            "root": str(root),
            "status": "missing",
            "inputs": [],
            "skipped_input_count": 0,
            "skipped_input_reasons": [],
            "warnings": ["memory root is missing"],
        }
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    def add_path(path: Path, source_type: str, item_id: str, title: str) -> None:
        if len(rows) >= limit:
            return
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if since_dt is not None and mtime < since_dt:
                return
            text, digest = _read_managed_text_and_hash(store, path)
            rows.append(
                _input_row(
                    scope=scope,
                    root=store.paths.root,
                    path=path,
                    source_type=source_type,
                    item_id=item_id,
                    title=title,
                    text=text,
                    digest=digest,
                )
            )
        except UnicodeDecodeError:
            skipped.append(
                {
                    "path": _relative_path(store.paths.root, path),
                    "reason": "unicode_decode_error",
                }
            )
        except (OSError, ValueError) as exc:
            skipped.append(
                {
                    "path": _relative_path(store.paths.root, path),
                    "reason": sanitize_text(str(exc))[:240],
                }
            )

    for path in store._iter_safe_managed_files(store.paths.sessions_dir, "session-*.md", limit=limit):
        add_path(path, "session", path.stem, _session_title(path.stem, path.stem))
    for path in store._iter_safe_managed_files(store.paths.episodes_dir, "20??-??-??.md", limit=limit):
        add_path(path, "episode", path.stem, path.stem)
    for path in store._iter_safe_managed_files(store.paths.sources_dir, "*", limit=limit):
        if path.is_file():
            add_path(path, "source", path.name, path.name)

    rows = rows[:limit]
    status = "review" if skipped else "ok"
    return {
        "scope": scope,
        "root": str(store.paths.root),
        "status": status,
        "inputs": rows,
        "skipped_input_count": len(skipped),
        "skipped_input_reasons": skipped,
        "warnings": ["some canonical inputs were skipped"] if skipped else [],
    }


def _bundle_id(scope: str, labels: list[str], source_paths: Iterable[str]) -> str:
    basis = f"{scope}|{','.join(labels)}|{','.join(sorted(source_paths))}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
    label = labels[0] if labels else "topic"
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "topic"
    return f"construction-{safe_label[:40]}-{digest}"


def _candidate_from_group(
    *,
    scope: str,
    label: str,
    inputs: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    source_paths = [str(item["canonical_path"]) for item in inputs]
    source_hashes = [str(item["canonical_hash_sha256"]) for item in inputs]
    labels = []
    for item in inputs:
        for topic_label in item.get("topic_labels", []):
            if topic_label not in labels:
                labels.append(topic_label)
    if label not in labels:
        labels.insert(0, label)
    labels = labels[:MAX_LABELS]
    warnings = []
    if any(
        item.get("construction_artifact", {})
        .get("sanitizer_status", {})
        .get("sensitive_text_redacted")
        for item in inputs
    ):
        warnings.append("sanitized_sensitive_text")
    if any(
        item.get("construction_artifact", {})
        .get("sanitizer_status", {})
        .get("instruction_like_neutralized")
        for item in inputs
    ):
        warnings.append("instruction_like_text_neutralized")
    token_raw = sum(int(item.get("token_estimates", {}).get("raw", 0)) for item in inputs)
    token_compressed = sum(
        int(item.get("token_estimates", {}).get("compressed", 0)) for item in inputs
    )
    inclusion_reasons = {
        str(item["item_id"]): f"shares topic label {label}" for item in inputs
    }
    return {
        "event": "construction_topic_bundle",
        "schema": TOPIC_BUNDLE_SCHEMA,
        "schema_version": 1,
        "ts": generated_at,
        "generated_at": generated_at,
        "scope": scope,
        "bundle_id": _bundle_id(scope, labels, source_paths),
        "status": "candidate",
        "source_paths": source_paths,
        "source_hashes_sha256": source_hashes,
        "canonical_source_types": sorted(
            {str(item.get("canonical_source_type", "")) for item in inputs}
        ),
        "source_digest_algorithm": "sha256",
        "source_ref_digest_status": "not-applicable",
        "item_ids": [str(item["item_id"]) for item in inputs],
        "included_item_ids": [str(item["item_id"]) for item in inputs],
        "excluded_item_ids": [],
        "input_span_ids": {
            str(item["item_id"]): item.get("input_span_ids", []) for item in inputs
        },
        "canonical_section_ids": {
            str(item["item_id"]): item.get("canonical_section_ids", []) for item in inputs
        },
        "excerpt_hashes_sha256": {
            str(item["item_id"]): item.get("construction_artifact", {}).get(
                "compressed_text_hash_sha256", ""
            )
            for item in inputs
        },
        "topic_labels": labels,
        "token_estimates": {
            "raw": token_raw,
            "compressed": token_compressed,
            "reduction_ratio": round(
                1 - min(token_compressed, token_raw) / max(token_raw, 1), 4
            ),
        },
        "confidence": round(min(0.8, 0.45 + 0.08 * len(inputs)), 2),
        "warnings": warnings,
        "inclusion_reasons": inclusion_reasons,
        "exclusion_reasons": {},
        "transformation_chain": [
            "sanitize_text",
            COMPRESSOR_VERSION,
            SEGMENTER_VERSION,
        ],
        "compressor_version": COMPRESSOR_VERSION,
        "segmenter_version": SEGMENTER_VERSION,
        "generator_version": GENERATOR_VERSION,
        "sanitizer_status": {
            "any_sensitive_text_redacted": "sanitized_sensitive_text" in warnings,
            "any_instruction_neutralized": "instruction_like_text_neutralized" in warnings,
        },
    }


def _topic_candidates(inputs: list[dict[str, Any]], *, generated_at: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in inputs:
        labels = item.get("topic_labels", []) or ["topic"]
        label = str(labels[0])
        grouped.setdefault((str(item.get("scope", "")), label), []).append(item)
    candidates = [
        _candidate_from_group(scope=scope, label=label, inputs=items, generated_at=generated_at)
        for (scope, label), items in sorted(grouped.items())
        if items
    ]
    candidates.sort(key=lambda row: (-len(row["item_ids"]), row["scope"], row["bundle_id"]))
    return candidates


def _candidate_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("scope", "project")), str(row.get("bundle_id", "")))


def _read_jsonl(path: Path, *, root: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        raise ValueError(f"Construction queue must stay below memory root: {path}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Construction queue must be a real file: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        size = os.fstat(fd).st_size
        if size > MAX_MANAGED_READ_BYTES:
            raise ValueError(f"Construction queue exceeds safe read limit: {path}")
        raw = os.read(fd, size).decode("utf-8")
    finally:
        os.close(fd)
    rows = []
    for line in raw.splitlines()[-MAX_REPORT_ITEMS:]:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _assert_safe_pending_file(root: Path, filename: str) -> Path:
    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        raise ValueError(f"Invalid pending filename: {filename}")
    pending = root / "_pending"
    if pending.exists() and (pending.is_symlink() or not pending.is_dir()):
        raise ValueError(f"Pending directory must be a real directory: {pending}")
    root_resolved = root.resolve(strict=False)
    cursor = pending
    checked = []
    while cursor != cursor.parent:
        checked.append(cursor)
        if cursor == root:
            break
        cursor = cursor.parent
    for item in checked:
        if item.exists() and item.is_symlink():
            raise ValueError(f"Pending path may not include symlinks: {item}")
        try:
            item.resolve(strict=False).relative_to(root_resolved)
        except ValueError:
            raise ValueError(f"Pending path must stay below memory root: {pending}")
    return pending / filename


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError(f"Construction write target must be a real file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError(f"Construction write directory must be a real directory: {path.parent}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def validate_topic_bundle_hashes(
    *,
    root: str | Path,
    scope: str,
    candidate: dict[str, Any],
) -> list[str]:
    store = build_existing_scoped_store(root, scope=scope)
    if store is None:
        return ["memory root is missing"]
    problems: list[str] = []
    source_paths = [str(item) for item in candidate.get("source_paths", [])]
    source_hashes = [str(item) for item in candidate.get("source_hashes_sha256", [])]
    if len(source_paths) != len(source_hashes):
        return ["source path/hash count mismatch"]
    for rel, expected_hash in zip(source_paths, source_hashes):
        path = store.paths.root / rel
        try:
            _, digest = _read_managed_text_and_hash(store, path)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            problems.append(f"{rel}: {sanitize_text(str(exc))[:160]}")
            continue
        if digest != expected_hash:
            problems.append(f"{rel}: source_changed")
    return problems


def _read_topic_bundle_rows(root: Path) -> list[dict[str, Any]]:
    return _read_jsonl(root / "_pending" / TOPIC_BUNDLE_QUEUE, root=root)


def load_construction_topic_bundle_rows(root: str | Path, scope: str) -> list[dict[str, Any]]:
    root_path = Path(root).expanduser()
    rows = _read_topic_bundle_rows(root_path)
    for row in rows:
        row["scope"] = row.get("scope") or scope
        row["root"] = str(root_path)
    return rows


def write_topic_bundle_candidates(
    *,
    root: str | Path,
    scope: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    store = build_existing_scoped_store(root, scope=scope)
    if store is None:
        raise ValueError(f"write-candidates requires an existing memory root: {root}")
    path = _assert_safe_pending_file(store.paths.root, TOPIC_BUNDLE_QUEUE)
    existing = [
        row
        for row in _read_topic_bundle_rows(store.paths.root)
        if row.get("event") == "construction_topic_bundle"
    ]
    seen = {_candidate_key(row) for row in existing}
    written = []
    skipped = 0
    for candidate in candidates:
        if str(candidate.get("scope") or scope) != scope:
            skipped += 1
            continue
        problems = validate_topic_bundle_hashes(
            root=store.paths.root,
            scope=scope,
            candidate=candidate,
        )
        if problems:
            raise ValueError(
                f"construction candidate has stale source hashes: {'; '.join(problems)}"
            )
        key = _candidate_key(candidate)
        if key in seen:
            skipped += 1
            continue
        _append_jsonl(path, candidate)
        seen.add(key)
        written.append(candidate)
    return {
        "written": len(written),
        "skipped": skipped,
        "path": _relative_path(store.paths.root, path),
        "rows": written,
    }


def run_construction_report(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str = "all",
    limit: int = 20,
    since: str | None = None,
    write_candidates: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    if scope not in {"all", "project", "global"}:
        raise ValueError("--scope must be one of all, project, global")
    if limit <= 0:
        raise ValueError("--limit must be positive")
    limit = min(limit, MAX_REPORT_ITEMS)
    generated_at = now or _now()
    since_dt = _parse_since(since)
    root_reports = []
    all_inputs: list[dict[str, Any]] = []
    warnings: list[str] = []
    for selected_scope, root in _selected_roots(
        project_root=project_root,
        global_root=global_root,
        scope=scope,
    ):
        root_report = _collect_scope_inputs(
            root=root,
            scope=selected_scope,
            limit=limit,
            since_dt=since_dt,
        )
        root_reports.append(root_report)
        all_inputs.extend(root_report["inputs"])
        warnings.extend(root_report.get("warnings", []))
    candidates = _topic_candidates(all_inputs, generated_at=generated_at)[:limit]
    write_result = {"written": 0, "skipped": 0, "paths": [], "rows": []}
    if write_candidates:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            grouped.setdefault(str(candidate.get("scope") or "project"), []).append(candidate)
        rows = []
        paths = []
        skipped = 0
        written = 0
        root_by_scope = {
            "project": Path(project_root).expanduser(),
            "global": Path(global_root).expanduser(),
        }
        for candidate_scope, scope_candidates in grouped.items():
            payload = write_topic_bundle_candidates(
                root=root_by_scope[candidate_scope],
                scope=candidate_scope,
                candidates=scope_candidates,
            )
            written += int(payload["written"])
            skipped += int(payload["skipped"])
            if payload.get("path"):
                paths.append(str(payload["path"]))
            rows.extend(payload.get("rows", []))
        write_result = {
            "written": written,
            "skipped": skipped,
            "paths": sorted(set(paths)),
            "rows": rows,
        }
    skipped_count = sum(int(report["skipped_input_count"]) for report in root_reports)
    token_raw = sum(int(item["token_estimates"]["raw"]) for item in all_inputs)
    token_compressed = sum(int(item["token_estimates"]["compressed"]) for item in all_inputs)
    status = "review" if warnings or skipped_count or candidates else "ok"
    return {
        "schema": REPORT_SCHEMA,
        "status": status,
        "generated_at": generated_at,
        "read_only": not write_candidates,
        "write_candidates": write_candidates,
        "scope": scope,
        "limit": limit,
        "since": since or "",
        "roots": root_reports,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "construction_write": write_result,
        "metrics": {
            "input_count": len(all_inputs),
            "candidate_count": len(candidates),
            "skipped_input_count": skipped_count,
            "skipped_input_reasons": [
                item
                for report in root_reports
                for item in report.get("skipped_input_reasons", [])
            ],
            "raw_token_estimate": token_raw,
            "compressed_token_estimate": token_compressed,
            "raw_to_candidate_token_reduction": round(
                1 - min(token_compressed, token_raw) / max(token_raw, 1), 4
            ),
            "construction_api_calls": 0,
            "scope_boundary_errors": 0,
            "private_path_leakage": 0,
            "source_excerpt_leakage": 0,
        },
        "warnings": sorted(set(warnings)),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Construction Report",
        "",
        f"- Status: `{payload['status']}`",
        "- Read-only: `%s`" % ("yes" if payload["read_only"] else "no"),
        f"- Scope: `{payload['scope']}`",
        f"- Inputs: `{payload['metrics']['input_count']}`",
        f"- Candidates: `{payload['candidate_count']}`",
        f"- Skipped inputs: `{payload['metrics']['skipped_input_count']}`",
        f"- Token reduction estimate: `{payload['metrics']['raw_to_candidate_token_reduction']}`",
        "",
    ]
    if payload.get("warnings"):
        lines.append("## Warnings")
        for warning in payload["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")
    lines.append("## Candidate Topic Bundles")
    if not payload["candidates"]:
        lines.append("- No candidates.")
    for candidate in payload["candidates"][:20]:
        lines.append(
            "- `{bundle}` scope={scope} labels={labels} inputs={count} warnings={warnings}".format(
                bundle=candidate["bundle_id"],
                scope=candidate["scope"],
                labels=",".join(candidate["topic_labels"]),
                count=len(candidate["item_ids"]),
                warnings=",".join(candidate["warnings"]) or "none",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a read-only MemoryWiki memory-construction report."
    )
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--scope", choices=("all", "project", "global"), default="all")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--since", default=None)
    parser.add_argument(
        "--write-candidates",
        action="store_true",
        help="Explicit write opt-in: append topic bundle candidates to _pending.",
    )
    parser.add_argument("--now", default=None)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_construction_report(
            project_root=args.project_root,
            global_root=args.global_root,
            scope=args.scope,
            limit=args.limit,
            since=args.since,
            write_candidates=args.write_candidates,
            now=args.now,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(payload), end="")
    return 0 if payload["status"] in {"ok", "review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
