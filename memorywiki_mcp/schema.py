from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SESSION_RE = re.compile(r"^session-[A-Za-z0-9][A-Za-z0-9_.-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RecallInput(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)
    scope: Literal["all", "project", "global"] = "all"
    limit: int = Field(default=8, ge=1, le=500)
    token_budget: int = Field(default=1200, ge=1, le=100_000)
    embedding: Literal["off", "local"] = "off"
    graph: Literal["off", "local"] = "local"
    ranker: Literal["rrf", "score"] = "rrf"
    strategy: Literal["live", "indexed", "hybrid"] = "hybrid"
    explain_score: bool = False
    refresh_index_if_needed: bool = False
    project_root: Optional[str] = None
    global_root: Optional[str] = None


class RecallHitOutput(BaseModel):
    scope: str
    source: str
    identifier: str
    title: str
    excerpt: str
    score: float
    tokens: int
    provenance: List[Dict[str, Any]]
    score_explanation: Dict[str, Any] = Field(default_factory=dict)


class RecallOutput(BaseModel):
    query: str
    strategy: str
    tokens_used: int
    truncated: bool
    warnings: List[str] = Field(default_factory=list)
    hits: List[RecallHitOutput] = Field(default_factory=list)


class ListInput(BaseModel):
    scope: Literal["all", "project", "global"] = "project"
    kind: Literal["all", "semantic", "procedural", "procedure", "session", "episode"] = "all"
    concepts: List[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=100, ge=1, le=500)
    project_root: Optional[str] = None
    global_root: Optional[str] = None


class ListMemoryItem(BaseModel):
    scope: str
    kind: str
    identifier: str
    title: str
    created_at: str = ""
    updated_at: str = ""
    concepts: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    strength: Optional[float] = None


class ListOutput(BaseModel):
    scope: str
    kind: str
    count: int
    memories: List[ListMemoryItem] = Field(default_factory=list)


class ReadMemoryInput(BaseModel):
    scope: Literal["project", "global"] = "project"
    kind: Literal[
        "semantic",
        "procedural",
        "procedure",
        "episode",
        "session",
        "core",
        "user",
        "index",
        "project_profile",
    ]
    identifier: str = ""
    max_chars: int = Field(default=5_000, ge=100, le=50_000)
    full: bool = False
    project_root: Optional[str] = None
    global_root: Optional[str] = None

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not value:
            return value
        if DATE_RE.fullmatch(value) or SESSION_RE.fullmatch(value) or IDENTIFIER_RE.fullmatch(value):
            return value
        raise ValueError("identifier must be a memory id, session id, or YYYY-MM-DD date")


class ReadMemoryOutput(BaseModel):
    found: bool
    scope: str
    kind: str
    identifier: str
    content: str = ""
    frontmatter: Dict[str, Any] = Field(default_factory=dict)
    update_log: List[str] = Field(default_factory=list)
    truncated: bool = False


class IndexMaintainInput(BaseModel):
    scope: Literal["all", "project", "global"] = "all"
    write: bool = False
    agent: str = Field(default="memorywiki-mcp", min_length=1, max_length=120)
    lease_ttl_seconds: int = Field(default=3600, ge=1, le=86_400)
    project_root: Optional[str] = None
    global_root: Optional[str] = None


class IndexRootStatus(BaseModel):
    scope: str
    root: str
    index_path: str
    status: str
    fresh: bool
    needs_rebuild: bool
    rebuilt: bool
    indexed: int
    warnings: List[str] = Field(default_factory=list)
    lease_id: Optional[str] = None


class IndexMaintainOutput(BaseModel):
    dry_run: bool
    scope: str
    rebuild_needed: bool
    rebuilt: bool
    roots: List[IndexRootStatus]


class WriteSessionInput(BaseModel):
    scope: Literal["project", "global"] = "project"
    summary: str = Field(min_length=1, max_length=10_000)
    reason: str = Field(min_length=1, max_length=500)
    title: Optional[str] = Field(default=None, max_length=240)
    session_id: Optional[str] = None
    keypoints: List[str] = Field(default_factory=list, max_length=50)
    actions: List[str] = Field(default_factory=list, max_length=50)
    pending: List[str] = Field(default_factory=list, max_length=50)
    body: Optional[str] = Field(default=None, max_length=50_000)
    duration_seconds: Optional[int] = Field(default=None, ge=0, le=60 * 60 * 24)
    write_episode: bool = True
    project_root: Optional[str] = None
    global_root: Optional[str] = None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if SESSION_RE.fullmatch(value):
            return value
        raise ValueError("session_id must start with session- and contain safe id characters")


class WriteSessionOutput(BaseModel):
    scope: str
    session_id: str
    dry_run: bool = False
    affected_paths: List[str] = Field(default_factory=list)
    audit_path: str = "audit.jsonl"


class CrystallizeInput(BaseModel):
    scope: Literal["project", "global"] = "project"
    kind: Literal["semantic", "procedure"] = "semantic"
    id: str
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=50_000)
    reason: str = Field(min_length=1, max_length=500)
    concepts: List[str] = Field(default_factory=list, max_length=50)
    trigger: Optional[str] = Field(default=None, max_length=2_000)
    steps: List[str] = Field(default_factory=list, max_length=100)
    source_kind: str = Field(default="manual", max_length=80)
    source_path: Optional[str] = Field(default=None, max_length=1_000)
    source_id: Optional[str] = Field(default=None, max_length=240)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    strength: float = Field(default=0.7, ge=0.0, le=1.0)
    replace: bool = False
    dry_run: bool = True
    project_root: Optional[str] = None
    global_root: Optional[str] = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if IDENTIFIER_RE.fullmatch(value):
            return value
        raise ValueError("id must be a safe memory id")


