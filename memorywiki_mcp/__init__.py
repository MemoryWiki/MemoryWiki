"""MCP v1 wrapper for the local-first MemoryWiki retrieval and gated-write surface."""

from memorywiki_mcp.schema import (
    CrystallizeInput,
    ContextInput,
    ForgetInput,
    IndexMaintainInput,
    IngestSourceInput,
    ReadMemoryInput,
    RecallInput,
    WriteSessionInput,
)
from memorywiki_mcp.tools import (
    memorywiki_context,
    memorywiki_crystallize,
    memorywiki_forget,
    memorywiki_index_maintain,
    memorywiki_ingest_source,
    memorywiki_read_memory,
    memorywiki_recall,
    memorywiki_write_session,
)

__all__ = [
    "CrystallizeInput",
    "ContextInput",
    "ForgetInput",
    "IndexMaintainInput",
    "IngestSourceInput",
    "ReadMemoryInput",
    "RecallInput",
    "WriteSessionInput",
    "memorywiki_context",
    "memorywiki_crystallize",
    "memorywiki_forget",
    "memorywiki_index_maintain",
    "memorywiki_ingest_source",
    "memorywiki_read_memory",
    "memorywiki_recall",
    "memorywiki_write_session",
]
