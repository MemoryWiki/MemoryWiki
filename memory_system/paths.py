from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Union


EPISODIC_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SESSION_ID_RE = re.compile(r"session-[A-Za-z0-9][A-Za-z0-9_.-]*")
MEMORY_ITEM_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def validate_episodic_date(date_text: str) -> str:
    if not EPISODIC_DATE_RE.fullmatch(date_text or ""):
        raise ValueError("Episodic date must use YYYY-MM-DD format")
    return date_text


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID_RE.fullmatch(session_id or ""):
        raise ValueError(
            "Session ID must start with session- and contain only letters, digits, dots, underscores, or dashes"
        )
    return session_id


def validate_memory_item_id(memory_id: str) -> str:
    if not MEMORY_ITEM_ID_RE.fullmatch(memory_id or ""):
        raise ValueError(
            "Memory item ID must start with a letter or digit and contain only letters, digits, dots, underscores, or dashes"
        )
    return memory_id


@dataclass
class MemoryScopePaths:
    root: Path
    scope: str

    @classmethod
    def from_root(cls, root: Union[str, Path], scope: str) -> "MemoryScopePaths":
        return cls(Path(root), scope)

    @property
    def history(self) -> Path:
        return self.root / "history.jsonl"

    @property
    def tokens(self) -> Path:
        return self.root / "tokens.jsonl"

    @property
    def core_memory(self) -> Path:
        return self.root / "MEMORY.md"

    @property
    def user_memory(self) -> Path:
        return self.root / "USER.md"

    @property
    def project_profile(self) -> Path:
        return self.root / "PROJECT_PROFILE.md"

    @property
    def index(self) -> Path:
        return self.root / "INDEX.md"

    @property
    def sources_dir(self) -> Path:
        return self.root / "sources"

    @property
    def source_ingest_log(self) -> Path:
        return self.root / "source_ingest.jsonl"

    @property
    def episodes_dir(self) -> Path:
        return self.root / "episodes"

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    @property
    def sessions(self) -> Path:
        return self.root / "sessions.jsonl"

    @property
    def pending_dir(self) -> Path:
        return self.root / "_pending"

    @property
    def semantic_dir(self) -> Path:
        return self.root / "semantic"

    @property
    def procedures_dir(self) -> Path:
        return self.root / "procedures"

    @property
    def audit_log(self) -> Path:
        return self.root / "audit.jsonl"

    @property
    def retrieval_dir(self) -> Path:
        return self.root / "retrieval"

    @property
    def retrieval_index(self) -> Path:
        return self.retrieval_dir / "index.jsonl"

    @property
    def lock_file(self) -> Path:
        return self.root / ".memory.lock"

    def episodic_for_date(self, date_text: str) -> Path:
        validate_episodic_date(date_text)
        return self.root / ("%s.md" % date_text)

    def episode_for_date(self, date_text: str) -> Path:
        validate_episodic_date(date_text)
        return self.episodes_dir / ("%s.md" % date_text)

    def session_file(self, session_id: str) -> Path:
        validate_session_id(session_id)
        return self.sessions_dir / ("%s.md" % session_id)

    def semantic_file(self, memory_id: str) -> Path:
        validate_memory_item_id(memory_id)
        return self.semantic_dir / ("%s.md" % memory_id)

    def procedure_file(self, memory_id: str) -> Path:
        validate_memory_item_id(memory_id)
        return self.procedures_dir / ("%s.md" % memory_id)

    def ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


MemoryPaths = MemoryScopePaths
