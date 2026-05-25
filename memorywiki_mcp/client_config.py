"""Generate safe read-mostly MCP client configuration for MemoryWiki."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from memory_system.config import default_memory_timezone

DEFAULT_SERVER_NAME = "memorywiki-memory"
MAX_CONFIG_BYTES = 2_000_000


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _as_abs(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _as_abs_command(path: str | Path) -> str:
    return os.path.abspath(os.path.expanduser(str(path)))


def build_server_config(
    *,
    repo_root: str | Path | None = None,
    python: str | Path | None = None,
    project_root: str | Path | None = None,
    global_root: str | Path | None = None,
    write_enabled: bool = False,
    global_write_enabled: bool = False,
    allow_root_override: bool = False,
) -> dict[str, Any]:
    """Return a stdio MCP server config with MemoryWiki' safe read-only defaults."""
    root = Path(repo_root).expanduser() if repo_root else _repo_root()
    root = root.resolve()
    command = _as_abs_command(python) if python else sys.executable
    env = {
        "PYTHONPATH": str(root),
        "MEMORY_BACKEND": "local",
        "MEMORY_PROJECT_ROOT": _as_abs(project_root or root / ".agent_memory" / "project"),
        "MEMORY_GLOBAL_ROOT": _as_abs(global_root or Path.home() / ".agent_memory" / "global"),
        "MEMORY_TIMEZONE": os.getenv("MEMORY_TIMEZONE", default_memory_timezone()),
    }
    if write_enabled:
        env["MEMORY_MCP_WRITE_ENABLED"] = "true"
    if global_write_enabled:
        env["MEMORY_GLOBAL_WRITE_ENABLED"] = "true"
    if allow_root_override:
        env["MEMORY_MCP_ALLOW_ROOT_OVERRIDE"] = "true"
    return {
        "command": command,
        "args": ["-m", "memorywiki_mcp", "--transport", "stdio"],
        "cwd": str(root),
        "env": env,
    }


def build_mcp_json(
    *,
    server_name: str = DEFAULT_SERVER_NAME,
    **kwargs: Any,
) -> dict[str, Any]:
    return {"mcpServers": {server_name: build_server_config(**kwargs)}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a .mcp.json snippet for the MemoryWiki MCP server."
    )
    parser.add_argument("--server-name", default=DEFAULT_SERVER_NAME)
    parser.add_argument("--repo-root", default=str(_repo_root()))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--project-root")
    parser.add_argument("--global-root")
    parser.add_argument("--write-enabled", action="store_true")
    parser.add_argument("--global-write-enabled", action="store_true")
    parser.add_argument("--allow-root-override", action="store_true")
    parser.add_argument("--output", help="Write config JSON to this path instead of stdout.")
    return parser


def _assert_no_symlink_output_parent(path: Path) -> None:
    cursor = path.parent
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError(f"MCP config output parent may not be a symlink: {cursor}")
    for ancestor in cursor.parents:
        if ancestor.exists() and ancestor.is_symlink():
            raise ValueError(f"MCP config output parent may not be below a symlink: {ancestor}")


def _write_text_no_follow(path: Path, text: str) -> None:
    if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ValueError(f"MCP config output exceeds safe size limit: {path}")
    if path.exists() and path.is_symlink():
        raise ValueError(f"MCP config output may not be a symlink: {path}")
    _assert_no_symlink_output_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        if path.is_symlink():
            raise ValueError(f"MCP config output may not be a symlink: {path}")
        raise
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_mcp_json(
        server_name=args.server_name,
        repo_root=args.repo_root,
        python=args.python,
        project_root=args.project_root,
        global_root=args.global_root,
        write_enabled=args.write_enabled,
        global_write_enabled=args.global_write_enabled,
        allow_root_override=args.allow_root_override,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        path = Path(args.output).expanduser()
        try:
            _write_text_no_follow(path, text)
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
