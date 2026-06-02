"""Markdown/frontmatter codecs for semantic, procedural, session, and episode files."""

from __future__ import annotations

import json
from datetime import datetime
from json import JSONDecodeError
from typing import Any

from memory_system.models import (
    EpisodeFile,
    ProceduralMemory,
    SemanticMemory,
    SessionFile,
    SessionMeta,
    SourceRef,
)

UPDATE_LOG_HEADING = "## Update Log"


def sanitized_text(store: Any, value: Any) -> str:
    return str(store._sanitize(str(value)))


def serialize_session_file(store: Any, session: SessionFile) -> str:
    frontmatter = [
        "---",
        f"id: {frontmatter_scalar(store, session.id)}",
        f"date: {frontmatter_scalar(store, session.date)}",
        f"scope: {frontmatter_scalar(store, session.scope)}",
        f"title: {frontmatter_scalar(store, session.title)}",
    ]
    frontmatter.extend(frontmatter_string_list(store, "keypoints", session.keypoints))
    frontmatter.extend(frontmatter_string_list(store, "actions", session.actions))
    frontmatter.extend(frontmatter_string_list(store, "pending", session.pending))
    frontmatter.append(
        "duration_seconds: "
        + (
            "null"
            if session.duration_seconds is None
            else str(int(session.duration_seconds))
        )
    )
    frontmatter.extend(["---", ""])
    return "\n".join(frontmatter) + sanitized_text(store, session.body).strip() + "\n"


def parse_session_file(store: Any, text: str) -> SessionFile:
    frontmatter, body = split_frontmatter(store, text)
    duration = frontmatter.get("duration_seconds")
    if duration in (None, "", "null"):
        duration_seconds = None
    else:
        duration_seconds = int(str(duration))
    return SessionFile(
        id=store._sanitize(str(frontmatter.get("id", ""))),
        date=store._sanitize(str(frontmatter.get("date", ""))),
        scope=store._sanitize(str(frontmatter.get("scope", store.paths.scope))),
        title=store._sanitize(str(frontmatter.get("title", "Untitled session"))),
        keypoints=[
            store._sanitize(item)
            for item in safe_string_list(frontmatter.get("keypoints", []))
        ],
        actions=[
            store._sanitize(item)
            for item in safe_string_list(frontmatter.get("actions", []))
        ],
        pending=[
            store._sanitize(item)
            for item in safe_string_list(frontmatter.get("pending", []))
        ],
        duration_seconds=duration_seconds,
        body=store._sanitize(body.strip()),
    )


def serialize_episode_file(store: Any, episode: EpisodeFile) -> str:
    frontmatter = [
        "---",
        f"date: {frontmatter_scalar(store, episode.date)}",
        f"scope: {frontmatter_scalar(store, episode.scope)}",
        "sessions:",
    ]
    if episode.sessions:
        for session in episode.sessions:
            frontmatter.append(f"  - id: {frontmatter_scalar(store, session.id)}")
            frontmatter.append(
                f"    title: {frontmatter_scalar(store, session.title)}"
            )
            frontmatter.append(
                "    started_at: "
                + frontmatter_scalar(store, session.started_at or "")
            )
            frontmatter.append(
                f"    ended_at: {frontmatter_scalar(store, session.ended_at or '')}"
            )
    else:
        frontmatter[-1] = "sessions: []"
    frontmatter.extend(["---", ""])
    return "\n".join(frontmatter) + sanitized_text(store, episode.body).strip() + "\n"


def parse_episode_file(
    store: Any, text: str, fallback_date: str | None = None
) -> EpisodeFile:
    frontmatter, body = split_frontmatter(store, text)
    sessions = []
    for item in frontmatter.get("sessions", []):
        if not isinstance(item, dict):
            continue
        sessions.append(
            SessionMeta(
                id=store._sanitize(str(item.get("id", ""))),
                title=store._sanitize(str(item.get("title", ""))),
                started_at=store._sanitize(str(item.get("started_at", ""))) or None,
                ended_at=store._sanitize(str(item.get("ended_at", ""))) or None,
            )
        )
    return EpisodeFile(
        date=store._sanitize(str(frontmatter.get("date", fallback_date or ""))),
        scope=store._sanitize(str(frontmatter.get("scope", store.paths.scope))),
        sessions=sessions,
        body=store._sanitize(body.strip()),
    )


