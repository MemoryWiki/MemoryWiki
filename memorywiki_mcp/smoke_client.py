from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from memorywiki_mcp.client_config import build_server_config
from memorywiki_mcp.server import TOOL_NAMES


def _structured(result: Any) -> dict[str, Any]:
    payload = getattr(result, "structuredContent", None)
    if isinstance(payload, dict):
        return payload
    content = getattr(result, "content", None) or []
    if content and getattr(content[0], "text", None):
        return json.loads(content[0].text)
    return {}


async def _call_readonly(session: Any, query: str) -> dict[str, Any]:
    tools = await session.list_tools()
    names = [tool.name for tool in tools.tools]
    missing = sorted(set(TOOL_NAMES) - set(names))
    if missing:
        raise RuntimeError("Missing MemoryWiki MCP tools: %s" % ", ".join(missing))

    index = await session.call_tool("memorywiki_index_maintain", {"input": {"scope": "all"}})
    recall = await session.call_tool(
        "memorywiki_recall",
        {
            "input": {
                "query": query,
                "scope": "all",
                "strategy": "hybrid",
                "limit": 5,
                "token_budget": 800,
                "explain_score": True,
            }
        },
    )
    denied_write = await session.call_tool(
        "memorywiki_write_session",
        {
            "input": {
                "summary": "This write should be denied by the read-only MCP smoke test.",
                "reason": "verify default MCP write gate",
            }
        },
    )
    return {
        "tools": names,
        "index": _structured(index),
        "recall": _structured(recall),
        "default_write_denied": bool(getattr(denied_write, "isError", False)),
    }


async def _call_temp_write_check(
    *,
    python: str,
    repo_root: Path,
) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    with tempfile.TemporaryDirectory(prefix="memorywiki-mcp-dogfood-") as temp:
        temp_root = Path(temp)
        project_root = temp_root / "project"
        global_root = temp_root / "global"
        sources = project_root / "sources"
        sources.mkdir(parents=True)
        (sources / "dogfood.md").write_text(
            "MemoryWiki MCP dogfood source with SHA256 provenance.",
            encoding="utf-8",
        )
        config = build_server_config(
            repo_root=repo_root,
            python=python,
            project_root=project_root,
            global_root=global_root,
            write_enabled=True,
            allow_root_override=False,
        )
        env = dict(os.environ)
        env.update(config["env"])
        params = StdioServerParameters(
            command=config["command"],
            args=config["args"],
            env=env,
            cwd=config["cwd"],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                write_session = await session.call_tool(
                    "memorywiki_write_session",
                    {
                        "input": {
                            "summary": "MCP dogfood writes only to a temporary project root.",
                            "reason": "verify gated temporary MCP write",
                            "keypoints": ["write gate enabled for temp project"],
                            "actions": ["saved temp session"],
                        }
                    },
                )
                ingest_dry_run = await session.call_tool(
                    "memorywiki_ingest_source",
                    {
                        "input": {
                            "source": "dogfood.md",
                            "id": "mcp-dogfood-source",
                            "title": "MCP Dogfood Source",
                            "summary": "Source ingest dry-run/apply path works through MCP.",
                            "reason": "verify MCP source ingest",
                        }
                    },
                )
                ingest_apply = await session.call_tool(
                    "memorywiki_ingest_source",
                    {
                        "input": {
                            "source": "dogfood.md",
                            "id": "mcp-dogfood-source",
                            "title": "MCP Dogfood Source",
                            "summary": "Source ingest dry-run/apply path works through MCP.",
                            "reason": "verify MCP source ingest",
                            "dry_run": False,
                        }
                    },
                )
                global_denied = await session.call_tool(
                    "memorywiki_write_session",
                    {
                        "input": {
                            "scope": "global",
                            "summary": "This global write should be denied.",
                            "reason": "verify global write gate",
                        }
                    },
                )
        return {
            "write_session": _structured(write_session),
            "ingest_dry_run": _structured(ingest_dry_run),
            "ingest_apply": _structured(ingest_apply),
            "global_write_denied": bool(getattr(global_denied, "isError", False)),
        }


async def run_smoke(
    *,
    python: str,
    repo_root: Path,
    project_root: Path,
    global_root: Path,
    query: str,
    temp_write_check: bool,
) -> dict[str, Any]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install MCP support first: pip install -e '.[mcp]'") from exc

    config = build_server_config(
        repo_root=repo_root,
        python=python,
        project_root=project_root,
        global_root=global_root,
    )
    env = dict(os.environ)
    env.update(config["env"])
    params = StdioServerParameters(
        command=config["command"],
        args=config["args"],
        env=env,
        cwd=config["cwd"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            readonly = await _call_readonly(session, query)
    payload = {"readonly": readonly}
    if temp_write_check:
        payload["temp_write_check"] = await _call_temp_write_check(
            python=python,
            repo_root=repo_root,
        )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dogfood the MemoryWiki MCP server through a real MCP client.")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
    )
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--query", default="MemoryWiki MCP retrieval enhancement")
    parser.add_argument("--temp-write-check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = asyncio.run(
            run_smoke(
                python=args.python,
                repo_root=Path(args.repo_root).expanduser().resolve(),
                project_root=Path(args.project_root).expanduser().resolve(),
                global_root=Path(args.global_root).expanduser().resolve(),
                query=args.query,
                temp_write_check=args.temp_write_check,
            )
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
