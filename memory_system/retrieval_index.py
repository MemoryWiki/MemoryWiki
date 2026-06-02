from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from memory_system.models import SourceRef
from memory_system.paths import MemoryScopePaths
from memory_system.sanitizer import neutralize_instruction_text, sanitize_text
from memory_system.store import MAX_MANAGED_FILES, MAX_MANAGED_READ_BYTES, ScopedMemoryStore

INDEX_SCHEMA_VERSION = 3
SUPPORTED_INDEX_SCHEMA_VERSIONS = {2, 3}
RETRIEVAL_VIEW_VERSION = 1
RETRIEVAL_VIEW_GENERATION_VERSION = "memorywiki-retrieval-views-v1"
LOCAL_EMBEDDING_MODEL = "memorywiki-local-hash-v1"
LOCAL_EMBEDDING_DIMENSIONS = 256
MAX_INDEX_ROWS = MAX_MANAGED_FILES * 2
MAX_INDEX_TERM_COUNTS = 128
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")


@dataclass
class IndexLoadResult:
    rows: list[dict]
    warnings: list[str]
    fresh: bool


def tokenize_for_index(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_RE.finditer(text or ""):
        segment = match.group(0).lower()
        if not segment:
            continue
        if _is_cjk_segment(segment):
            tokens.extend(_cjk_ngrams(segment))
        else:
            tokens.append(segment)
    return tokens


def _is_cjk_segment(value: str) -> bool:
    return all(
        "\u3400" <= char <= "\u4dbf" or "\u4e00" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"
        for char in value
    )


def _cjk_ngrams(value: str) -> list[str]:
    if len(value) <= 1:
        return [value]
    tokens: list[str] = []
    for size in (2, 3, 4):
        if len(value) < size:
            continue
        tokens.extend(value[index : index + size] for index in range(len(value) - size + 1))
    if len(value) <= 12:
        tokens.append(value)
    return tokens


def term_counts_for_index(text: str) -> dict[str, int]:
    counts = Counter(tokenize_for_index(text))
    if len(counts) <= MAX_INDEX_TERM_COUNTS:
        return dict(counts)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return dict(ranked[:MAX_INDEX_TERM_COUNTS])


def local_embedding_for_index(
    text: str,
    dimensions: int = LOCAL_EMBEDDING_DIMENSIONS,
) -> dict[str, float]:
    counts = Counter(tokenize_for_index(text))
    if not counts:
        return {}
    buckets: dict[int, float] = {}
    for token, count in counts.items():
        digest = hashlib.sha256(("memorywiki-local-hash-v1:" + token).encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % dimensions
        sign = 1.0 if digest[8] % 2 == 0 else -1.0
        buckets[bucket] = buckets.get(bucket, 0.0) + sign * (1.0 + math.log(count))
    norm = sum(value * value for value in buckets.values()) ** 0.5
    if not norm:
        return {}
    return {
        str(bucket): round(value / norm, 6) for bucket, value in sorted(buckets.items()) if value
    }


def sparse_vector_cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    dot = 0.0
    for bucket, value in left.items():
        try:
            dot += float(value) * float(right.get(bucket, 0.0))
        except (TypeError, ValueError):
            continue
    return dot


def has_conflict_update(update_log: Iterable[str]) -> bool:
    return any("conflict:" in str(entry).lower() for entry in update_log)


def conflict_update_entries(update_log: Iterable[str]) -> list[str]:
    return [str(entry) for entry in update_log if "conflict:" in str(entry).lower()]


def _safe_root(root: Path) -> Path:
    root = root.expanduser()
    if not root.exists():
        raise ValueError(f"Memory root does not exist: {root}")
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Memory root must be a real directory: {root}")
    for ancestor in [root] + list(root.parents):
        if ancestor.exists() and ancestor.is_symlink():
            raise ValueError(f"Memory root may not be below a symlink: {ancestor}")
    return root


def _assert_safe_child(root: Path, path: Path) -> None:
    root = _safe_root(root)
    try:
        path.parent.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        raise ValueError(f"Retrieval index path must stay within memory root: {path}")
    cursor = root
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ValueError(f"Retrieval index path must stay within memory root: {path}")
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise ValueError(f"Retrieval index path may not cross a symlink: {cursor}")
    if path.exists() and path.is_symlink():
        raise ValueError(f"Retrieval index path may not be a symlink: {path}")


def _safe_relative_path(root: Path, relative_text: str) -> Path:
    relative = Path(str(relative_text or ""))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"Invalid indexed source path: {relative_text}")
    path = root / relative
    _assert_safe_child(root, path)
    return path


def _read_file_bytes(root: Path, path: Path) -> bytes:
    _assert_safe_child(root, path)
    if not path.exists() or not path.is_file():
        raise ValueError(f"Indexed source file is missing: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        stat = os.fstat(fd)
        if stat.st_size > MAX_MANAGED_READ_BYTES:
            raise ValueError(f"Indexed source file exceeds safe read limit: {path}")
        return os.read(fd, stat.st_size)
    finally:
        os.close(fd)


def _source_metadata(root: Path, path: Path) -> dict:
    raw = _read_file_bytes(root, path)
    stat = path.stat()
    return {
        "source_path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _source_refs_to_dicts(source_refs: Iterable[SourceRef]) -> list[dict]:
    refs = []
    for ref in source_refs:
        payload = asdict(ref)
        payload["path"] = _portable_path_text(payload.get("path"))
        if payload.get("excerpt") is not None:
            payload["excerpt"] = neutralize_instruction_text(sanitize_text(str(payload["excerpt"])))
        refs.append(payload)
    return refs


def _weighted_text(title: str, text: str, concepts: Iterable[str]) -> str:
    return " ".join([title, text, " ".join(str(concept) for concept in concepts)])


def estimate_index_tokens(text: str) -> int:
    return max(1, math.ceil(len(text or "") / 4))


def canonical_row_key(scope: str, source: str, identifier: str, source_path: str) -> str:
    return "|".join([str(scope), str(source), str(identifier), str(source_path)])


def _portable_path_text(path: str | None) -> str:
    path_text = str(path or "").strip()
    if not path_text:
        return ""
    candidate = Path(path_text)
    if candidate.is_absolute():
        return candidate.name
    safe_parts = [part for part in candidate.parts if part not in ("", ".", "..")]
    return Path(*safe_parts).as_posix() if safe_parts else ""


def _source_ref_value(ref: SourceRef | dict, field: str) -> str:
    if isinstance(ref, SourceRef):
        return str(getattr(ref, field) or "")
    if isinstance(ref, dict):
        return str(ref.get(field) or "")
    return ""


def _source_provenance_text(
    source_refs: Iterable[SourceRef | dict],
    update_log: Iterable[str],
) -> str:
    parts = []
    for ref in source_refs:
        kind = _source_ref_value(ref, "kind")
        path = _portable_path_text(_source_ref_value(ref, "path"))
        identifier = _source_ref_value(ref, "identifier")
        ref_parts = [item for item in (kind, path, identifier) if item]
        if ref_parts:
            parts.append(" ".join(ref_parts))
    for entry in update_log:
        lowered = str(entry).lower()
        if "conflict:" in lowered:
            parts.append("conflict update-log")
        elif "update:" in lowered:
            parts.append("update-log")
    return "\n".join(parts)


def _summary_keypoints_text(title: str, text: str, update_log: Iterable[str]) -> str:
    lines = [title]
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("-", "*", "#")) or len(stripped) <= 120:
            lines.append(stripped)
        if len(lines) >= 12:
            break
    for entry in update_log:
        entry_text = str(entry).strip()
        if entry_text:
            lines.append(entry_text[:160])
        if len(lines) >= 18:
            break
    return "\n".join(lines)


def build_retrieval_views(
    *,
    scope: str,
    source: str,
    identifier: str,
    source_path: str,
    title: str,
    text: str,
    concepts: Iterable[str],
    source_refs: Iterable[SourceRef | dict],
    update_log: Iterable[str],
    indexed_at: str,
) -> list[dict]:
    """Build deterministic derived retrieval views from one canonical memory row."""

    safe_concepts = [str(concept) for concept in concepts]
    safe_update_log = [str(entry) for entry in update_log if str(entry).strip()]
    canonical_text_hash = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()
    row_key = canonical_row_key(scope, source, identifier, source_path)
    view_specs = [
        ("title_concepts", " ".join([title, identifier, " ".join(safe_concepts)])),
        ("body", text),
        ("summary_keypoints", _summary_keypoints_text(title, text, safe_update_log)),
        (
            "procedure_trigger_steps",
            "\n".join([title, text]) if source == "procedure" else "",
        ),
        ("source_provenance", _source_provenance_text(source_refs, safe_update_log)),
    ]
    views = []
    for view_name, view_text in view_specs:
        view_text = neutralize_instruction_text(sanitize_text(str(view_text or ""))).strip()
        if not view_text:
            continue
        views.append(
            {
                "schema_version": INDEX_SCHEMA_VERSION,
                "view_name": view_name,
                "view_version": RETRIEVAL_VIEW_VERSION,
                "canonical_row_key": row_key,
                "canonical_path": _portable_path_text(source_path),
                "canonical_text_sha256": canonical_text_hash,
                "canonical_section": view_name,
                "generation_version": RETRIEVAL_VIEW_GENERATION_VERSION,
                "generated_at": indexed_at,
                "text": view_text,
                "text_sha256": hashlib.sha256(view_text.encode("utf-8")).hexdigest(),
                "term_counts": term_counts_for_index(view_text),
                "embedding_model": LOCAL_EMBEDDING_MODEL,
                "embedding_dimensions": LOCAL_EMBEDDING_DIMENSIONS,
                "embedding_vector": local_embedding_for_index(view_text),
                "token_estimate": estimate_index_tokens(view_text),
                "freshness": {
                    "canonical_text_sha256": canonical_text_hash,
                    "canonical_path": _portable_path_text(source_path),
                    "generation_version": RETRIEVAL_VIEW_GENERATION_VERSION,
                },
            }
        )
    return views


def _index_row(
    store: ScopedMemoryStore,
    scope: str,
    source: str,
    identifier: str,
    title: str,
    text: str,
    concepts: list[str],
    confidence: float,
    strength: float,
    source_refs: list[SourceRef],
    source_path: Path,
    update_log: list[str] | None = None,
) -> dict:
    root = store.paths.root
    metadata = _source_metadata(root, source_path)
    weighted_text = _weighted_text(title, text, concepts)
    safe_update_log = [str(entry).strip() for entry in (update_log or []) if str(entry).strip()]
    conflict_entries = conflict_update_entries(safe_update_log)
    indexed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "scope": scope,
        "source": source,
        "identifier": identifier,
        "title": title,
        "text": text,
        "concepts": concepts,
        "confidence": confidence,
        "strength": strength,
        "provenance": _source_refs_to_dicts(source_refs),
        "term_counts": term_counts_for_index(weighted_text),
        "embedding_model": LOCAL_EMBEDDING_MODEL,
        "embedding_dimensions": LOCAL_EMBEDDING_DIMENSIONS,
        "embedding_vector": local_embedding_for_index(weighted_text),
        "update_log": safe_update_log,
        "conflict_history": bool(conflict_entries),
        "conflict_entries": conflict_entries,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "indexed_at": indexed_at,
        "views": build_retrieval_views(
            scope=scope,
            source=source,
            identifier=identifier,
            source_path=metadata["source_path"],
            title=title,
            text=text,
            concepts=concepts,
            source_refs=source_refs,
            update_log=safe_update_log,
            indexed_at=indexed_at,
        ),
        **metadata,
    }


def build_index_rows(store: ScopedMemoryStore, scope: str) -> list[dict]:
    rows = []
    for semantic_item in store.list_semantic_memories(limit=MAX_MANAGED_FILES):
        source_refs = semantic_item.source_refs + [
            SourceRef("memory-file", f"semantic/{semantic_item.id}.md", semantic_item.id)
        ]
        rows.append(
            _index_row(
                store,
                scope,
                "semantic",
                semantic_item.id,
                semantic_item.title,
                semantic_item.content,
                list(semantic_item.concepts),
                semantic_item.confidence,
                semantic_item.strength,
                source_refs,
                store.paths.semantic_file(semantic_item.id),
                update_log=list(semantic_item.update_log),
            )
        )

    for procedural_item in store.list_procedural_memories(limit=MAX_MANAGED_FILES):
        text = "\n".join([procedural_item.trigger] + procedural_item.steps)
        source_refs = procedural_item.source_refs + [
            SourceRef("memory-file", f"procedures/{procedural_item.id}.md", procedural_item.id)
        ]
        rows.append(
            _index_row(
                store,
                scope,
                "procedure",
                procedural_item.id,
                procedural_item.title,
                text,
                [],
                procedural_item.confidence,
                procedural_item.strength,
                source_refs,
                store.paths.procedure_file(procedural_item.id),
            )
        )

    for session_meta in store.list_sessions(limit=MAX_MANAGED_FILES):
        session = store.read_session(session_meta.id)
        if session is None:
            continue
        text = "\n".join(
            [session.title, session.body] + session.keypoints + session.actions + session.pending
        )
        rows.append(
            _index_row(
                store,
                scope,
                "session",
                session.id,
                session.title,
                text,
                [],
                0.0,
                0.0,
                [SourceRef("session", f"sessions/{session.id}.md", session.id)],
                store.paths.session_file(session.id),
            )
        )

    for date_text in store.list_episodes():
        episode = store.read_episode(date_text)
        if episode is None:
            continue
        rows.append(
            _index_row(
                store,
                scope,
                "episode",
                date_text,
                date_text,
                episode.body,
                [],
                0.0,
                0.0,
                [SourceRef("episode", f"episodes/{date_text}.md", date_text)],
                store.paths.episode_for_date(date_text),
            )
        )

    for label, path in (
        ("index", store.paths.index),
        ("memory", store.paths.core_memory),
        ("user", store.paths.user_memory),
        ("project_profile", store.paths.project_profile),
    ):
        if not store._is_safe_readable_file(path):
            continue
        text = store._read_text_bounded(path)
        rows.append(
            _index_row(
                store,
                scope,
                label,
                label,
                label.upper(),
                text,
                [],
                0.0,
                0.0,
                [SourceRef("hot-file", path.name, label)],
                path,
            )
        )
    return rows


def write_index(root: Path, rows: list[dict]) -> Path:
    root = _safe_root(root)
    index_dir = root / "retrieval"
    if index_dir.exists() and (index_dir.is_symlink() or not index_dir.is_dir()):
        raise ValueError(f"Retrieval index directory must be a real directory: {index_dir}")
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / "index.jsonl"
    _assert_safe_child(root, index_path)
    tmp_path = index_dir / (f"index.{os.getpid()}.tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(tmp_path, flags, 0o600)
    try:
        payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp_path, index_path)
    if os.name != "nt":
        os.chmod(index_path, 0o600)
    return index_path


def _coerce_term_counts(value: dict) -> dict[str, int]:
    counts = {}
    for token, count in (value or {}).items():
        try:
            counts[str(token)] = int(count)
        except (TypeError, ValueError):
            continue
    return counts


def _coerce_embedding_vector(value: dict) -> dict[str, float]:
    vector = {}
    for bucket, weight in (value or {}).items():
        try:
            vector[str(bucket)] = float(weight)
        except (TypeError, ValueError):
            continue
    return vector


def _row_update_log(row: dict) -> list[str]:
    return [str(entry) for entry in (row.get("update_log") or [])]


def _validate_embedded_views(row: dict, line_number: int) -> list[str]:
    warnings = []
    views = row.get("views")
    if not isinstance(views, list) or not views:
        return [f"Stale retrieval index row {line_number}: embedded retrieval views missing"]
    expected_views = {
        view["view_name"]: view
        for view in build_retrieval_views(
            scope=str(row.get("scope", "")),
            source=str(row.get("source", "")),
            identifier=str(row.get("identifier", "")),
            source_path=str(row.get("source_path", "")),
            title=str(row.get("title", "")),
            text=str(row.get("text", "")),
            concepts=[str(item) for item in (row.get("concepts") or [])],
            source_refs=row.get("provenance") or [],
            update_log=_row_update_log(row),
            indexed_at=str(row.get("indexed_at", "")),
        )
    }
    seen = set()
    for view in views:
        if not isinstance(view, dict):
            warnings.append(f"Stale retrieval index row {line_number}: malformed embedded view")
            continue
        view_name = str(view.get("view_name", ""))
        expected = expected_views.get(view_name)
        if expected is None:
            warnings.append(
                f"Stale retrieval index row {line_number}: unexpected embedded view {view_name}"
            )
            continue
        seen.add(view_name)
        for field in (
            "schema_version",
            "view_version",
            "canonical_row_key",
            "canonical_path",
            "canonical_text_sha256",
            "canonical_section",
            "generation_version",
            "generated_at",
            "text",
            "text_sha256",
            "term_counts",
            "embedding_model",
            "embedding_dimensions",
            "embedding_vector",
            "token_estimate",
            "freshness",
        ):
            if view.get(field) != expected.get(field):
                warnings.append(
                    f"Stale retrieval index row {line_number}: embedded view {view_name} field {field} changed"
                )
                break
    missing_views = sorted(set(expected_views) - seen)
    if missing_views:
        warnings.append(
            "Stale retrieval index row {}: embedded views missing: {}".format(line_number, ", ".join(missing_views))
        )
    return warnings


def _validate_derived_row_fields(row: dict, line_number: int) -> list[str]:
    warnings = []
    title = str(row.get("title", ""))
    text = str(row.get("text", ""))
    concepts = [str(item) for item in (row.get("concepts") or [])]
    weighted_text = _weighted_text(title, text, concepts)
    expected_counts = term_counts_for_index(weighted_text)
    if _coerce_term_counts(row.get("term_counts") or {}) != expected_counts:
        warnings.append(f"Stale retrieval index row {line_number}: derived term counts changed")
    expected_vector = local_embedding_for_index(weighted_text)
    if (
        row.get("embedding_model") != LOCAL_EMBEDDING_MODEL
        or row.get("embedding_dimensions") != LOCAL_EMBEDDING_DIMENSIONS
        or _coerce_embedding_vector(row.get("embedding_vector") or {}) != expected_vector
    ):
        warnings.append(f"Stale retrieval index row {line_number}: embedding vector changed")
    expected_conflicts = conflict_update_entries(_row_update_log(row))
    if bool(row.get("conflict_history")) != bool(expected_conflicts):
        warnings.append(f"Stale retrieval index row {line_number}: conflict flag changed")
    indexed_conflicts = [str(entry) for entry in (row.get("conflict_entries") or [])]
    if indexed_conflicts != expected_conflicts:
        warnings.append(f"Stale retrieval index row {line_number}: conflict entries changed")
    if int(row.get("schema_version") or 0) >= 3:
        warnings.extend(_validate_embedded_views(row, line_number))
    return warnings


CANONICAL_ROW_FIELDS = (
    "scope",
    "source",
    "identifier",
    "title",
    "text",
    "concepts",
    "confidence",
    "strength",
    "provenance",
    "term_counts",
    "embedding_model",
    "embedding_dimensions",
    "embedding_vector",
    "update_log",
    "conflict_history",
    "conflict_entries",
    "text_sha256",
    "source_path",
    "sha256",
    "size",
    "mtime_ns",
)


def _row_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("source", "")),
        str(row.get("identifier", "")),
        str(row.get("source_path", "")),
    )


