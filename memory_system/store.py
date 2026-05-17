from __future__ import annotations

from contextlib import contextmanager
import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
import warnings

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

from memory_system.models import (
    AuditEntry,
    ChatMessage,
    EpisodeFile,
    ProceduralMemory,
    SemanticMemory,
    SessionFile,
    SessionMeta,
    SessionSummary,
    SourceRef,
    TokenUsage,
)
from memory_system.paths import MemoryPaths, MemoryScopePaths
from memory_system.sanitizer import neutralize_instruction_text, sanitize_text


CORE_MEMORY_TEMPLATE = """# Core Memory

## Identity And Mission

- Keep track of the user's long-term goals and current work.
"""


USER_MEMORY_TEMPLATE = """# User Memory

## Stable Facts

- No stable facts captured yet.
"""


INDEX_TEMPLATE = """# Memory Index

> Auto-generated navigation hub for this memory scope.
"""


MAX_MANAGED_READ_BYTES = 2_000_000
MAX_MANAGED_JSONL_ROWS = 10_000
MAX_MANAGED_FILES = 1_000
UPDATE_LOG_HEADING = "## Update Log"


class ScopedMemoryStore:
    def __init__(
        self,
        paths: MemoryScopePaths,
        sanitize_on_write: bool = True,
        secure_permissions: bool = True,
    ) -> None:
        self.paths = paths
        self.sanitize_on_write = sanitize_on_write
        self.secure_permissions = secure_permissions
        self._index_dirty_path = self.paths.root / ".INDEX_DIRTY"
        self._ensure_root()

    def append_history(self, message: ChatMessage) -> None:
        row = asdict(message)
        row["content"] = self._sanitize(row["content"])
        self._append_jsonl(self.paths.history, row)

    def append_token_usage(self, usage: TokenUsage) -> None:
        self._append_jsonl(self.paths.tokens, asdict(usage))

    def read_core_memory(self) -> str:
        return self._sanitize(
            self._read_or_create(self.paths.core_memory, CORE_MEMORY_TEMPLATE)
        )

    def write_core_memory(self, content: str) -> None:
        with self._file_lock():
            self._atomic_write_text_unlocked(
                self.paths.core_memory, self._sanitize(content).strip() + "\n"
            )
            self._mark_index_dirty_unlocked()

    def read_user_memory(self) -> str:
        return self._sanitize(
            self._read_or_create(self.paths.user_memory, USER_MEMORY_TEMPLATE)
        )

    def write_user_memory(self, content: str) -> None:
        with self._file_lock():
            self._atomic_write_text_unlocked(
                self.paths.user_memory, self._sanitize(content).strip() + "\n"
            )
            self._mark_index_dirty_unlocked()

    def read_index(self) -> str:
        if not self.paths.index.exists() or self._index_is_dirty():
            self.refresh_index(force=False)
        return self._sanitize(self._read_or_create(self.paths.index, INDEX_TEMPLATE))

    def refresh_index(self, force: bool = True) -> None:
        with self._file_lock():
            self._refresh_index_if_dirty_unlocked(force=force)

    def append_episodic(self, date_text: str, section_markdown: str) -> Path:
        path = self.paths.episodic_for_date(date_text)
        with self._file_lock():
            if not path.exists():
                self._atomic_write_text_unlocked(
                    path, "# %s Episodic Memory\n\n" % date_text
                )
            self._append_text_unlocked(
                path, self._sanitize(section_markdown).strip() + "\n\n"
            )
            self._mark_index_dirty_unlocked()
        return path

    def read_episodic(self, date_text: str) -> str:
        path = self.paths.episodic_for_date(date_text)
        self._assert_safe_managed_path(path)
        if not path.exists():
            return "# %s Episodic Memory\n" % date_text
        return self._sanitize(self._read_text_bounded(path))

    def write_session(self, session: SessionFile) -> Path:
        path = self.paths.session_file(session.id)
        content = self._serialize_session_file(session)
        with self._file_lock():
            self._atomic_write_text_unlocked(path, content)
            self._mark_index_dirty_unlocked()
        return path

    def read_session(self, session_id: str) -> SessionFile | None:
        path = self.paths.session_file(session_id)
        self._assert_safe_managed_path(path)
        if not path.exists():
            return None
        return self._parse_session_file(self._sanitize(self._read_text_bounded(path)))

    def list_sessions(self, limit: int = 30) -> list[SessionMeta]:
        sessions = []
        scan_limit = self._safe_file_limit(limit, default=30)
        for path in self._iter_safe_managed_files(
            self.paths.sessions_dir, "session-*.md", limit=scan_limit
        ):
            try:
                session = self._parse_session_file(
                    self._sanitize(self._read_text_bounded(path))
                )
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            sessions.append(
                SessionMeta(
                    id=session.id,
                    title=session.title,
                    started_at=session.date,
                    ended_at=None,
                )
            )
            if len(sessions) >= limit:
                break
        sessions.sort(key=lambda item: item.started_at or item.id, reverse=True)
        return sessions

    def append_to_episode(
        self,
        date_text: str,
        section_title: str,
        body: str,
        session_meta: SessionMeta | None = None,
    ) -> Path:
        path = self.paths.episode_for_date(date_text)
        heading = self._episode_heading(section_title)
        body_block = "%s\n\n%s" % (heading, self._sanitize(body).strip())
        with self._file_lock():
            if path.exists():
                self._assert_safe_managed_path(path)
                episode = self._parse_episode_file(
                    self._sanitize(self._read_text_bounded(path)),
                    fallback_date=date_text,
                )
            else:
                episode = EpisodeFile(
                    date=date_text,
                    scope=self.paths.scope,
                    sessions=[],
                    body="",
                )
            if session_meta is not None and not any(
                item.id == session_meta.id for item in episode.sessions
            ):
                episode.sessions.append(
                    SessionMeta(
                        id=self._sanitize(session_meta.id),
                        title=self._sanitize(session_meta.title),
                        started_at=self._sanitize(session_meta.started_at or "")
                        or None,
                        ended_at=self._sanitize(session_meta.ended_at or "") or None,
                    )
                )
            episode.body = (
                (episode.body.rstrip() + "\n\n" if episode.body.strip() else "")
                + body_block.strip()
                + "\n"
            )
            self._atomic_write_text_unlocked(path, self._serialize_episode_file(episode))
            self._mark_index_dirty_unlocked()
        return path

    def read_episode(self, date_text: str) -> EpisodeFile | None:
        path = self.paths.episode_for_date(date_text)
        self._assert_safe_managed_path(path)
        if not path.exists():
            return None
        return self._parse_episode_file(
            self._sanitize(self._read_text_bounded(path)),
            fallback_date=date_text,
        )

    def list_episodes(self, since: str | int | None = None) -> list[str]:
        dates = []
        limit = (
            self._safe_file_limit(since, default=MAX_MANAGED_FILES)
            if isinstance(since, int)
            else MAX_MANAGED_FILES
        )
        for path in self._iter_safe_managed_files(
            self.paths.episodes_dir, "20??-??-??.md", limit=limit
        ):
            dates.append(path.stem)
        if isinstance(since, str):
            dates = [date_text for date_text in dates if date_text >= since]
        return dates

    def write_semantic_memory(self, item: SemanticMemory) -> Path:
        path = self.paths.semantic_file(item.id)
        content = self._serialize_semantic_memory(item)
        with self._file_lock():
            self._atomic_write_text_unlocked(path, content)
            self._mark_index_dirty_unlocked()
        return path

    def read_semantic_memory(self, memory_id: str) -> SemanticMemory | None:
        path = self.paths.semantic_file(memory_id)
        self._assert_safe_managed_path(path)
        if not path.exists():
            return None
        return self._parse_semantic_memory(
            self._sanitize(self._read_text_bounded(path)),
            fallback_id=memory_id,
        )

    def list_semantic_memories(self, limit: int = 100) -> list[SemanticMemory]:
        items = []
        for path in self._iter_safe_managed_files(
            self.paths.semantic_dir,
            "*.md",
            limit=self._safe_file_limit(limit, default=100),
        ):
            try:
                items.append(
                    self._parse_semantic_memory(
                        self._sanitize(self._read_text_bounded(path)),
                        fallback_id=path.stem,
                    )
                )
            except (OSError, UnicodeDecodeError, ValueError):
                continue
        items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return items

    def append_semantic_update_log(
        self,
        memory_id: str,
        note: str,
        source_refs: list[SourceRef] | None = None,
        conflict: bool = False,
        now: str | None = None,
    ) -> Path:
        item = self.read_semantic_memory(memory_id)
        if item is None:
            raise ValueError("Unknown semantic memory: %s" % memory_id)
        timestamp = now or datetime.now().astimezone().isoformat(timespec="seconds")
        prefix = "Conflict:" if conflict else "Update:"
        refs = source_refs or []
        source_suffix = ""
        if refs:
            source_suffix = " Sources: " + ", ".join(
                self._sanitize(ref.path)[:1000] for ref in refs[:10]
            )
        item.update_log.append(
            "%s %s %s%s"
            % (timestamp, prefix, self._sanitize(note).strip(), source_suffix)
        )
        item.source_refs = self._merge_source_refs(item.source_refs, refs)
        item.updated_at = timestamp
        return self.write_semantic_memory(item)

    def write_procedural_memory(self, item: ProceduralMemory) -> Path:
        path = self.paths.procedure_file(item.id)
        content = self._serialize_procedural_memory(item)
        with self._file_lock():
            self._atomic_write_text_unlocked(path, content)
            self._mark_index_dirty_unlocked()
        return path

    def read_procedural_memory(self, memory_id: str) -> ProceduralMemory | None:
        path = self.paths.procedure_file(memory_id)
        self._assert_safe_managed_path(path)
        if not path.exists():
            return None
        return self._parse_procedural_memory(
            self._sanitize(self._read_text_bounded(path)),
            fallback_id=memory_id,
        )

    def list_procedural_memories(self, limit: int = 100) -> list[ProceduralMemory]:
        items = []
        for path in self._iter_safe_managed_files(
            self.paths.procedures_dir,
            "*.md",
            limit=self._safe_file_limit(limit, default=100),
        ):
            try:
                items.append(
                    self._parse_procedural_memory(
                        self._sanitize(self._read_text_bounded(path)),
                        fallback_id=path.stem,
                    )
                )
            except (OSError, UnicodeDecodeError, ValueError):
                continue
        items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return items

    def delete_semantic_memory(self, memory_id: str) -> bool:
        path = self.paths.semantic_file(memory_id)
        with self._file_lock():
            self._assert_mutable_managed_path(path)
            if not path.exists():
                return False
            path.unlink()
            self._mark_index_dirty_unlocked()
            return True

    def delete_procedural_memory(self, memory_id: str) -> bool:
        path = self.paths.procedure_file(memory_id)
        with self._file_lock():
            self._assert_mutable_managed_path(path)
            if not path.exists():
                return False
            path.unlink()
            self._mark_index_dirty_unlocked()
            return True

    def append_audit(self, entry: AuditEntry) -> None:
        row = asdict(entry)
        row["ts"] = self._sanitize(str(row["ts"]))
        row["action"] = self._sanitize(str(row["action"]))
        row["target_kind"] = self._sanitize(str(row["target_kind"]))
        row["target_id"] = self._sanitize(str(row["target_id"]))
        row["reason"] = self._sanitize(str(row["reason"]))
        row["dry_run"] = bool(row["dry_run"])
        row["details"] = self._sanitize_json(row.get("details", {}))
        self._append_jsonl(self.paths.audit_log, row)

    def append_source_ingest(self, row: dict) -> None:
        self._append_jsonl(self.paths.source_ingest_log, self._sanitize_json(row))

    def list_source_documents(self, limit: int = 100) -> list[Path]:
        limit = self._safe_file_limit(limit, default=100)
        try:
            self._assert_safe_managed_path(self.paths.sources_dir)
        except ValueError:
            return []
        if (
            not self.paths.sources_dir.exists()
            or not self.paths.sources_dir.is_dir()
            or self.paths.sources_dir.is_symlink()
        ):
            return []
        safe_paths = []
        for path in sorted(self.paths.sources_dir.rglob("*")):
            if not self._is_safe_readable_file(path):
                continue
            safe_paths.append(path)
            if len(safe_paths) >= limit:
                break
        return safe_paths

    def read_audit(self, limit: int = 100) -> list[AuditEntry]:
        rows = []
        if not self.paths.audit_log.exists():
            return rows
        try:
            lines = self._read_lines_bounded(self.paths.audit_log)
        except ValueError:
            return rows
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                details = payload.get("details", {})
                if not isinstance(details, dict):
                    details = {}
                rows.append(
                    AuditEntry(
                        ts=self._sanitize(str(payload["ts"])),
                        action=self._sanitize(str(payload["action"])),
                        target_kind=self._sanitize(str(payload["target_kind"])),
                        target_id=self._sanitize(str(payload["target_id"])),
                        reason=self._sanitize(str(payload.get("reason", ""))),
                        dry_run=bool(payload.get("dry_run", False)),
                        details=self._sanitize_json(details),
                    )
                )
            except (JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return rows[-limit:]

    def append_session_summary(self, summary: SessionSummary) -> None:
        row = asdict(summary)
        row["summary"] = self._sanitize(str(row["summary"]))
        row["key_points"] = [self._sanitize(str(item)) for item in row["key_points"]]
        row["actions_taken"] = [
            self._sanitize(str(item)) for item in row["actions_taken"]
        ]
        row["pending_tasks"] = [
            self._sanitize(str(item)) for item in row["pending_tasks"]
        ]
        self._append_jsonl(self.paths.sessions, row)

    def read_session_summaries(self, limit: int = 10) -> list[SessionSummary]:
        rows = []
        if not self.paths.sessions.exists():
            return rows
        try:
            lines = self._read_lines_bounded(self.paths.sessions)
        except ValueError:
            return rows
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                rows.append(
                    SessionSummary(
                        ts=self._sanitize(str(payload["ts"])),
                        session_id=self._sanitize(str(payload["session_id"])),
                        summary=self._sanitize(str(payload["summary"])),
                        key_points=[
                            self._sanitize(item)
                            for item in self._safe_string_list(
                                payload.get("key_points", [])
                            )
                        ],
                        actions_taken=[
                            self._sanitize(item)
                            for item in self._safe_string_list(
                                payload.get("actions_taken", [])
                            )
                        ],
                        pending_tasks=[
                            self._sanitize(item)
                            for item in self._safe_string_list(
                                payload.get("pending_tasks", [])
                            )
                        ],
                    )
                )
            except (JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        rows.sort(key=lambda row: row.ts, reverse=True)
        return rows[:limit]

    def _serialize_session_file(self, session: SessionFile) -> str:
        frontmatter = [
            "---",
            "id: %s" % self._frontmatter_scalar(session.id),
            "date: %s" % self._frontmatter_scalar(session.date),
            "scope: %s" % self._frontmatter_scalar(session.scope),
            "title: %s" % self._frontmatter_scalar(session.title),
        ]
        frontmatter.extend(self._frontmatter_string_list("keypoints", session.keypoints))
        frontmatter.extend(self._frontmatter_string_list("actions", session.actions))
        frontmatter.extend(self._frontmatter_string_list("pending", session.pending))
        frontmatter.append(
            "duration_seconds: %s"
            % (
                "null"
                if session.duration_seconds is None
                else int(session.duration_seconds)
            )
        )
        frontmatter.extend(["---", ""])
        return "\n".join(frontmatter) + self._sanitize(session.body).strip() + "\n"

    def _parse_session_file(self, text: str) -> SessionFile:
        frontmatter, body = self._split_frontmatter(text)
        duration = frontmatter.get("duration_seconds")
        if duration in (None, "", "null"):
            duration_seconds = None
        else:
            duration_seconds = int(str(duration))
        return SessionFile(
            id=self._sanitize(str(frontmatter.get("id", ""))),
            date=self._sanitize(str(frontmatter.get("date", ""))),
            scope=self._sanitize(str(frontmatter.get("scope", self.paths.scope))),
            title=self._sanitize(str(frontmatter.get("title", "Untitled session"))),
            keypoints=[
                self._sanitize(item)
                for item in self._safe_string_list(frontmatter.get("keypoints", []))
            ],
            actions=[
                self._sanitize(item)
                for item in self._safe_string_list(frontmatter.get("actions", []))
            ],
            pending=[
                self._sanitize(item)
                for item in self._safe_string_list(frontmatter.get("pending", []))
            ],
            duration_seconds=duration_seconds,
            body=self._sanitize(body.strip()),
        )

    def _serialize_episode_file(self, episode: EpisodeFile) -> str:
        frontmatter = [
            "---",
            "date: %s" % self._frontmatter_scalar(episode.date),
            "scope: %s" % self._frontmatter_scalar(episode.scope),
            "sessions:",
        ]
        if episode.sessions:
            for session in episode.sessions:
                frontmatter.append("  - id: %s" % self._frontmatter_scalar(session.id))
                frontmatter.append(
                    "    title: %s" % self._frontmatter_scalar(session.title)
                )
                frontmatter.append(
                    "    started_at: %s"
                    % self._frontmatter_scalar(session.started_at or "")
                )
                frontmatter.append(
                    "    ended_at: %s" % self._frontmatter_scalar(session.ended_at or "")
                )
        else:
            frontmatter[-1] = "sessions: []"
        frontmatter.extend(["---", ""])
        return "\n".join(frontmatter) + self._sanitize(episode.body).strip() + "\n"

    def _parse_episode_file(
        self, text: str, fallback_date: str | None = None
    ) -> EpisodeFile:
        frontmatter, body = self._split_frontmatter(text)
        sessions = []
        for item in frontmatter.get("sessions", []):
            if not isinstance(item, dict):
                continue
            sessions.append(
                SessionMeta(
                    id=self._sanitize(str(item.get("id", ""))),
                    title=self._sanitize(str(item.get("title", ""))),
                    started_at=self._sanitize(str(item.get("started_at", ""))) or None,
                    ended_at=self._sanitize(str(item.get("ended_at", ""))) or None,
                )
            )
        return EpisodeFile(
            date=self._sanitize(str(frontmatter.get("date", fallback_date or ""))),
            scope=self._sanitize(str(frontmatter.get("scope", self.paths.scope))),
            sessions=sessions,
            body=self._sanitize(body.strip()),
        )

    def _serialize_semantic_memory(self, item: SemanticMemory) -> str:
        frontmatter = [
            "---",
            "id: %s" % self._frontmatter_scalar(item.id),
            "scope: %s" % self._frontmatter_scalar(item.scope or self.paths.scope),
            "title: %s" % self._frontmatter_scalar(item.title),
            "confidence: %s" % self._safe_float(item.confidence),
            "strength: %s" % self._safe_float(item.strength),
            "last_accessed: %s" % self._frontmatter_scalar(item.last_accessed or ""),
            "created_at: %s" % self._frontmatter_scalar(item.created_at),
            "updated_at: %s" % self._frontmatter_scalar(item.updated_at),
            "source_refs_json: %s" % self._source_refs_json(item.source_refs),
        ]
        frontmatter.extend(self._frontmatter_string_list("concepts", item.concepts))
        frontmatter.extend(["---", ""])
        body = self._sanitize(item.content).strip()
        update_log = [self._sanitize(entry).strip() for entry in item.update_log if str(entry).strip()]
        if update_log:
            body = (
                body.rstrip()
                + "\n\n"
                + UPDATE_LOG_HEADING
                + "\n\n"
                + "\n".join("- %s" % self._frontmatter_scalar(entry) for entry in update_log)
            )
        return "\n".join(frontmatter) + body.strip() + "\n"

    def _parse_semantic_memory(
        self, text: str, fallback_id: str | None = None
    ) -> SemanticMemory:
        frontmatter, body = self._split_frontmatter(text)
        content, update_log = self._split_update_log(body.strip())
        return SemanticMemory(
            id=self._sanitize(str(frontmatter.get("id", fallback_id or ""))),
            scope=self._sanitize(str(frontmatter.get("scope", self.paths.scope))),
            title=self._sanitize(str(frontmatter.get("title", "Untitled memory"))),
            content=self._sanitize(content.strip()),
            concepts=[
                self._sanitize(item)
                for item in self._safe_string_list(frontmatter.get("concepts", []))
            ],
            source_refs=self._parse_source_refs(frontmatter.get("source_refs_json", "[]")),
            confidence=self._safe_float(frontmatter.get("confidence", 0.0)),
            strength=self._safe_float(frontmatter.get("strength", 0.0)),
            last_accessed=self._optional_sanitized_text(
                frontmatter.get("last_accessed")
            ),
            created_at=self._sanitize(str(frontmatter.get("created_at", ""))),
            updated_at=self._sanitize(str(frontmatter.get("updated_at", ""))),
            update_log=[self._sanitize(item) for item in update_log],
        )

    def _split_update_log(self, body: str) -> tuple[str, list[str]]:
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

    def _serialize_procedural_memory(self, item: ProceduralMemory) -> str:
        frontmatter = [
            "---",
            "id: %s" % self._frontmatter_scalar(item.id),
            "scope: %s" % self._frontmatter_scalar(item.scope or self.paths.scope),
            "title: %s" % self._frontmatter_scalar(item.title),
            "trigger: %s" % self._frontmatter_scalar(item.trigger),
            "confidence: %s" % self._safe_float(item.confidence),
            "strength: %s" % self._safe_float(item.strength),
            "last_accessed: %s" % self._frontmatter_scalar(item.last_accessed or ""),
            "created_at: %s" % self._frontmatter_scalar(item.created_at),
            "updated_at: %s" % self._frontmatter_scalar(item.updated_at),
            "source_refs_json: %s" % self._source_refs_json(item.source_refs),
        ]
        frontmatter.extend(self._frontmatter_string_list("steps", item.steps))
        frontmatter.extend(["---", ""])
        return "\n".join(frontmatter) + self._sanitize(item.trigger).strip() + "\n"

    def _parse_procedural_memory(
        self, text: str, fallback_id: str | None = None
    ) -> ProceduralMemory:
        frontmatter, body = self._split_frontmatter(text)
        trigger = self._sanitize(str(frontmatter.get("trigger", ""))).strip()
        if not trigger:
            trigger = self._sanitize(body.strip())
        return ProceduralMemory(
            id=self._sanitize(str(frontmatter.get("id", fallback_id or ""))),
            scope=self._sanitize(str(frontmatter.get("scope", self.paths.scope))),
            title=self._sanitize(str(frontmatter.get("title", "Untitled procedure"))),
            trigger=trigger,
            steps=[
                self._sanitize(item)
                for item in self._safe_string_list(frontmatter.get("steps", []))
            ],
            source_refs=self._parse_source_refs(frontmatter.get("source_refs_json", "[]")),
            confidence=self._safe_float(frontmatter.get("confidence", 0.0)),
            strength=self._safe_float(frontmatter.get("strength", 0.0)),
            last_accessed=self._optional_sanitized_text(
                frontmatter.get("last_accessed")
            ),
            created_at=self._sanitize(str(frontmatter.get("created_at", ""))),
            updated_at=self._sanitize(str(frontmatter.get("updated_at", ""))),
        )

    def _source_refs_json(self, refs: list[SourceRef]) -> str:
        rows = []
        for ref in refs[:50]:
            rows.append(
                {
                    "kind": self._sanitize(str(ref.kind))[:64],
                    "path": self._sanitize(str(ref.path))[:1000],
                    "identifier": self._optional_sanitized_text(ref.identifier),
                    "excerpt": self._optional_sanitized_text(ref.excerpt),
                }
            )
        return self._frontmatter_scalar(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        )

    def _parse_source_refs(self, value) -> list[SourceRef]:
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
                    kind=self._sanitize(str(item.get("kind", "")))[:64],
                    path=self._sanitize(str(item.get("path", "")))[:1000],
                    identifier=self._optional_sanitized_text(item.get("identifier")),
                    excerpt=self._optional_sanitized_text(item.get("excerpt")),
                )
            )
        return refs

    def _merge_source_refs(
        self, existing: list[SourceRef], incoming: list[SourceRef]
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

    def _optional_sanitized_text(self, value) -> str | None:
        if value is None:
            return None
        text = self._sanitize(str(value)).strip()
        return text or None

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        if number != number:
            number = default
        return max(0.0, min(1.0, number))

    def _sanitize_json(self, value):
        if isinstance(value, dict):
            return {
                self._sanitize(str(key))[:128]: self._sanitize_json(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._sanitize_json(item) for item in value[:100]]
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        return self._sanitize(str(value))[:2000]

    def _frontmatter_scalar(self, value: str | int | None) -> str:
        text = "" if value is None else self._sanitize(str(value))
        return text.replace("\n", " ").strip()

    def _frontmatter_string_list(self, key: str, items: list[str]) -> list[str]:
        if not items:
            return ["%s: []" % key]
        lines = ["%s:" % key]
        for item in items:
            lines.append("  - %s" % self._frontmatter_scalar(item))
        return lines

    def _split_frontmatter(self, text: str) -> tuple[dict, str]:
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
        frontmatter = self._parse_frontmatter_lines(lines[1:end_index])
        body = "\n".join(lines[end_index + 1 :])
        return frontmatter, body

    def _parse_frontmatter_lines(self, lines: list[str]) -> dict:
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
                value = self._parse_frontmatter_scalar(value.strip())
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
                        self._parse_frontmatter_scalar(line[4:].strip())
                    )
                continue
            if current_key == "sessions" and line.startswith("  - "):
                key, _, value = line[4:].partition(":")
                current_meta = {
                    key.strip(): self._parse_frontmatter_scalar(value.strip())
                }
                payload.setdefault("sessions", [])
                if isinstance(payload["sessions"], list):
                    payload["sessions"].append(current_meta)
                continue
            if current_key == "sessions" and current_meta is not None:
                key, separator, value = line.strip().partition(":")
                if separator:
                    current_meta[key.strip()] = self._parse_frontmatter_scalar(
                        value.strip()
                    )
        return payload

    def _parse_frontmatter_scalar(self, value):
        if value == "[]":
            return []
        if value in {"null", "None"}:
            return None
        return str(value)

    def _episode_heading(self, section_title: str) -> str:
        title = self._sanitize(section_title).strip() or "Session"
        parts = title.split(" ", 1)
        if parts and len(parts[0]) == 5 and parts[0][2] == ":":
            return "## %s" % title
        return "## %s %s" % (datetime.now().astimezone().strftime("%H:%M"), title)

    def _safe_string_list(self, value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    def _read_or_create(self, path: Path, template: str) -> str:
        self._assert_safe_managed_path(path)
        if not path.exists():
            with self._file_lock():
                self._assert_safe_managed_path(path)
                if not path.exists():
                    self._atomic_write_text_unlocked(path, template)
                if path != self.paths.index:
                    self._mark_index_dirty_unlocked()
        return self._read_text_bounded(path)

    def _append_jsonl(self, path: Path, row: dict) -> None:
        with self._file_lock():
            self._append_text_unlocked(path, json.dumps(row, ensure_ascii=False) + "\n")
            self._mark_index_dirty_unlocked()

    def _atomic_write_text(self, path: Path, content: str) -> None:
        with self._file_lock():
            self._atomic_write_text_unlocked(path, content)
            if path != self.paths.index:
                self._mark_index_dirty_unlocked()

    def _atomic_write_text_unlocked(self, path: Path, content: str) -> None:
        self._assert_mutable_managed_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = 0o600 if self.secure_permissions and os.name != "nt" else 0o666
        fd, temp_name = tempfile.mkstemp(
            prefix=".%s." % path.name,
            suffix=".tmp",
            dir=path.parent,
            text=False,
        )
        temp_path = Path(temp_name)
        try:
            if os.name != "nt":
                os.chmod(temp_path, mode)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content.encode("utf-8"))
            os.replace(temp_path, path)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            temp_path.unlink(missing_ok=True)
            raise
        self._secure_path(path)

    def _append_text(self, path: Path, content: str) -> None:
        with self._file_lock():
            self._append_text_unlocked(path, content)
            if path != self.paths.index:
                self._mark_index_dirty_unlocked()

    def _append_text_unlocked(self, path: Path, content: str) -> None:
        self._assert_mutable_managed_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        mode = 0o600 if self.secure_permissions and os.name != "nt" else 0o666
        try:
            fd = os.open(path, flags, mode)
        except OSError:
            if path.is_symlink():
                raise ValueError("Managed memory files may not be symlinks: %s" % path)
            raise
        try:
            with os.fdopen(fd, "ab") as handle:
                handle.write(content.encode("utf-8"))
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        self._secure_path(path)

    def _index_is_dirty(self) -> bool:
        return self._index_dirty_path.exists()

    def _mark_index_dirty_unlocked(self) -> None:
        self._atomic_write_text_unlocked(
            self._index_dirty_path,
            datetime.now().astimezone().isoformat(timespec="seconds") + "\n",
        )

    def _clear_index_dirty_unlocked(self) -> None:
        self._assert_safe_managed_path(self._index_dirty_path)
        if self._index_dirty_path.exists():
            if self._index_dirty_path.is_symlink():
                raise ValueError(
                    "Managed memory files may not be symlinks: %s"
                    % self._index_dirty_path
                )
            self._index_dirty_path.unlink()

    def _refresh_index_if_dirty_unlocked(self, force: bool = False) -> None:
        if not force and self.paths.index.exists() and not self._index_is_dirty():
            return
        self._refresh_index_unlocked()

    def _sanitize(self, text: str) -> str:
        if not self.sanitize_on_write:
            return text
        return sanitize_text(text)

    @contextmanager
    def _file_lock(self):
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self._assert_safe_managed_path(self.paths.lock_file)
        mode = 0o600 if self.secure_permissions and os.name != "nt" else 0o666
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.paths.lock_file, flags, mode)
        except OSError:
            if self.paths.lock_file.is_symlink():
                raise ValueError(
                    "Managed memory files may not be symlinks: %s"
                    % self.paths.lock_file
                )
            raise
        try:
            if os.name != "nt":
                os.chmod(self.paths.lock_file, mode)
            with os.fdopen(fd, "a+") as handle:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        self._secure_path(self.paths.lock_file)

    def _refresh_index_unlocked(self) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        legacy_episodic_paths = []
        for path in self._iter_safe_managed_files(
            self.paths.root, "20??-??-??.md"
        ):
            legacy_episodic_paths.append(path)
        episode_paths = []
        for path in self._iter_safe_managed_files(
            self.paths.episodes_dir, "20??-??-??.md"
        ):
            episode_paths.append(path)
        session_paths = []
        for path in self._iter_safe_managed_files(
            self.paths.sessions_dir, "session-*.md"
        ):
            session_paths.append(path)
        semantic_paths = []
        for path in self._iter_safe_managed_files(self.paths.semantic_dir, "*.md"):
            semantic_paths.append(path)
        procedure_paths = []
        for path in self._iter_safe_managed_files(self.paths.procedures_dir, "*.md"):
            procedure_paths.append(path)
        source_paths = self.list_source_documents(limit=MAX_MANAGED_FILES)

        lines = [
            "# Memory Index — %s" % self.paths.scope,
            "",
            "*Last refreshed: %s*" % datetime.now().astimezone().isoformat(timespec="minutes"),
            "",
            "> Auto-generated navigation hub for this memory scope.",
            "",
            "## Overview",
            "",
            "| Category | Count / Size | Location |",
            "|----------|--------------|----------|",
            "| Core Memory | %s chars | MEMORY.md |"
            % self._file_char_count(self.paths.core_memory),
            "| User Memory | %s chars | USER.md |"
            % self._file_char_count(self.paths.user_memory),
            "| Project Profile | %s chars | PROJECT_PROFILE.md |"
            % self._file_char_count(self.paths.project_profile),
            "| Sources | %s files | sources/ |" % len(source_paths),
            "| Episodic Memory | %s files | YYYY-MM-DD.md |"
            % len(legacy_episodic_paths),
            "| Episodes | %s files | episodes/YYYY-MM-DD.md |" % len(episode_paths),
            "| History | %s rows | history.jsonl |" % self._count_nonempty_lines(self.paths.history),
            "| Token Usage | %s rows | tokens.jsonl |" % self._count_nonempty_lines(self.paths.tokens),
            "| Session Summaries | %s rows | sessions.jsonl |"
            % self._count_nonempty_lines(self.paths.sessions),
            "| Session Files | %s files | sessions/session-*.md |" % len(session_paths),
            "| Semantic Memories | %s files | semantic/*.md |" % len(semantic_paths),
            "| Procedures | %s files | procedures/*.md |" % len(procedure_paths),
            "| Audit Log | %s rows | audit.jsonl |"
            % self._count_nonempty_lines(self.paths.audit_log),
            "| Source Ingest Log | %s rows | source_ingest.jsonl |"
            % self._count_nonempty_lines(self.paths.source_ingest_log),
            "",
            "## Episodes",
            "",
        ]
        if episode_paths:
            for path in episode_paths[:14]:
                preview = self._preview_text(path)
                lines.append("- **%s**: %s" % (path.stem, preview or "(empty)"))
        else:
            lines.append("- No v2 episodes yet.")

        lines.extend(["", "## Legacy Episodes", ""])
        if legacy_episodic_paths:
            for path in legacy_episodic_paths[:7]:
                preview = self._preview_text(path)
                lines.append("- **%s**: %s" % (path.stem, preview or "(empty)"))
        else:
            lines.append("- No legacy episodic memory yet.")

        recent_sessions = self.read_session_summaries(limit=5)
        lines.extend(["", "## Sessions", ""])
        if session_paths:
            for path in session_paths[:30]:
                preview = self._preview_text(path)
                lines.append("- **%s**: %s" % (path.stem, preview or "(empty)"))
        elif recent_sessions:
            for session in recent_sessions:
                lines.append(
                    "- **%s**: %s" % (session.session_id, session.summary[:120])
                )
        else:
            lines.append("- No session files yet.")

        lines.extend(["", "## Legacy Session Summaries", ""])
        if recent_sessions:
            for session in recent_sessions:
                lines.append(
                    "- **%s**: %s" % (session.session_id, session.summary[:120])
                )
        else:
            lines.append("- No legacy session summaries yet.")

        lines.extend(["", "## Semantic Memory", ""])
        if semantic_paths:
            for path in semantic_paths[:30]:
                preview = self._preview_text(path)
                lines.append("- **%s**: %s" % (path.stem, preview or "(empty)"))
        else:
            lines.append("- No semantic memories yet.")

        lines.extend(["", "## Procedures", ""])
        if procedure_paths:
            for path in procedure_paths[:30]:
                preview = self._preview_text(path)
                lines.append("- **%s**: %s" % (path.stem, preview or "(empty)"))
        else:
            lines.append("- No procedures yet.")

        lines.extend(["", "## Read-Only Sources", ""])
        if source_paths:
            for path in source_paths[:30]:
                try:
                    label = path.relative_to(self.paths.sources_dir).as_posix()
                except ValueError:
                    label = path.name
                preview = self._preview_text(path)
                lines.append("- **%s**: %s" % (label, preview or "(empty)"))
        else:
            lines.append("- No read-only source documents yet.")

        lines.extend(
            [
                "",
                "## Hot Files",
                "",
                "- MEMORY.md",
                "- USER.md",
                "- PROJECT_PROFILE.md",
                "",
            ]
        )
        self._atomic_write_text_unlocked(self.paths.index, "\n".join(lines))
        self._clear_index_dirty_unlocked()

    def _file_char_count(self, path: Path) -> int:
        try:
            return (
                len(self._read_text_bounded(path))
                if self._is_safe_readable_file(path)
                else 0
            )
        except (OSError, UnicodeDecodeError, ValueError):
            return 0

    def _count_nonempty_lines(self, path: Path) -> int:
        try:
            if not self._is_safe_readable_file(path):
                return 0
            return sum(1 for line in self._read_lines_bounded(path) if line)
        except (OSError, UnicodeDecodeError, ValueError):
            return 0

    def _preview_text(self, path: Path) -> str:
        try:
            if not self._is_safe_readable_file(path):
                return ""
            text = self._read_text_bounded(path)
        except (OSError, UnicodeDecodeError, ValueError):
            return ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return neutralize_instruction_text(self._sanitize(stripped))[:120]
        return ""

    def _iter_safe_managed_files(
        self, directory: Path, pattern: str, limit: int = MAX_MANAGED_FILES
    ) -> list[Path]:
        limit = self._safe_file_limit(limit, default=MAX_MANAGED_FILES)
        try:
            if directory == self.paths.root:
                if self.paths.root.is_symlink():
                    return []
            else:
                self._assert_safe_managed_path(directory)
        except ValueError:
            return []
        if limit <= 0 or not directory.exists() or not directory.is_dir():
            return []
        safe_paths = []
        for path in sorted(directory.glob(pattern), reverse=True):
            if not self._is_safe_readable_file(path):
                continue
            safe_paths.append(path)
            if len(safe_paths) >= limit:
                break
        return safe_paths

    def _safe_file_limit(self, limit, default: int) -> int:
        try:
            value = int(limit)
        except (TypeError, ValueError):
            value = default
        return min(max(value, 1), MAX_MANAGED_FILES)

    def _ensure_root(self) -> None:
        for component in [self.paths.root, *self.paths.root.parents]:
            if component.exists() and component.is_symlink():
                raise ValueError(
                    "Memory root may not be or be below a symlinked directory: %s"
                    % component
                )
        missing_dirs = []
        current = self.paths.root
        while not current.exists():
            missing_dirs.append(current)
            current = current.parent
        if current.is_symlink():
            raise ValueError(
                "Memory root may not be created below a symlinked directory: %s"
                % current
            )
        self.paths.root.mkdir(parents=True, exist_ok=True)
        if self.paths.root.is_symlink():
            raise ValueError("Memory root may not be a symlink: %s" % self.paths.root)
        if self.secure_permissions and os.name != "nt":
            for path in reversed(missing_dirs):
                os.chmod(path, 0o700)
            os.chmod(self.paths.root, 0o700)

    def _secure_path(self, path: Path) -> None:
        if self.secure_permissions and os.name != "nt" and path.exists():
            os.chmod(path, 0o600)

    def _assert_safe_managed_path(self, path: Path) -> None:
        if self.paths.root.is_symlink():
            raise ValueError("Memory root may not be a symlink: %s" % self.paths.root)
        if path.is_symlink():
            raise ValueError("Managed memory files may not be symlinks: %s" % path)
        root = self.paths.root.resolve(strict=True)
        parent = path.parent.resolve(strict=False)
        try:
            parent.relative_to(root)
        except ValueError:
            raise ValueError(
                "Managed memory path must stay within memory root: %s" % path
            )

    def _assert_mutable_managed_path(self, path: Path) -> None:
        self._assert_safe_managed_path(path)
        try:
            resolved_path = path.resolve(strict=False)
            resolved_sources = self.paths.sources_dir.resolve(strict=False)
            resolved_path.relative_to(resolved_sources)
        except (OSError, ValueError):
            return
        raise ValueError("sources/ is read-only for MemoryWiki writes: %s" % path)

    def _is_safe_readable_file(self, path: Path) -> bool:
        try:
            self._assert_safe_managed_path(path)
        except ValueError:
            return False
        return (
            path.exists()
            and path.is_file()
            and path.stat().st_size <= MAX_MANAGED_READ_BYTES
        )

    def _read_text_bounded(self, path: Path) -> str:
        self._assert_safe_managed_path(path)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags)
        except OSError:
            if path.is_symlink():
                raise ValueError("Managed memory files may not be symlinks: %s" % path)
            raise
        try:
            size = os.fstat(fd).st_size
            if size > MAX_MANAGED_READ_BYTES:
                raise ValueError("Managed memory file exceeds safe read limit: %s" % path)
            data = os.read(fd, size)
            return data.decode("utf-8")
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def _read_lines_bounded(self, path: Path) -> list[str]:
        lines = self._read_text_bounded(path).splitlines()
        if len(lines) > MAX_MANAGED_JSONL_ROWS:
            warnings.warn(
                "Managed JSONL file exceeds safe row limit; truncating to %s rows: %s"
                % (MAX_MANAGED_JSONL_ROWS, path),
                RuntimeWarning,
                stacklevel=2,
            )
        return lines[:MAX_MANAGED_JSONL_ROWS]


class MemoryStore(ScopedMemoryStore):
    """Compatibility shim that now keeps the safer ScopedMemoryStore defaults.

    Prefer ScopedMemoryStore for new code so callers choose safety settings
    explicitly.
    """

    def __init__(self, paths: MemoryPaths) -> None:
        super().__init__(
            paths=MemoryScopePaths(root=paths.root, scope="project"),
            sanitize_on_write=True,
            secure_permissions=True,
        )