def serialize_semantic_memory(store: Any, item: SemanticMemory) -> str:
    frontmatter = [
        "---",
        f"id: {frontmatter_scalar(store, item.id)}",
        f"scope: {frontmatter_scalar(store, item.scope or store.paths.scope)}",
        f"title: {frontmatter_scalar(store, item.title)}",
        f"confidence: {safe_float(item.confidence)}",
        f"strength: {safe_float(item.strength)}",
        f"last_accessed: {frontmatter_scalar(store, item.last_accessed or '')}",
        f"created_at: {frontmatter_scalar(store, item.created_at)}",
        f"updated_at: {frontmatter_scalar(store, item.updated_at)}",
        f"source_refs_json: {source_refs_json(store, item.source_refs)}",
    ]
    frontmatter.extend(frontmatter_string_list(store, "concepts", item.concepts))
    frontmatter.extend(["---", ""])
    body = sanitized_text(store, item.content).strip()
    update_log = [
        store._sanitize(entry).strip()
        for entry in item.update_log
        if str(entry).strip()
    ]
    if update_log:
        entries = "\n".join(
            f"- {frontmatter_scalar(store, entry)}" for entry in update_log
        )
        body = body.rstrip() + "\n\n" + UPDATE_LOG_HEADING + "\n\n" + entries
    return "\n".join(frontmatter) + body.strip() + "\n"


def parse_semantic_memory(
    store: Any, text: str, fallback_id: str | None = None
) -> SemanticMemory:
    frontmatter, body = split_frontmatter(store, text)
    content, update_log = split_update_log(body.strip())
    return SemanticMemory(
        id=store._sanitize(str(frontmatter.get("id", fallback_id or ""))),
        scope=store._sanitize(str(frontmatter.get("scope", store.paths.scope))),
        title=store._sanitize(str(frontmatter.get("title", "Untitled memory"))),
        content=store._sanitize(content.strip()),
        concepts=[
            store._sanitize(item)
            for item in safe_string_list(frontmatter.get("concepts", []))
        ],
        source_refs=parse_source_refs(
            store, frontmatter.get("source_refs_json", "[]")
        ),
        confidence=safe_float(frontmatter.get("confidence", 0.0)),
        strength=safe_float(frontmatter.get("strength", 0.0)),
        last_accessed=optional_sanitized_text(store, frontmatter.get("last_accessed")),
        created_at=store._sanitize(str(frontmatter.get("created_at", ""))),
        updated_at=store._sanitize(str(frontmatter.get("updated_at", ""))),
        update_log=[store._sanitize(item) for item in update_log],
    )


def split_update_log(body: str) -> tuple[str, list[str]]:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower() == UPDATE_LOG_HEADING.lower():
            content = "\n".join(lines[:index]).strip()
            entries = []
            for entry_line in lines[index + 1 :]:
                stripped = entry_line.strip()
                if stripped.startswith("- "):
                    entries.append(stripped[2:].strip())
                elif stripped and entries:
                    entries[-1] = (entries[-1] + " " + stripped).strip()
            return content, entries
    return body, []


def serialize_procedural_memory(store: Any, item: ProceduralMemory) -> str:
    frontmatter = [
        "---",
        f"id: {frontmatter_scalar(store, item.id)}",
        f"scope: {frontmatter_scalar(store, item.scope or store.paths.scope)}",
        f"title: {frontmatter_scalar(store, item.title)}",
        f"trigger: {frontmatter_scalar(store, item.trigger)}",
        f"confidence: {safe_float(item.confidence)}",
        f"strength: {safe_float(item.strength)}",
        f"last_accessed: {frontmatter_scalar(store, item.last_accessed or '')}",
        f"created_at: {frontmatter_scalar(store, item.created_at)}",
        f"updated_at: {frontmatter_scalar(store, item.updated_at)}",
        f"source_refs_json: {source_refs_json(store, item.source_refs)}",
    ]
    frontmatter.extend(frontmatter_string_list(store, "steps", item.steps))
    frontmatter.extend(["---", ""])
    return "\n".join(frontmatter) + sanitized_text(store, item.trigger).strip() + "\n"


def parse_procedural_memory(
    store: Any, text: str, fallback_id: str | None = None
) -> ProceduralMemory:
    frontmatter, body = split_frontmatter(store, text)
    trigger = store._sanitize(str(frontmatter.get("trigger", ""))).strip()
    if not trigger:
        trigger = store._sanitize(body.strip())
    return ProceduralMemory(
        id=store._sanitize(str(frontmatter.get("id", fallback_id or ""))),
        scope=store._sanitize(str(frontmatter.get("scope", store.paths.scope))),
        title=store._sanitize(str(frontmatter.get("title", "Untitled procedure"))),
        trigger=trigger,
        steps=[
            store._sanitize(item)
            for item in safe_string_list(frontmatter.get("steps", []))
        ],
        source_refs=parse_source_refs(
            store, frontmatter.get("source_refs_json", "[]")
        ),
        confidence=safe_float(frontmatter.get("confidence", 0.0)),
        strength=safe_float(frontmatter.get("strength", 0.0)),
        last_accessed=optional_sanitized_text(store, frontmatter.get("last_accessed")),
        created_at=store._sanitize(str(frontmatter.get("created_at", ""))),
        updated_at=store._sanitize(str(frontmatter.get("updated_at", ""))),
    )