def _canonical_rows_by_key(root: Path, scope: str) -> dict[tuple[str, str, str], dict]:
    store = ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=False,
    )
    return {_row_key(row): row for row in build_index_rows(store, scope)}


def _validate_against_canonical_row(
    row: dict,
    canonical_rows: dict[tuple[str, str, str], dict],
    line_number: int,
) -> list[str]:
    canonical = canonical_rows.get(_row_key(row))
    if canonical is None:
        return [
            f"Stale retrieval index row {line_number}: canonical source is missing or changed"
        ]
    for field in CANONICAL_ROW_FIELDS:
        if row.get(field) != canonical.get(field):
            return [
                "Stale retrieval index row {} for {}: canonical content changed".format(line_number, row.get("source_path", ""))
            ]
    return []


def _validate_source_ref_integrity(root: Path, row: dict, line_number: int) -> list[str]:
    warnings = []
    for ref in row.get("provenance") or []:
        if not isinstance(ref, dict):
            continue
        if str(ref.get("kind", "")) != "source":
            continue
        path_text = str(ref.get("path", ""))
        identifier = str(ref.get("identifier", "") or "")
        if not path_text.startswith("sources/") or not identifier:
            continue
        if len(identifier) < 8 or not re.fullmatch(r"[a-fA-F0-9]{8,64}", identifier):
            continue
        try:
            source_path = _safe_relative_path(root, path_text)
            digest = hashlib.sha256(_read_file_bytes(root, source_path)).hexdigest()
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            warnings.append(f"Stale retrieval index row {line_number}: source ref changed: {exc}")
            continue
        if not digest.startswith(identifier):
            warnings.append(
                f"Stale retrieval index row {line_number} for {path_text}: source ref digest changed"
            )
    return warnings


