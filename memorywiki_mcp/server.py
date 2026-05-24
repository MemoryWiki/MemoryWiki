from __future__ import annotations

import os
from ipaddress import ip_address

from memorywiki_mcp.schema import (
    CrystallizeInput,
    CrystallizeOutput,
    ForgetInput,
    ForgetOutput,
    IndexMaintainInput,
    IndexMaintainOutput,
    IngestSourceInput,
    IngestSourceOutput,
    ListInput,
    ListOutput,
    ReadMemoryInput,
    ReadMemoryOutput,
    RecallInput,
    RecallOutput,
    WriteSessionInput,
    WriteSessionOutput,
)
from memorywiki_mcp.tools import memorywiki_crystallize as run_crystallize
from memorywiki_mcp.tools import memorywiki_forget as run_forget
from memorywiki_mcp.tools import memorywiki_ingest_source as run_ingest_source
from memorywiki_mcp.tools import memorywiki_index_maintain as run_index_maintain
from memorywiki_mcp.tools import memorywiki_list as run_list
from memorywiki_mcp.tools import memorywiki_read_memory as run_read_memory
from memorywiki_mcp.tools import memorywiki_recall as run_recall
from memorywiki_mcp.tools import memorywiki_write_session as run_write_session


TOOL_NAMES = (
    "memorywiki_recall",
    "memorywiki_list",
    "memorywiki_read_memory",
    "memorywiki_index_maintain",
    "memorywiki_write_session",
    "memorywiki_crystallize",
    "memorywiki_ingest_source",
    "memorywiki_forget",
)
VALID_BACKENDS = {"local", "openai"}


def tool_specs() -> dict[str, dict]:
    return {
        "memorywiki_recall": {
            "read_only": True,
            "write_gated": "refresh_index_if_needed",
            "description": "Hybrid recall over project/global MemoryWiki memory.",
        },
        "memorywiki_list": {
            "read_only": True,
            "write_gated": False,
            "description": "List MemoryWiki memories by scope, kind, or concept.",
        },
        "memorywiki_read_memory": {
            "read_only": True,
            "write_gated": False,
            "description": "Read one MemoryWiki memory item or hot file with sanitized output.",
        },
        "memorywiki_index_maintain": {
            "read_only": "when write=false",
            "write_gated": True,
            "description": "Dry-run or explicitly rebuild MemoryWiki retrieval sidecars.",
        },
        "memorywiki_write_session": {
            "read_only": False,
            "write_gated": True,
            "description": "Explicitly save a session summary into MemoryWiki.",
        },
        "memorywiki_crystallize": {
            "read_only": "when dry_run=true",
            "write_gated": "when dry_run=false",
            "description": "Crystallize an approved answer into semantic/procedural memory.",
        },
        "memorywiki_ingest_source": {
            "read_only": "when dry_run=true",
            "write_gated": "when dry_run=false",
            "description": "Ingest one read-only sources/ document with SHA256 provenance.",
        },
        "memorywiki_forget": {
            "read_only": "when dry_run=true",
            "write_gated": "when dry_run=false",
            "description": "Dry-run or apply audited memory deletion.",
        },
    }


def validate_backend() -> str:
    backend = os.getenv("MEMORY_BACKEND", "local").strip().lower() or "local"
    if backend not in VALID_BACKENDS:
        raise ValueError("MEMORY_BACKEND must be one of local, openai")
    return backend


def create_server():
    validate_backend()
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Install the MCP extra with Python 3.10+: pip install -e '.[mcp]'"
        ) from exc

    mcp = FastMCP("MemoryWiki Memory", json_response=True)

    @mcp.tool()
    def memorywiki_recall(input: RecallInput) -> RecallOutput:
        """Hybrid recall over local MemoryWiki memory with warnings and provenance."""
        return run_recall(input)

    @mcp.tool()
    def memorywiki_list(input: ListInput) -> ListOutput:
        """List MemoryWiki memories by scope, kind, or concept."""
        return run_list(input)

    @mcp.tool()
    def memorywiki_read_memory(input: ReadMemoryInput) -> ReadMemoryOutput:
        """Read a specific MemoryWiki memory item or hot file."""
        return run_read_memory(input)

    @mcp.tool()
    def memorywiki_index_maintain(input: IndexMaintainInput) -> IndexMaintainOutput:
        """Check or explicitly rebuild retrieval sidecar indexes."""
        return run_index_maintain(input)

    @mcp.tool()
    def memorywiki_write_session(input: WriteSessionInput) -> WriteSessionOutput:
        """Save an explicit MemoryWiki session summary. Requires MCP write gates."""
        return run_write_session(input)

    @mcp.tool()
    def memorywiki_crystallize(input: CrystallizeInput) -> CrystallizeOutput:
        """Crystallize approved content into semantic/procedural memory."""
        return run_crystallize(input)

    @mcp.tool()
    def memorywiki_ingest_source(input: IngestSourceInput) -> IngestSourceOutput:
        """Dry-run or apply source ingest from the memory root sources/ sandbox."""
        return run_ingest_source(input)

    @mcp.tool()
    def memorywiki_forget(input: ForgetInput) -> ForgetOutput:
        """Dry-run or apply an audited memory deletion."""
        return run_forget(input)

    return mcp


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _allow_non_loopback_http() -> bool:
    return os.getenv("MEMORY_MCP_ALLOW_HTTP_NON_LOOPBACK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run_server(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    if transport == "streamable-http":
        if not _is_loopback_host(host) and not _allow_non_loopback_http():
            raise ValueError(
                "streamable-http refuses non-loopback host %s; use stdio or set "
                "MEMORY_MCP_ALLOW_HTTP_NON_LOOPBACK=true explicitly" % host
            )
        os.environ.setdefault("FASTMCP_HOST", host)
        os.environ.setdefault("FASTMCP_PORT", str(port))
    server = create_server()
    server.run(transport=transport)