class CrystallizeOutput(BaseModel):
    scope: str
    kind: str
    id: str
    dry_run: bool
    affected_paths: List[str] = Field(default_factory=list)
    replaced: bool = False


class IngestSourceInput(BaseModel):
    scope: Literal["project", "global"] = "project"
    source: str = Field(min_length=1, max_length=1_000)
    target_kind: Literal["semantic", "procedure"] = "semantic"
    id: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=240)
    summary: Optional[str] = Field(default=None, max_length=50_000)
    reason: str = Field(min_length=1, max_length=500)
    concepts: List[str] = Field(default_factory=list, max_length=50)
    trigger: Optional[str] = Field(default=None, max_length=2_000)
    steps: List[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    strength: float = Field(default=0.6, ge=0.0, le=1.0)
    conflict_with: Optional[str] = None
    conflict_note: Optional[str] = Field(default=None, max_length=10_000)
    dry_run: bool = True
    project_root: Optional[str] = None
    global_root: Optional[str] = None

    @field_validator("id", "conflict_with")
    @classmethod
    def validate_optional_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if IDENTIFIER_RE.fullmatch(value):
            return value
        raise ValueError("id fields must be safe memory ids")


class IngestSourceOutput(BaseModel):
    scope: str
    source_path: str
    source_sha256: str
    source_bytes: int
    dry_run: bool
    affected_paths: List[str] = Field(default_factory=list)


class ForgetInput(BaseModel):
    scope: Literal["project", "global"] = "project"
    kind: Literal["semantic", "procedure", "session", "episode"]
    identifier: str
    reason: str = Field(min_length=1, max_length=500)
    dry_run: bool = True
    project_root: Optional[str] = None
    global_root: Optional[str] = None

    @field_validator("identifier")
    @classmethod
    def validate_forget_identifier(cls, value: str) -> str:
        if DATE_RE.fullmatch(value) or SESSION_RE.fullmatch(value) or IDENTIFIER_RE.fullmatch(value):
            return value
        raise ValueError("identifier must be a memory id, session id, or YYYY-MM-DD date")


class ForgetOutput(BaseModel):
    scope: str
    kind: str
    identifier: str
    dry_run: bool
    existed: bool
    deleted: bool
    affected_paths: List[str] = Field(default_factory=list)
    audit_path: str = "audit.jsonl"
