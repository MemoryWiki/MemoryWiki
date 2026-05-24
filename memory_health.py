from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from memory_system.models import ProceduralMemory, SemanticMemory, SourceRef
from memory_system.paths import MemoryScopePaths
from memory_system.store import ScopedMemoryStore


DEFAULT_HOT_FILE_MAX_BYTES = 250_000
DEFAULT_LOW_CONFIDENCE = 0.4
DEFAULT_STALE_DAYS = 365
MIN_HASH_PREFIX = 6


@dataclass
class HealthIssue:
    scope: str
    code: str
    severity: str
    target: str
    message: str


def _safe_store(root: str | Path, scope: str) -> ScopedMemoryStore | None:
    path = Path(root).expanduser()
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Memory root must be a real directory: %s" % path)
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(path, scope),
        sanitize_on_write=True,
        secure_permissions=True,
    )


def _issue(scope: str, code: str, severity: str, target: str, message: str) -> HealthIssue:
    return HealthIssue(
        scope=scope,
        code=code,
        severity=severity,
        target=target,
        message=message,
    )


def _item_refs(item: SemanticMemory | ProceduralMemory) -> list[SourceRef]:
    return list(getattr(item, "source_refs", []) or [])


def _item_kind(item: SemanticMemory | ProceduralMemory) -> str:
    return "semantic" if isinstance(item, SemanticMemory) else "procedures"


def _item_target(item: SemanticMemory | ProceduralMemory) -> str:
    return "%s/%s.md" % (_item_kind(item), item.id)


def _normal_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())[:300]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _source_path_for_ref(store: ScopedMemoryStore, ref: SourceRef) -> Path | None:
    if ref.kind != "source":
        return None
    ref_path = Path(str(ref.path or ""))
    if ref_path.is_absolute():
        return None
    parts = ref_path.parts
    if parts and parts[0] == "sources":
        candidate = store.paths.root / ref_path
    else:
        candidate = store.paths.sources_dir / ref_path
    if store.paths.sources_dir.exists() and store.paths.sources_dir.is_symlink():
        return None
    resolved_root = store.paths.sources_dir.resolve(strict=False)
    try:
        candidate.resolve(strict=False).relative_to(resolved_root)
    except ValueError:
        return None
    cursor = candidate
    checked = []
    while cursor != cursor.parent:
        checked.append(cursor)
        if cursor == store.paths.sources_dir:
            break
        cursor = cursor.parent
    for path in checked:
        if path.exists() and path.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except OSError:
        return candidate
    except ValueError:
        return None
    return resolved


def _check_hot_files(
    store: ScopedMemoryStore,
    *,
    max_bytes: int,
    issues: list[HealthIssue],
) -> None:
    for path in (
        store.paths.core_memory,
        store.paths.user_memory,
        store.paths.project_profile,
        store.paths.index,
    ):
        try:
            if path.exists() and path.is_file() and not path.is_symlink():
                size = path.stat().st_size
                if size > max_bytes:
                    issues.append(
                        _issue(
                            store.paths.scope,
                            "hot-file-large",
                            "warn",
                            path.name,
                            "%s is %s bytes, above %s" % (path.name, size, max_bytes),
                        )
                    )
        except OSError:
            continue


def _check_source_refs(
    store: ScopedMemoryStore,
    item: SemanticMemory | ProceduralMemory,
    *,
    issues: list[HealthIssue],
) -> None:
    target = _item_target(item)
    for ref in _item_refs(item):
        if ref.kind != "source":
            continue
        path = _source_path_for_ref(store, ref)
        if path is None:
            issues.append(
                _issue(
                    store.paths.scope,
                    "source-ref-outside",
                    "warn",
                    target,
                    "Source ref is outside sources/: %s" % ref.path,
                )
            )
            continue
        if not path.exists() or not path.is_file() or path.is_symlink():
            issues.append(
                _issue(
                    store.paths.scope,
                    "source-ref-missing",
                    "warn",
                    target,
                    "Source ref is missing: %s" % ref.path,
                )
            )
            continue
        identifier = str(ref.identifier or "").strip().lower()
        if len(identifier) >= MIN_HASH_PREFIX:
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            if not digest.startswith(identifier):
                issues.append(
                    _issue(
                        store.paths.scope,
                        "source-ref-tampered",
                        "warn",
                        target,
                        "Source hash does not match ref %s for %s" % (identifier, ref.path),
                    )
                )


