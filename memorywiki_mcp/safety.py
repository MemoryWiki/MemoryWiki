"""Safety gates and path/input screening for MemoryWiki MCP tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Tuple

from memory_system.sanitizer import neutralize_instruction_text, sanitize_text

PATH_FIELD_HINTS = ("path", "root", "source")
TRUE_VALUES = {"1", "true", "yes", "on"}
MAX_OUTPUT_CHARS = 50_000


def env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUE_VALUES


def _default_project_root() -> Path:
    raw = os.getenv("MEMORY_PROJECT_ROOT")
    return Path(raw).expanduser() if raw else Path.cwd() / ".agent_memory" / "project"


def _default_global_root() -> Path:
    return Path(os.path.expanduser(os.getenv("MEMORY_GLOBAL_ROOT", "~/.agent_memory/global")))


def _same_path(left: Path, right: Path) -> bool:
    return os.path.abspath(os.path.expanduser(str(left))) == os.path.abspath(
        os.path.expanduser(str(right))
    )


def _validate_path_text(field: str, value: str) -> None:
    path = Path(value)
    if "\x00" in value or ".." in path.parts:
        raise ValueError(f"Path-like field is not allowed to escape its root: {field}")


def screen_tool_input(tool_name: str, payload: dict[str, Any]) -> None:
    """Validate MCP-facing inputs before dispatching to MemoryWiki internals."""
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, dict):
            screen_tool_input(tool_name, value)
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    screen_tool_input(tool_name, item)
                elif isinstance(item, str) and len(item) > MAX_OUTPUT_CHARS:
                    raise ValueError(f"String input is too large for {tool_name}: {key}")
            continue
        if not isinstance(value, str):
            continue
        if len(value) > MAX_OUTPUT_CHARS:
            raise ValueError(f"String input is too large for {tool_name}: {key}")
        lowered = key.lower()
        if any(hint in lowered for hint in PATH_FIELD_HINTS):
            _validate_path_text(key, value)


def resolve_project_root(project_root: Optional[str] = None) -> Path:
    default = _default_project_root()
    if not project_root:
        return default.expanduser()
    candidate = Path(project_root).expanduser()
    if not env_enabled("MEMORY_MCP_ALLOW_ROOT_OVERRIDE") and not _same_path(candidate, default):
        raise PermissionError(
            "MCP root override is disabled; set MEMORY_MCP_ALLOW_ROOT_OVERRIDE=true to allow project_root"
        )
    return candidate


def resolve_global_root(global_root: Optional[str] = None) -> Path:
    default = _default_global_root()
    if not global_root:
        return default.expanduser()
    candidate = Path(global_root).expanduser()
    if not env_enabled("MEMORY_MCP_ALLOW_ROOT_OVERRIDE") and not _same_path(candidate, default):
        raise PermissionError(
            "MCP root override is disabled; set MEMORY_MCP_ALLOW_ROOT_OVERRIDE=true to allow global_root"
        )
    return candidate


def require_mcp_write_enabled(scope: str | None = None) -> None:
    if not env_enabled("MEMORY_MCP_WRITE_ENABLED"):
        raise PermissionError(
            "MCP write operation refused; set MEMORY_MCP_WRITE_ENABLED=true to allow this explicit write"
        )
    if scope == "global" and not env_enabled("MEMORY_GLOBAL_WRITE_ENABLED"):
        raise PermissionError(
            "Global MCP write operation refused; set MEMORY_GLOBAL_WRITE_ENABLED=true to allow this explicit global write"
        )


def safe_output_text(text: Optional[str]) -> str:
    return neutralize_instruction_text(sanitize_text(text or ""))


def clipped_output(text: Optional[str], max_chars: int, full: bool = False) -> Tuple[str, bool]:
    clean = safe_output_text(text)
    limit = min(max_chars if not full else max(max_chars, len(clean)), MAX_OUTPUT_CHARS)
    if len(clean) <= limit:
        return clean, False
    return clean[:limit].rstrip() + "...", True


def safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {safe_output_text(str(key)): safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return safe_output_text(str(value))