def build_and_write_index(store: ScopedMemoryStore, scope: str) -> dict:
    rows = build_index_rows(store, scope)
    index_path = write_index(store.paths.root, rows)
    return {
        "root": str(store.paths.root),
        "scope": scope,
        "index_path": str(index_path),
        "schema_version": INDEX_SCHEMA_VERSION,
        "indexed": len(rows),
    }


def load_index(root: Path, scope: str) -> IndexLoadResult:
    root = root.expanduser()
    warnings = []
    try:
        root = _safe_root(root)
    except ValueError as exc:
        return IndexLoadResult(rows=[], warnings=[str(exc)], fresh=False)
    index_path = root / "retrieval" / "index.jsonl"
    try:
        _assert_safe_child(root, index_path)
    except ValueError as exc:
        return IndexLoadResult(rows=[], warnings=[str(exc)], fresh=False)
    if not index_path.exists():
        return IndexLoadResult(
            rows=[],
            warnings=[f"Missing retrieval index for {scope} memory: {index_path}"],
            fresh=False,
        )
    try:
        raw = _read_file_bytes(root, index_path)
    except (OSError, ValueError) as exc:
        return IndexLoadResult(
            rows=[],
            warnings=[f"Unreadable retrieval index for {scope} memory: {exc}"],
            fresh=False,
        )
    rows = []
    seen_keys: set[tuple[str, str, str]] = set()
    fresh = True
    canonical_rows: dict[tuple[str, str, str], dict] | None = None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return IndexLoadResult(
            rows=[],
            warnings=[
                f"Unreadable retrieval index for {scope} memory: non-UTF-8 data: {exc}"
            ],
            fresh=False,
        )
    schema_versions_seen: set[int] = set()
    scoped_rows: list[tuple[int, dict]] = []
    for line_number, line in enumerate(decoded.splitlines(), start=1):
        if line_number > MAX_INDEX_ROWS:
            warnings.append(f"Retrieval index row limit exceeded: {index_path}")
            fresh = False
            break
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"Malformed retrieval index row {line_number}: {index_path}")
            fresh = False
            continue
        try:
            schema_version = int(row.get("schema_version"))
        except (TypeError, ValueError):
            schema_version = 0
        if schema_version not in SUPPORTED_INDEX_SCHEMA_VERSIONS:
            warnings.append(f"Unsupported retrieval index row schema at row {line_number}")
            fresh = False
            continue
        if row.get("scope") != scope:
            continue
        schema_versions_seen.add(schema_version)
        scoped_rows.append((line_number, row))

    if len(schema_versions_seen) > 1:
        return IndexLoadResult(
            rows=[],
            warnings=[
                f"Stale retrieval index for {scope} memory: mixed schema versions {sorted(schema_versions_seen)}"
            ],
            fresh=False,
        )

    for line_number, row in scoped_rows:
        text = str(row.get("text", ""))
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if row.get("text_sha256") != text_hash:
            warnings.append(
                "Stale retrieval index row {} for {}: text hash changed".format(line_number, row.get("source_path", ""))
            )
            fresh = False
            continue
        try:
            source_path = _safe_relative_path(root, str(row.get("source_path", "")))
            metadata = _source_metadata(root, source_path)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            warnings.append(f"Stale retrieval index row {line_number}: {exc}")
            fresh = False
            continue
        for field in ("sha256", "size", "mtime_ns"):
            if row.get(field) != metadata[field]:
                warnings.append(
                    "Stale retrieval index row {} for {}: {} changed".format(line_number, row.get("source_path", ""), field)
                )
                fresh = False
                break
        else:
            if canonical_rows is None:
                try:
                    canonical_rows = _canonical_rows_by_key(root, scope)
                except (OSError, UnicodeDecodeError, ValueError) as exc:
                    warnings.append(
                        f"Unable to validate retrieval index against canonical memory: {exc}"
                    )
                    fresh = False
                    continue
            canonical_warnings = _validate_against_canonical_row(
                row,
                canonical_rows,
                line_number,
            )
            derived_warnings = _validate_derived_row_fields(row, line_number)
            source_ref_warnings = _validate_source_ref_integrity(root, row, line_number)
            row_warnings = canonical_warnings + derived_warnings + source_ref_warnings
            if row_warnings:
                warnings.extend(row_warnings)
                fresh = False
                continue
            seen_keys.add(_row_key(row))
            rows.append(row)
    if canonical_rows is None:
        try:
            canonical_rows = _canonical_rows_by_key(root, scope)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            warnings.append(f"Unable to validate retrieval index against canonical memory: {exc}")
            fresh = False
            canonical_rows = {}
    missing_keys = sorted(set(canonical_rows) - seen_keys)
    if missing_keys:
        fresh = False
        for key in missing_keys[:20]:
            warnings.append(
                f"Stale retrieval index is missing canonical row: {key[0]}/{key[1]}"
            )
        if len(missing_keys) > 20:
            warnings.append(
                "Stale retrieval index is missing %s additional canonical rows"
                % (len(missing_keys) - 20)
            )
    return IndexLoadResult(rows=rows, warnings=warnings, fresh=fresh)
