from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "memorywiki-memory"
MAX_CONFIG_BYTES = 2_000_000
DEFAULT_TRUSTED_PYTHON_DIRS = (
    Path.home() / ".local" / "share" / "memorywiki-mcp",
    Path.home() / ".local" / "share" / "uv" / "python",
)


def _safe_config_file(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise ValueError(f"MCP config must be a real file: {candidate}")
    if candidate.exists() and not candidate.is_file():
        raise ValueError(f"MCP config must be a real file: {candidate}")
    cursor = candidate.parent
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError(f"MCP config may not be below a symlink: {cursor}")
    for parent in cursor.parents:
        if parent.is_symlink():
            raise ValueError(f"MCP config may not be below a symlink: {parent}")
    return candidate


def _read_json_config(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        size = os.fstat(fd).st_size
        if size > MAX_CONFIG_BYTES:
            raise ValueError(f"MCP config exceeds safe read limit: {path}")
        payload = json.loads(os.read(fd, size).decode("utf-8") or "{}")
    finally:
        os.close(fd)
    if not isinstance(payload, dict):
        raise ValueError(f"MCP config must be a JSON object: {path}")
    return payload


def _looks_like_python(command: str) -> bool:
    if not command:
        return False
    name = Path(command).name.lower()
    return name == "python" or name.startswith("python")


def _trusted_python_dirs() -> list[Path]:
    rows = [Path(item).expanduser() for item in DEFAULT_TRUSTED_PYTHON_DIRS]
    override = os.getenv("MEMORYWIKI_MCP_TRUSTED_PYTHON_DIRS", "")
    for item in override.split(os.pathsep):
        if item.strip():
            rows.append(Path(item).expanduser())
    return rows


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _has_parent_reference(path: Path) -> bool:
    return ".." in path.parts


def _is_trusted_python_command(command: str) -> tuple[bool, str]:
    candidate = Path(command).expanduser()
    if not candidate.is_absolute():
        return False, "MemoryWiki MCP command is not an absolute Python path; using fallback Python."
    if _has_parent_reference(candidate):
        return False, "MemoryWiki MCP command contains parent-directory traversal; using fallback Python."
    if not candidate.exists() or not candidate.is_file():
        return False, "MemoryWiki MCP command does not point to an existing Python file; using fallback Python."
    try:
        resolved_candidate = candidate.resolve(strict=True)
    except OSError:
        return False, "MemoryWiki MCP command could not be resolved safely; using fallback Python."
    explicit = os.getenv("MEMORYWIKI_MCP_PYTHON", "").strip()
    if explicit and resolved_candidate == Path(explicit).expanduser().resolve(strict=False):
        return True, ""
    for root in _trusted_python_dirs():
        resolved_root = root.resolve(strict=False)
        if _is_relative_to(resolved_candidate, resolved_root):
            return True, ""
    return False, "MemoryWiki MCP command is not in a trusted Python directory; using fallback Python."


def resolve_mcp_python(
    *,
    mcp_config: str | Path | None = None,
    fallback: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve the MemoryWiki MCP Python command without executing project config content."""
    fallback_text = str(fallback or sys.executable)
    config_path = _safe_config_file(mcp_config or (Path.cwd() / ".mcp.json"))
    payload = _read_json_config(config_path)
    if payload is None:
        return {
            "python": fallback_text,
            "source": "fallback",
            "mcp_config": str(config_path),
            "warning": "MCP config is missing; using fallback Python.",
        }
    servers = payload.get("mcpServers", {})
    server = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
    if not isinstance(server, dict):
        return {
            "python": fallback_text,
            "source": "fallback",
            "mcp_config": str(config_path),
            "warning": f"MCP config does not define {SERVER_NAME}; using fallback Python.",
        }
    command = str(server.get("command", "")).strip()
    if not _looks_like_python(command):
        return {
            "python": fallback_text,
            "source": "fallback",
            "mcp_config": str(config_path),
            "warning": "MemoryWiki MCP command is not a Python executable name; using fallback Python.",
        }
    trusted, warning = _is_trusted_python_command(command)
    if not trusted:
        return {
            "python": fallback_text,
            "source": "fallback",
            "mcp_config": str(config_path),
            "warning": warning,
        }
    return {
        "python": command,
        "source": "mcp-config",
        "mcp_config": str(config_path),
        "warning": "",
    }
