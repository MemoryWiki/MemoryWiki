from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ChatMessage:
    ts: str
    role: str
    content: str


@dataclass
class TokenUsage:
    ts: str
    model: str
    kind: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass
class SessionSummary:
    ts: str
    session_id: str
    summary: str
    key_points: List[str]
    actions_taken: List[str]
    pending_tasks: List[str]


@dataclass
class SessionMeta:
    id: str
    title: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


@dataclass
class SessionFile:
    id: str
    date: str
    scope: str
    title: str
    keypoints: List[str]
    actions: List[str]
    pending: List[str]
    duration_seconds: Optional[int]
    body: str


@dataclass
class EpisodeFile:
    date: str
    scope: str
    sessions: List[SessionMeta]
    body: str


@dataclass
class SourceRef:
    kind: str
    path: str
    identifier: Optional[str] = None
    excerpt: Optional[str] = None


@dataclass
class SemanticMemory:
    id: str
    scope: str
    title: str
    content: str
    concepts: List[str]
    source_refs: List[SourceRef]
    confidence: float
    strength: float
    last_accessed: Optional[str]
    created_at: str
    updated_at: str
    update_log: List[str] = field(default_factory=list)


@dataclass
class ProceduralMemory:
    id: str
    scope: str
    title: str
    trigger: str
    steps: List[str]
    source_refs: List[SourceRef]
    confidence: float
    strength: float
    last_accessed: Optional[str]
    created_at: str
    updated_at: str


@dataclass
class AuditEntry:
    ts: str
    action: str
    target_kind: str
    target_id: str
    reason: str
    dry_run: bool
    details: Dict[str, Any]


@dataclass
class CompactionResult:
    updated_memory: str
    updated_user: str
    episodic_append: str


@dataclass
class RetrievalHit:
    scope: str
    source: str
    identifier: str
    excerpt: str
    score: int
    deprecated: bool = False
    note: str = ""


@dataclass
class RetrievalResult:
    hits: List[RetrievalHit]


@dataclass
class RecallHit:
    scope: str
    source: str
    identifier: str
    title: str
    excerpt: str
    score: float
    provenance: List[SourceRef]
    tokens: int
    score_explanation: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecallResult:
    query: str
    hits: List[RecallHit]
    tokens_used: int
    truncated: bool
    strategy: str = "live"
    warnings: List[str] = field(default_factory=list)
