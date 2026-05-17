from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Iterable

from memory_system.paths import MemoryScopePaths
from memory_system.sanitizer import sanitize_text
from memory_system.store import ScopedMemoryStore


QUEUE_NAME = "crystallize-candidates.jsonl"
MAX_TEXT_CHARS = 900


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_store(root: str | Path) -> ScopedMemoryStore:
    path = Path(root).expanduser()
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise ValueError("Memory root must be a real directory: %s" % path)
    cursor = path
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError("Memory root may not be below a symlink: %s" % cursor)
    for parent in cursor.parents:
        if parent.is_symlink():
            raise ValueError("Memory root may not be below a symlink: %s" % parent)
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(path, "project"),
        sanitize_on_write=True,
        secure_permissions=True,
    )


def _slug(text: str) -> str:
    ascii_text = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    if not ascii_text:
        ascii_text = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return ascii_text[:80]


def _candidate_id(kind: str, text: str) -> str:
    return "%s-%s" % (kind, _slug(text)[:64])


def _sentences(texts: Iterable[str]) -> Iterable[str]:
    for text in texts:
        clean = sanitize_text(text or "")
        for line in clean.splitlines():
            line = line.strip(" -\t")
            if not line:
                continue
            parts = re.split(r"(?<=[。.!?])\s+", line)
            for part in parts:
                part = part.strip(" -\t")
                if len(part) >= 20:
                    yield part[:MAX_TEXT_CHARS]


def _classify(text: str) -> str | None:
    lowered = text.lower()
    if any(marker in lowered for marker in ("procedure:", "workflow", "run ", "steps:", "checklist")):
        return "procedure"
    if any(
        marker in lowered
        for marker in (
            "stable decision",
            "reusable insight",
            "durable",
            "should ",
            "principle",
            "convention",
        )
    ):
        return "semantic"
    return None


def _title(text: str) -> str:
    clean = re.sub(r"^(stable decision|reusable insight|procedure)\s*:\s*", "", text, flags=re.I)
    return clean[:80].rstrip(".。 ")


def _session_candidates(store: ScopedMemoryStore, limit: int) -> list[dict]:
    rows: list[dict] = []
    seen = set()
    for meta in store.list_sessions(limit=limit):
        session = store.read_session(meta.id)
        if session is None:
            continue
        texts = list(session.keypoints) + list(session.actions) + list(session.pending) + [session.body]
        for sentence in _sentences(texts):
            kind = _classify(sentence)
            if not kind:
                continue
            key = (kind, sentence.lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "kind": kind,
                    "id": _candidate_id(kind, sentence),
                    "title": _title(sentence),
                    "answer": sentence,
                    "confidence": 0.55,
                    "strength": 0.5,
                    "source_kind": "session",
                    "source_path": "sessions/%s.md" % session.id,
                    "source_id": session.id,
                    "reason": "candidate extracted from stable-looking session text",
                }
            )
    return rows


def _episode_candidates(store: ScopedMemoryStore, limit: int) -> list[dict]:
    rows: list[dict] = []
    for date_text in store.list_episodes()[:limit]:
        episode = store.read_episode(date_text)
        if episode is None:
            continue
        for sentence in _sentences([episode.body]):
            kind = _classify(sentence)
            if not kind:
                continue
            rows.append(
                {
                    "kind": kind,
                    "id": _candidate_id(kind, sentence),
                    "title": _title(sentence),
                    "answer": sentence,
                    "confidence": 0.5,
                    "strength": 0.45,
                    "source_kind": "episode",
                    "source_path": "episodes/%s.md" % date_text,
                    "source_id": date_text,
                    "reason": "candidate extracted from stable-looking episode text",
                }
            )
    return rows


def _append_queue(store: ScopedMemoryStore, rows: list[dict]) -> Path:
    pending = store.paths.pending_dir
    if pending.exists() and pending.is_symlink():
        raise ValueError("_pending may not be a symlink: %s" % pending)
    pending.mkdir(parents=True, exist_ok=True)
    path = pending / QUEUE_NAME
    if path.exists() and path.is_symlink():
        raise ValueError("candidate queue may not be a symlink: %s" % path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        for row in rows:
            os.write(fd, (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return path


def propose_candidates(
    *,
    root: str | Path,
    limit: int = 20,
    write: bool = False,
    now: str | None = None,
) -> dict:
    root_path = Path(root).expanduser()
    if not write and not root_path.exists():
        return {
            "status": "empty",
            "root": str(root_path),
            "candidate_count": 0,
            "written": False,
            "queue_path": None,
            "candidates": [],
        }
    store = _safe_store(root)
    timestamp = now or _now()
    candidates = (_session_candidates(store, limit=limit) + _episode_candidates(store, limit=limit))[:limit]
    for row in candidates:
        row["ts"] = timestamp
    queue_path = None
    if write and candidates:
        queue_path = _append_queue(store, candidates)
    return {
        "status": "candidates" if candidates else "empty",
        "root": str(store.paths.root),
        "candidate_count": len(candidates),
        "written": bool(write and candidates),
        "queue_path": str(queue_path) if queue_path else None,
        "candidates": candidates,
    }


def render_human(payload: dict) -> str:
    lines = [
        "# MemoryWiki Crystallize Candidates",
        "",
        "Status: %s" % payload["status"],
        "Candidates: %s" % payload["candidate_count"],
        "Written: %s" % ("yes" if payload["written"] else "no"),
        "",
    ]
    for candidate in payload["candidates"]:
        lines.append(
            "- [{kind}] {id}: {title} ({source_path})".format(**candidate)
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Propose explicit crystallization candidates from sessions and episodes."
    )
    parser.add_argument("--root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Explicit write opt-in: append candidates to _pending/crystallize-candidates.jsonl.",
    )
    parser.add_argument("--now")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit <= 0:
        print("--limit must be positive", file=sys.stderr)
        return 2
    try:
        payload = propose_candidates(
            root=args.root,
            limit=args.limit,
            write=args.write,
            now=args.now,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
