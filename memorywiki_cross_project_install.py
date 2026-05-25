from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from memorywiki_mcp.client_config import build_mcp_json
from project_agents import render_agents_md

SERVER_NAME = "memorywiki-memory"
AGENTS_BLOCK_START = "<!-- BEGIN MemoryWiki MCP BRIDGE -->"
AGENTS_BLOCK_END = "<!-- END MemoryWiki MCP BRIDGE -->"


def _memory_home() -> Path:
    return Path(__file__).resolve().parent


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _assert_safe_project_root(project_root: str | Path) -> Path:
    root = Path(project_root).expanduser()
    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise ValueError(f"Project root must be a real directory: {root}")
    for ancestor in root.parents:
        if ancestor.exists() and ancestor.is_symlink():
            raise ValueError(f"Project root may not be below a symlink: {ancestor}")
    return root.resolve()


def _read_json_no_follow(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"MCP config may not be a symlink: {path}")
    if not path.exists():
        return {}
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        raw = os.read(fd, min(os.fstat(fd).st_size, 2_000_000)).decode("utf-8")
    finally:
        os.close(fd)
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"MCP config is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"MCP config must be a JSON object: {path}")
    return payload


def _write_text_no_follow(path: Path, text: str, mode: int = 0o644) -> None:
    if path.is_symlink():
        raise ValueError(f"Managed install target may not be a symlink: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, mode)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def render_managed_agents_block(memory_home: str | Path, python: str | Path | None = None) -> str:
    memory_home_text = str(Path(memory_home).expanduser())
    python_text = str(python or sys.executable)
    python_shell = shlex.quote(python_text)
    return """{start}
## MemoryWiki MCP Memory Bridge

- Prefer the local `memorywiki-memory` MCP server for startup context when available.
- Use `memorywiki_index_maintain(write=false)`, `memorywiki_recall(strategy="hybrid")`, and bounded `memorywiki_read_memory` before falling back to CLI reads.
- Keep MCP read-only by default. Do not set `MEMORY_MCP_WRITE_ENABLED` unless the user explicitly asks to save, update, or forget memory.
- Do not set `MEMORY_GLOBAL_WRITE_ENABLED` unless the user explicitly asks for a global write.
- Run `memorywiki_quality_report.py` in read-only mode before longer MemoryWiki maintenance work.
- Run `memorywiki_knowledge_ops.py --period daily|weekly` as the V8 read-mostly operator console across knowledge formation, cross-project rollout, retrieval quality, release discipline, and operator UX. It uses `.mcp.json` only for trusted MemoryWiki MCP Python locations or an explicit `--python`, shows adoption readiness and top next actions, and keeps writes behind explicit approval; `--stage-candidates` writes pending proposals, not semantic/procedural memory.
- Run `memorywiki_ops_dashboard.py --period daily|weekly` for a read-only operating snapshot with quality, project matrix, release baseline, local embedding readiness, and `Recommended Actions` across memory ops, knowledge formation, retrieval quality, cross-project reliability, and release discipline.
- Use `memory_health.py` directly only when you need the lower-level health issue list.
- Run `memory_lifecycle.py` as a dry-run before release or applying MemoryWiki review items.
- Use `memory_feedback.py` only for explicit recall feedback, and `memory_crystallize_candidates.py --write` only for an explicit pending queue.
- Use `memory_review.py` before applying pending MemoryWiki items; `--apply-candidate <id>` is dry-run unless `--write` is explicit and applies exactly one candidate. `--fill-golden-candidate`, `--reject-golden-candidate`, and `--promote-golden-candidate` each act on exactly one pending eval candidate only when `--write` is explicit and append audit rows.
- If this project owns MemoryWiki releases, run `memorywiki_release_check.py --mcp-contract ... --skill-archive ... --skill-source-dir ... --manifest-out ...`, `memorywiki_mcp_contract.py --verify ...`, `memorywiki_restore_check.py`, and `memorywiki_release_manifest.py --verify ...` before committing. Release checks fail on dirty scoped MemoryWiki files unless `--allow-dirty` is explicit and release manifests include retrieval baseline comparison.
- Diagnose the bridge with:

```bash
if [ -z "${{MEMORYWIKI_MCP_PYTHON:-}}" ]; then
  MCP_PYTHON={python_shell}
else
  MCP_PYTHON="$MEMORYWIKI_MCP_PYTHON"
fi
PYTHONPATH={memory_home!r} \\
"$MCP_PYTHON" {doctor!r} \\
  --python "$MCP_PYTHON" \\
  --project-root "$(pwd)/.agent_memory/project" \\
  --global-root "${{MEMORY_GLOBAL_ROOT:-$HOME/.agent_memory/global}}" \\
  --config "$(pwd)/.mcp.json"
```

- Check retrieval quality with:

```bash
if [ -z "${{MEMORYWIKI_MCP_PYTHON:-}}" ]; then
  MCP_PYTHON={python_shell}
else
  MCP_PYTHON="$MEMORYWIKI_MCP_PYTHON"
fi
PYTHONPATH={memory_home!r} \\
"$MCP_PYTHON" {eval!r} \\
  --project-root "$(pwd)/.agent_memory/project" \\
  --global-root "${{MEMORY_GLOBAL_ROOT:-$HOME/.agent_memory/global}}"
```

- Check unified MemoryWiki quality with:

```bash
if [ -z "${{MEMORYWIKI_MCP_PYTHON:-}}" ]; then
  MCP_PYTHON={python_shell}
else
  MCP_PYTHON="$MEMORYWIKI_MCP_PYTHON"
fi
PYTHONPATH={memory_home!r} \\
"$MCP_PYTHON" {quality!r} \\
  --project-root "$(pwd)/.agent_memory/project" \\
  --global-root "${{MEMORY_GLOBAL_ROOT:-$HOME/.agent_memory/global}}" \\
  --scope all \\
  --skip-golden
```

- Render the read-only MemoryWiki knowledge ops loop:

```bash
if [ -z "${{MEMORYWIKI_MCP_PYTHON:-}}" ]; then
  MCP_PYTHON={python_shell}
else
  MCP_PYTHON="$MEMORYWIKI_MCP_PYTHON"
fi
PYTHONPATH={memory_home!r} \\
"$MCP_PYTHON" {knowledge_ops!r} \\
  --project-root "$(pwd)/.agent_memory/project" \\
  --global-root "${{MEMORY_GLOBAL_ROOT:-$HOME/.agent_memory/global}}" \\
  --mcp-config "$(pwd)/.mcp.json" \\
  --period daily
```

Use its `Top Next Actions` and adoption readiness summary before drilling into lower-level reports.

- Render the read-only MemoryWiki ops dashboard and follow its `Recommended Actions` section:

```bash
if [ -z "${{MEMORYWIKI_MCP_PYTHON:-}}" ]; then
  MCP_PYTHON={python_shell}
else
  MCP_PYTHON="$MEMORYWIKI_MCP_PYTHON"
fi
PYTHONPATH={memory_home!r} \\
"$MCP_PYTHON" {dashboard!r} \\
  --project-root "$(pwd)/.agent_memory/project" \\
  --global-root "${{MEMORY_GLOBAL_ROOT:-$HOME/.agent_memory/global}}" \\
  --mcp-config "$(pwd)/.mcp.json" \\
  --period daily
```

- Check ledger lifecycle with:

```bash
if [ -z "${{MEMORYWIKI_MCP_PYTHON:-}}" ]; then
  MCP_PYTHON={python_shell}
else
  MCP_PYTHON="$MEMORYWIKI_MCP_PYTHON"
fi
PYTHONPATH={memory_home!r} \\
"$MCP_PYTHON" {lifecycle!r} \\
  --project-root "$(pwd)/.agent_memory/project" \\
  --global-root "${{MEMORY_GLOBAL_ROOT:-$HOME/.agent_memory/global}}" \\
  --scope all
```
{end}""".format(
        start=AGENTS_BLOCK_START,
        end=AGENTS_BLOCK_END,
        memory_home=memory_home_text,
        python_shell=python_shell,
        doctor=str(Path(memory_home_text) / "memorywiki_mcp_doctor.py"),
        eval=str(Path(memory_home_text) / "retrieval_golden_eval.py"),
        quality=str(Path(memory_home_text) / "memorywiki_quality_report.py"),
        knowledge_ops=str(Path(memory_home_text) / "memorywiki_knowledge_ops.py"),
        dashboard=str(Path(memory_home_text) / "memorywiki_ops_dashboard.py"),
        lifecycle=str(Path(memory_home_text) / "memory_lifecycle.py"),
    )


def merge_managed_agents_block(
    existing: str,
    memory_home: str | Path,
    python: str | Path | None = None,
) -> str:
    block = render_managed_agents_block(memory_home, python=python)
    if AGENTS_BLOCK_START in existing and AGENTS_BLOCK_END in existing:
        prefix, rest = existing.split(AGENTS_BLOCK_START, 1)
        _, suffix = rest.split(AGENTS_BLOCK_END, 1)
        return prefix.rstrip() + "\n\n" + block + suffix.rstrip() + "\n"
    return existing.rstrip() + "\n\n" + block + "\n"


def _merge_mcp_config(existing: dict[str, Any], server_config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    servers = merged.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(".mcp.json mcpServers must be an object")
    servers = dict(servers)
    servers[SERVER_NAME] = server_config["mcpServers"][SERVER_NAME]
    merged["mcpServers"] = servers
    return merged


def install_cross_project_memory(
    *,
    project_root: str | Path,
    memory_system_home: str | Path | None = None,
    python: str | Path | None = None,
    global_root: str | Path | None = None,
    write: bool = False,
    force_agents: bool = False,
    update_existing_agents: bool = False,
    skip_agents: bool = False,
    skip_mcp: bool = False,
) -> dict[str, Any]:
    root = _assert_safe_project_root(project_root)
    memory_home = Path(memory_system_home).expanduser() if memory_system_home else _memory_home()
    repo_root = memory_home.parent
    python_path = str(python or sys.executable)
    project_memory_root = root / ".agent_memory" / "project"
    global_memory_root = Path(global_root).expanduser() if global_root else Path.home() / ".agent_memory" / "global"
    actions: list[dict[str, Any]] = []

    if not skip_agents:
        target = root / "AGENTS.md"
        status = "would_write"
        if target.is_symlink():
            raise ValueError(f"AGENTS.md may not be a symlink: {target}")
        if target.exists() and update_existing_agents:
            status = "would_update"
        elif target.exists() and not force_agents:
            status = "skipped_exists"
        actions.append({"path": "AGENTS.md", "status": status})
        if write and status != "skipped_exists":
            if status == "would_update":
                text = merge_managed_agents_block(
                    target.read_text(encoding="utf-8"),
                    memory_home,
                    python=python_path,
                )
            else:
                text = render_agents_md(root.name, memory_home, mcp_python=python_path)
            _write_text_no_follow(target, text)
            actions[-1]["status"] = "updated" if status == "would_update" else "written"

    if not skip_mcp:
        target = root / ".mcp.json"
        config = build_mcp_json(
            repo_root=repo_root,
            python=python_path,
            project_root=project_memory_root,
            global_root=global_memory_root,
        )
        existing = _read_json_no_follow(target)
        merged = _merge_mcp_config(existing, config)
        actions.append({"path": ".mcp.json", "status": "would_write"})
        if write:
            _write_text_no_follow(
                target,
                json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
            )
            actions[-1]["status"] = "written"

    return {
        "dry_run": not write,
        "project_root": str(root),
        "memory_system_home": str(memory_home),
        "python": python_path,
        "global_root": str(global_memory_root),
        "actions": actions,
    }


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Cross-Project Install",
        "",
        "Mode: %s" % ("dry-run" if payload["dry_run"] else "write"),
        "Project: {}".format(payload["project_root"]),
        "Memory system: {}".format(payload["memory_system_home"]),
        "",
    ]
    for action in payload["actions"]:
        lines.append("- {}: {}".format(action["path"], action["status"]))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install MemoryWiki read-only MCP and AGENTS startup into another project."
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--memory-system-home", default=str(_memory_home()))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--force-agents", action="store_true")
    parser.add_argument(
        "--update-existing-agents",
        action="store_true",
        help="Append or refresh a managed MemoryWiki MCP bridge block in existing AGENTS.md.",
    )
    parser.add_argument("--skip-agents", action="store_true")
    parser.add_argument("--skip-mcp", action="store_true")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = install_cross_project_memory(
            project_root=args.project_root,
            memory_system_home=args.memory_system_home,
            python=args.python,
            global_root=args.global_root,
            write=args.write,
            force_agents=args.force_agents,
            update_existing_agents=args.update_existing_agents,
            skip_agents=args.skip_agents,
            skip_mcp=args.skip_mcp,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