def _check_memory_items(
    store: ScopedMemoryStore,
    *,
    low_confidence: float,
    stale_days: int,
    now: datetime,
    issues: list[HealthIssue],
) -> None:
    items: list[SemanticMemory | ProceduralMemory] = []
    items.extend(store.list_semantic_memories(limit=1000))
    items.extend(store.list_procedural_memories(limit=1000))
    duplicate_groups: dict[str, list[str]] = defaultdict(list)
    for item in items:
        target = _item_target(item)
        if item.confidence < low_confidence or item.strength < low_confidence:
            issues.append(
                _issue(
                    store.paths.scope,
                    "low-confidence-memory",
                    "warn",
                    target,
                    "confidence %.2f / strength %.2f below %.2f"
                    % (item.confidence, item.strength, low_confidence),
                )
            )
        updated = _parse_datetime(item.updated_at)
        if updated is not None and (now - updated).days > stale_days:
            issues.append(
                _issue(
                    store.paths.scope,
                    "stale-memory",
                    "info",
                    target,
                    "updated_at is older than %s days" % stale_days,
                )
            )
        if isinstance(item, SemanticMemory):
            conflicts = [entry for entry in item.update_log if "Conflict:" in entry]
            resolved = any("Resolved:" in entry or "Resolution:" in entry for entry in item.update_log)
            if conflicts and not resolved:
                issues.append(
                    _issue(
                        store.paths.scope,
                        "semantic-conflict-history",
                        "warn",
                        target,
                        "semantic memory has unresolved Conflict entries",
                    )
                )
            duplicate_groups[
                "%s|%s" % (_normal_key(item.title), _normal_key(item.content))
            ].append(target)
        else:
            duplicate_groups[
                "%s|%s" % (_normal_key(item.title), _normal_key(item.trigger))
            ].append(target)
        _check_source_refs(store, item, issues=issues)

    for targets in duplicate_groups.values():
        if len(targets) > 1:
            issues.append(
                _issue(
                    store.paths.scope,
                    "duplicate-memory",
                    "warn",
                    ", ".join(sorted(targets)),
                    "multiple memory items share the same normalized title/body",
                )
            )


def _check_root(
    root: Path,
    scope: str,
    *,
    hot_file_max_bytes: int,
    low_confidence: float,
    stale_days: int,
    now: datetime,
) -> dict:
    issues: list[HealthIssue] = []
    store = _safe_store(root, scope)
    if store is None:
        return {
            "scope": scope,
            "root": str(root),
            "status": "missing",
            "issues": [],
        }
    _check_hot_files(store, max_bytes=hot_file_max_bytes, issues=issues)
    _check_memory_items(
        store,
        low_confidence=low_confidence,
        stale_days=stale_days,
        now=now,
        issues=issues,
    )
    return {
        "scope": scope,
        "root": str(root),
        "status": "warn" if issues else "ok",
        "issues": [asdict(issue) for issue in issues],
    }


def run_health(
    *,
    project_root: str | Path,
    global_root: str | Path,
    scope: str = "all",
    hot_file_max_bytes: int = DEFAULT_HOT_FILE_MAX_BYTES,
    low_confidence: float = DEFAULT_LOW_CONFIDENCE,
    stale_days: int = DEFAULT_STALE_DAYS,
    now: datetime | None = None,
) -> dict:
    selected = []
    if scope in ("all", "global"):
        selected.append(("global", Path(global_root).expanduser()))
    if scope in ("all", "project"):
        selected.append(("project", Path(project_root).expanduser()))
    now = now or datetime.now(timezone.utc)
    roots = [
        _check_root(
            root,
            root_scope,
            hot_file_max_bytes=hot_file_max_bytes,
            low_confidence=low_confidence,
            stale_days=stale_days,
            now=now,
        )
        for root_scope, root in selected
    ]
    issues = [issue for row in roots for issue in row["issues"]]
    status = "warn" if issues else "ok"
    return {
        "status": status,
        "scope": scope,
        "issue_count": len(issues),
        "roots": roots,
        "issues": issues,
    }


def render_human(payload: dict) -> str:
    lines = [
        "# MemoryWiki Memory Health",
        "",
        "Status: %s" % payload["status"],
        "Issues: %s" % payload["issue_count"],
        "",
    ]
    for root in payload["roots"]:
        lines.append("- [%s] %s: %s" % (root["status"], root["scope"], root["root"]))
    if payload["issues"]:
        lines.append("")
        for issue in payload["issues"]:
            lines.append(
                "- [{severity}] {scope}/{code} {target}: {message}".format(**issue)
            )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run read-only MemoryWiki memory quality checks.")
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--scope", choices=("all", "project", "global"), default="all")
    parser.add_argument("--hot-file-max-bytes", type=int, default=DEFAULT_HOT_FILE_MAX_BYTES)
    parser.add_argument("--low-confidence", type=float, default=DEFAULT_LOW_CONFIDENCE)
    parser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_health(
            project_root=args.project_root,
            global_root=args.global_root,
            scope=args.scope,
            hot_file_max_bytes=args.hot_file_max_bytes,
            low_confidence=args.low_confidence,
            stale_days=args.stale_days,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0 if payload["status"] in {"ok", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
