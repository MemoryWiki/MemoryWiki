from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any

from memory_system.sanitizer import sanitize_text


LEDGER_NAME = "retrieval_feedback.jsonl"
MAX_FIELD_CHARS = 5000
VALID_RATINGS = ("useful", "not-useful", "missing")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_root(root: str | Path) -> Path:
    path = Path(root).expanduser()
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise ValueError("Feedback root must be a real directory: %s" % path)
    cursor = path
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError("Feedback root may not be below a symlink: %s" % cursor)
    for parent in cursor.parents:
        if parent.is_symlink():
            raise ValueError("Feedback root may not be below a symlink: %s" % parent)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clean(value: Any) -> str:
    return sanitize_text(str(value or ""))[:MAX_FIELD_CHARS]


def _append_jsonl(root: Path, row: dict[str, Any]) -> Path:
    path = root / LEDGER_NAME
    if path.exists() and path.is_symlink():
        raise ValueError("Feedback ledger may not be a symlink: %s" % path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return path


def append_feedback(
    *,
    root: str | Path,
    query: str,
    rating: str,
    hit_scope: str = "",
    hit_source: str = "",
    hit_identifier: str = "",
    reason: str = "",
    now: str | None = None,
) -> dict[str, Any]:
    if rating not in VALID_RATINGS:
        raise ValueError("rating must be one of: %s" % ", ".join(VALID_RATINGS))
    root_path = _safe_root(root)
    row = {
        "ts": now or _now(),
        "event": "recall_feedback",
        "query": _clean(query),
        "rating": rating,
        "hit_scope": _clean(hit_scope),
        "hit_source": _clean(hit_source),
        "hit_identifier": _clean(hit_identifier),
        "reason": _clean(reason),
    }
    _append_jsonl(root_path, row)
    row["ledger_path"] = str(root_path / LEDGER_NAME)
    return row


def append_recall_trace(
    *,
    root: str | Path,
    result: Any,
    now: str | None = None,
) -> dict[str, Any]:
    root_path = _safe_root(root)
    top_hits = []
    for hit in getattr(result, "hits", [])[:10]:
        top_hits.append(
            {
                "scope": _clean(getattr(hit, "scope", "")),
                "source": _clean(getattr(hit, "source", "")),
                "identifier": _clean(getattr(hit, "identifier", "")),
                "title": _clean(getattr(hit, "title", "")),
                "score": round(float(getattr(hit, "score", 0.0) or 0.0), 4),
                "provenance": [
                    asdict(ref) if hasattr(ref, "__dataclass_fields__") else dict(ref)
                    for ref in getattr(hit, "provenance", [])[:5]
                    if isinstance(ref, dict) or hasattr(ref, "__dataclass_fields__")
                ],
            }
        )
    row = {
        "ts": now or _now(),
        "event": "recall_trace",
        "query": _clean(getattr(result, "query", "")),
        "strategy": _clean(getattr(result, "strategy", "")),
        "tokens_used": int(getattr(result, "tokens_used", 0) or 0),
        "truncated": bool(getattr(result, "truncated", False)),
        "warnings": [_clean(item) for item in getattr(result, "warnings", [])[:10]],
        "top_hits": top_hits,
    }
    _append_jsonl(root_path, row)
    row["ledger_path"] = str(root_path / LEDGER_NAME)
    return row


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append explicit MemoryWiki recall feedback.")
    parser.add_argument("--root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--query", required=True)
    parser.add_argument("--rating", choices=VALID_RATINGS, required=True)
    parser.add_argument("--hit-scope", default="")
    parser.add_argument("--hit-source", default="")
    parser.add_argument("--hit-identifier", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--now")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def render_human(row: dict[str, Any]) -> str:
    return (
        "Recorded recall feedback: {rating} for {hit_scope}/{hit_source}/{hit_identifier}\n"
        "Ledger: {ledger_path}\n"
    ).format(**row)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        row = append_feedback(
            root=args.root,
            query=args.query,
            rating=args.rating,
            hit_scope=args.hit_scope,
            hit_source=args.hit_source,
            hit_identifier=args.hit_identifier,
            reason=args.reason,
            now=args.now,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(row, ensure_ascii=False, indent=2))
    else:
        print(render_human(row), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
