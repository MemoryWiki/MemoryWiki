from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Iterable

from memory_system.models import SourceRef
from memory_system.paths import MemoryScopePaths
from memory_system.store import MAX_MANAGED_FILES, MAX_MANAGED_READ_BYTES, ScopedMemoryStore


INDEX_SCHEMA_VERSION = 2
LOCAL_EMBEDDING_MODEL = "memorywiki-local-hash-v1"
LOCAL_EMBEDDING_DIMENSIONS = 256
MAX_INDEX_ROWS = MAX_MANAGED_FILES * 2
TOKEN_RE = re.compile(
    r"[A-Za-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+"
)


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
        "\u3400" <= char <= "\u4dbf"
        or "\u4e00" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
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
    return dict(Counter(tokenize_for_index(text)))


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
        str(bucket): round(value / norm, 6)
        for bucket, value in sorted(buckets.items())
        if value
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
    return [
        str(entry)
        for entry in update_log
        if "conflict:" in str(entry).lower()
    ]


def _safe_root(root: Path) -> Path:
    root = root.expanduser()
    if not root.exists():
        raise ValueError("Memory root does not exist: %s" % root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Memory root must be a real directory: %s" % root)
    for ancestor in [root] + list(root.parents):
        if ancestor.exists() and ancestor.is_symlink():
            raise ValueError("Memory root may not be below a symlink: %s" % ancestor)
    return root


def _assert_safe_child(root: Path, path: Path) -> None:
    root = _safe_root(root)
    try:
        path.parent.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        raise ValueError("Retrieval index path must stay within memory root: %s" % path)
    cursor = root
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ValueError("Retrieval index path must stay within memory root: %s" % path)
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise ValueError("Retrieval index path may not cross a symlink: %s" % cursor)
    if path.exists() and path.is_symlink():
        raise ValueError("Retrieval index path may not be a symlink: %s" % path)


def _safe_relative_path(root: Path, relative_text: str) -> Path:
    relative = Path(str(relative_text or ""))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Invalid indexed source path: %s" % relative_text)
    path = root / relative
    _assert_safe_child(root, path)
    return path


def _read_file_bytes(root: Path, path: Path) -> bytes:
    _assert_safe_child(root, path)
    if not path.exists() or not path.is_file():
        raise ValueError("Indexed source file is missing: %s" % path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        stat = os.fstat(fd)
        if stat.st_size > MAX_MANAGED_READ_BYTES:
            raise ValueError("Indexed source file exceeds safe read limit: %s" % path)
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
    return [asdict(ref) for ref in source_refs]


def _weighted_text(title: str, text: str, concepts: Iterable[str]) -> str:
    return " ".join([title, text, " ".join(str(concept) for concept in concepts)])


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
        "indexed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **metadata,
    }


def build_index_rows(store: ScopedMemoryStore, scope: str) -> list[dict]:
    rows = []
    for item in store.list_semantic_memories(limit=MAX_MANAGED_FILES):
        source_refs = item.source_refs + [
            SourceRef("memory-file", "semantic/%s.md" % item.id, item.id)
        ]
        rows.append(
            _index_row(
                store,
                scope,
                "semantic",
                item.id,
                item.title,
                item.content,
                list(item.concepts),
                item.confidence,
                item.strength,
                source_refs,
                store.paths.semantic_file(item.id),
                update_log=list(item.update_log),
            )
        )

    for item in store.list_procedural_memories(limit=MAX_MANAGED_FILES):
        text = "\n".join([item.trigger] + item.steps)
        source_refs = item.source_refs + [
            SourceRef("memory-file", "procedures/%s.md" % item.id, item.id)
        ]
        rows.append(
            _index_row(
                store,
                scope,
                "procedure",
                item.id,
                item.title,
                text,
                [],
                item.confidence,
                item.strength,
                source_refs,
                store.paths.procedure_file(item.id),
            )
        )

    for session_meta in store.list_sessions(limit=MAX_MANAGED_FILES):
        session = store.read_session(session_meta.id)
        if session is None:
            continue
        text = "\n".join(
            [session.title, session.body]
            + session.keypoints
            + session.actions
            + session.pending
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
                [SourceRef("session", "sessions/%s.md" % session.id, session.id)],
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
                [SourceRef("episode", "episodes/%s.md" % date_text, date_text)],
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
        raise ValueError("Retrieval index directory must be a real directory: %s" % index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / "index.jsonl"
    _assert_safe_child(root, index_path)
    tmp_path = index_dir / ("index.%s.tmp" % os.getpid())
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


def _validate_derived_row_fields(row: dict, line_number: int) -> list[str]:
    warnings = []
    title = str(row.get("title", ""))
    text = str(row.get("text", ""))
    concepts = [str(item) for item in (row.get("concepts") or [])]
    weighted_text = _weighted_text(title, text, concepts)
    expected_counts = term_counts_for_index(weighted_text)
    if _coerce_term_counts(row.get("term_counts") or {}) != expected_counts:
        warnings.append("Stale retrieval index row %s: derived term counts changed" % line_number)
    expected_vector = local_embedding_for_index(weighted_text)
    if (
        row.get("embedding_model") != LOCAL_EMBEDDING_MODEL
        or row.get("embedding_dimensions") != LOCAL_EMBEDDING_DIMENSIONS
        or _coerce_embedding_vector(row.get("embedding_vector") or {}) != expected_vector
    ):
        warnings.append("Stale retrieval index row %s: embedding vector changed" % line_number)
    expected_conflicts = conflict_update_entries(_row_update_log(row))
    if bool(row.get("conflict_history")) != bool(expected_conflicts):
        warnings.append("Stale retrieval index row %s: conflict flag changed" % line_number)
    indexed_conflicts = [str(entry) for entry in (row.get("conflict_entries") or [])]
    if indexed_conflicts != expected_conflicts:
        warnings.append("Stale retrieval index row %s: conflict entries changed" % line_number)
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
            "Stale retrieval index row %s: canonical source is missing or changed"
            % line_number
        ]
    for field in CANONICAL_ROW_FIELDS:
        if row.get(field) != canonical.get(field):
            return [
                "Stale retrieval index row %s for %s: canonical content changed"
                % (line_number, row.get("source_path", ""))
            ]
    return []


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
            warnings=["Missing retrieval index for %s memory: %s" % (scope, index_path)],
            fresh=False,
        )
    try:
        raw = _read_file_bytes(root, index_path)
    except (OSError, ValueError) as exc:
        return IndexLoadResult(
            rows=[],
            warnings=["Unreadable retrieval index for %s memory: %s" % (scope, exc)],
            fresh=False,
        )
    rows = []
    fresh = True
    canonical_rows: dict[tuple[str, str, str], dict] | None = None
    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if line_number > MAX_INDEX_ROWS:
            warnings.append("Retrieval index row limit exceeded: %s" % index_path)
            fresh = False
            break
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            warnings.append("Malformed retrieval index row %s: %s" % (line_number, index_path))
            fresh = False
            continue
        if row.get("schema_version") != INDEX_SCHEMA_VERSION:
            warnings.append("Unsupported retrieval index row schema at row %s" % line_number)
            fresh = False
            continue
        if row.get("scope") != scope:
            continue
        text = str(row.get("text", ""))
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if row.get("text_sha256") != text_hash:
            warnings.append(
                "Stale retrieval index row %s for %s: text hash changed"
                % (line_number, row.get("source_path", ""))
            )
            fresh = False
            continue
        try:
            source_path = _safe_relative_path(root, str(row.get("source_path", "")))
            metadata = _source_metadata(root, source_path)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            warnings.append("Stale retrieval index row %s: %s" % (line_number, exc))
            fresh = False
            continue
        for field in ("sha256", "size", "mtime_ns"):
            if row.get(field) != metadata[field]:
                warnings.append(
                    "Stale retrieval index row %s for %s: %s changed"
                    % (line_number, row.get("source_path", ""), field)
                )
                fresh = False
                break
        else:
            derived_warnings = _validate_derived_row_fields(row, line_number)
            if derived_warnings:
                warnings.extend(derived_warnings)
                fresh = False
                continue
            if canonical_rows is None:
                try:
                    canonical_rows = _canonical_rows_by_key(root, scope)
                except (OSError, UnicodeDecodeError, ValueError) as exc:
                    warnings.append("Unable to validate retrieval index against canonical memory: %s" % exc)
                    fresh = False
                    continue
            canonical_warnings = _validate_against_canonical_row(
                row,
                canonical_rows,
                line_number,
            )
            if canonical_warnings:
                warnings.extend(canonical_warnings)
                fresh = False
                continue
            rows.append(row)
    return IndexLoadResult(rows=rows, warnings=warnings, fresh=fresh)