def source_refs_json(store: Any, refs: list[SourceRef]) -> str:
    rows = []
    for ref in refs[:50]:
        rows.append(
            {
                "kind": store._sanitize(str(ref.kind))[:64],
                "path": store._sanitize(str(ref.path))[:1000],
                "identifier": optional_sanitized_text(store, ref.identifier),
                "excerpt": optional_sanitized_text(store, ref.excerpt),
            }
        )
    return frontmatter_scalar(
        store, json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    )


def parse_source_refs(store: Any, value: Any) -> list[SourceRef]:
    try:
        payload = json.loads(str(value or "[]"))
    except (JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    refs = []
    for item in payload[:50]:
        if not isinstance(item, dict):
            continue
        refs.append(
            SourceRef(
                kind=store._sanitize(str(item.get("kind", "")))[:64],
                path=store._sanitize(str(item.get("path", "")))[:1000],
                identifier=optional_sanitized_text(store, item.get("identifier")),
                excerpt=optional_sanitized_text(store, item.get("excerpt")),
            )
        )
    return refs


def merge_source_refs(
    existing: list[SourceRef], incoming: list[SourceRef]
) -> list[SourceRef]:
    merged = []
    seen = set()
    for ref in (existing or []) + (incoming or []):
        key = (ref.kind, ref.path, ref.identifier, ref.excerpt)
        if key in seen:
            continue
        seen.add(key)
        merged.append(ref)
        if len(merged) >= 50:
            break
    return merged


def optional_sanitized_text(store: Any, value: Any) -> str | None:
    if value is None:
        return None
    text = store._sanitize(str(value)).strip()
    return text or None


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def sanitize_json(store: Any, value: Any) -> Any:
    if isinstance(value, dict):
        return {
            store._sanitize(str(key))[:128]: sanitize_json(store, item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_json(store, item) for item in value[:100]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return store._sanitize(str(value))[:2000]


def frontmatter_scalar(store: Any, value: str | int | None) -> str:
    text = "" if value is None else sanitized_text(store, value)
    return text.replace("\n", " ").strip()


def frontmatter_string_list(store: Any, key: str, items: list[str]) -> list[str]:
    if not items:
        return [f"{key}: []"]
    lines = [f"{key}:"]
    for item in items:
        lines.append(f"  - {frontmatter_scalar(store, item)}")
    return lines


def split_frontmatter(store: Any, text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    lines = text.splitlines()
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line == "---":
            end_index = index
            break
    if end_index is None:
        return {}, text
    frontmatter = parse_frontmatter_lines(store, lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :])
    return frontmatter, body


def parse_frontmatter_lines(store: Any, lines: list[str]) -> dict:
    payload: dict = {}
    current_key = None
    current_meta = None
    for line in lines:
        if not line.strip():
            continue
        if not line.startswith(" "):
            key, separator, value = line.partition(":")
            if not separator:
                current_key = None
                continue
            key = key.strip()
            value = parse_frontmatter_scalar(value.strip())
            current_key = key
            current_meta = None
            if value == [] or (
                value == ""
                and key
                in {"keypoints", "actions", "pending", "sessions", "concepts", "steps"}
            ):
                payload[key] = []
            else:
                payload[key] = value
            continue
        if current_key in {
            "keypoints",
            "actions",
            "pending",
            "concepts",
            "steps",
        } and line.startswith("  - "):
            payload.setdefault(current_key, [])
            if isinstance(payload[current_key], list):
                payload[current_key].append(
                    parse_frontmatter_scalar(line[4:].strip())
                )
            continue
        if current_key == "sessions" and line.startswith("  - "):
            key, _, value = line[4:].partition(":")
            current_meta = {key.strip(): parse_frontmatter_scalar(value.strip())}
            payload.setdefault("sessions", [])
            if isinstance(payload["sessions"], list):
                payload["sessions"].append(current_meta)
            continue
        if current_key == "sessions" and current_meta is not None:
            key, separator, value = line.strip().partition(":")
            if separator:
                current_meta[key.strip()] = parse_frontmatter_scalar(value.strip())
    return payload


def parse_frontmatter_scalar(value: Any) -> Any:
    if value == "[]":
        return []
    if value in {"null", "None"}:
        return None
    return str(value)


def episode_heading(store: Any, section_title: str) -> str:
    title = store._sanitize(section_title).strip() or "Session"
    parts = title.split(" ", 1)
    if parts and len(parts[0]) == 5 and parts[0][2] == ":":
        return f"## {title}"
    timestamp = datetime.now().astimezone().strftime("%H:%M")
    return f"## {timestamp} {title}"


def safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
