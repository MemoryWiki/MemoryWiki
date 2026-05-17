from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from memory_index_maintain import maintain_indexes


SERVER_NAME = "memorywiki-memory"
WARN_GATES = (
    "MEMORY_MCP_WRITE_ENABLED",
    "MEMORY_GLOBAL_WRITE_ENABLED",
    "MEMORY_MCP_ALLOW_ROOT_OVERRIDE",
)
PYTHON_CHECK_TIMEOUT_SECONDS = 10


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _check(status: str, messages: list[str], **extra: Any) -> dict[str, Any]:
    return {"status": status, "messages": messages, **extra}


def _overall(checks: dict[str, dict[str, Any]]) -> str:
    statuses = {item["status"] for item in checks.values()}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _load_mcp_config(path: Path) -> dict[str, Any] | None:
    if path.is_symlink():
        raise ValueError("MCP config may not be a symlink: %s" % path)
    if not path.exists():
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        text = os.read(fd, min(os.fstat(fd).st_size, 2_000_000)).decode("utf-8")
    finally:
        os.close(fd)
    payload = json.loads(text or "{}")
    if not isinstance(payload, dict):
        raise ValueError("MCP config must be a JSON object: %s" % path)
    return payload


def _check_python(
    python: str,
    repo_root: Path,
    timeout_seconds: float = PYTHON_CHECK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    expanded = os.path.expanduser(python)
    has_path_separator = os.sep in expanded or (os.altsep is not None and os.altsep in expanded)
    resolved_command = shutil.which(expanded) if not has_path_separator else None
    path = Path(resolved_command or expanded)
    if not path.exists():
        return _check("warn", ["Python command was not found: %s" % python])
    if not path.is_file():
        return _check("warn", ["Python command is not a file: %s" % python])
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    try:
        result = subprocess.run(
            [str(path), "-c", "import memorywiki_mcp; import mcp"],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _check(
            "warn",
            ["Python import check timed out after %.1f seconds: %s" % (timeout_seconds, python)],
        )
    if result.returncode != 0:
        return _check(
            "warn",
            ["Python exists but cannot import both memorywiki_mcp and mcp."],
            stderr=result.stderr.strip(),
        )
    return _check("ok", ["Python can import memorywiki_mcp and mcp."])


def _check_roots(project_root: Path, global_root: Path) -> dict[str, Any]:
    messages = []
    failures = []
    warnings = []
    for label, root in (("project", project_root), ("global", global_root)):
        if root.exists() and root.is_symlink():
            failures.append("%s root is a symlink: %s" % (label, root))
        elif root.exists() and not root.is_dir():
            failures.append("%s root is not a directory: %s" % (label, root))
        elif not root.exists():
            warnings.append("%s root does not exist yet: %s" % (label, root))
        else:
            messages.append("%s root is a real directory: %s" % (label, root))
    if failures:
        return _check("fail", failures + warnings + messages)
    if warnings:
        return _check("warn", warnings + messages)
    return _check("ok", messages)


def _check_config(config_path: Path, project_root: Path, global_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = _load_mcp_config(config_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _check("fail", [str(exc)]), _check("warn", ["Cannot evaluate write gates without a valid MCP config."])
    if payload is None:
        return (
            _check("warn", ["MCP config is missing: %s" % config_path]),
            _check("ok", ["No MCP config write gates found."]),
        )
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict) or SERVER_NAME not in servers:
        return (
            _check("warn", ["MCP config does not define %s." % SERVER_NAME]),
            _check("ok", ["No MemoryWiki MCP write gates found."]),
        )
    server = servers[SERVER_NAME]
    env = server.get("env", {}) if isinstance(server, dict) else {}
    if not isinstance(env, dict):
        return _check("fail", ["%s env must be an object." % SERVER_NAME]), _check("warn", ["Cannot evaluate malformed env."])
    messages = ["MCP config defines %s." % SERVER_NAME]
    expected_project = str(project_root)
    expected_global = str(global_root)
    if env.get("MEMORY_PROJECT_ROOT") != expected_project:
        messages.append("MEMORY_PROJECT_ROOT differs from doctor input.")
    if env.get("MEMORY_GLOBAL_ROOT") != expected_global:
        messages.append("MEMORY_GLOBAL_ROOT differs from doctor input.")
    gate_messages = [
        "%s is enabled in MCP config." % name
        for name in WARN_GATES
        if str(env.get(name, "")).lower() in {"1", "true", "yes", "on"}
    ]
    gate_messages.extend(
        "%s is enabled in current shell." % name
        for name in WARN_GATES
        if str(os.getenv(name, "")).lower() in {"1", "true", "yes", "on"}
    )
    gate_status = "warn" if gate_messages else "ok"
    return _check("ok", messages), _check(gate_status, gate_messages or ["No write/root override gates are enabled."])


def _check_index(project_root: Path, global_root: Path) -> dict[str, Any]:
    try:
        payload = maintain_indexes(
            project_root=project_root,
            global_root=global_root,
            scope="all",
            write=False,
        )
    except Exception as exc:
        return _check("fail", [str(exc)])
    messages = []
    for item in payload["roots"]:
        messages.append("%s index is %s." % (item["scope"], item["status"]))
        messages.extend(item.get("warnings", []))
    return _check("warn" if payload["rebuild_needed"] else "ok", messages, payload=payload)


def run_doctor(
    *,
    repo_root: str | Path,
    python: str | Path,
    project_root: str | Path,
    global_root: str | Path,
    config_path: str | Path,
) -> dict[str, Any]:
    repo = Path(repo_root).expanduser().resolve()
    project = Path(project_root).expanduser()
    global_mem = Path(global_root).expanduser()
    config = Path(config_path).expanduser()
    config_check, gate_check = _check_config(config, project, global_mem)
    checks = {
        "python": _check_python(str(python), repo),
        "mcp_config": config_check,
        "write_gates": gate_check,
        "roots": _check_roots(project, global_mem),
        "index": _check_index(project, global_mem),
    }
    return {
        "status": _overall(checks),
        "repo_root": str(repo),
        "project_root": str(project),
        "global_root": str(global_mem),
        "config_path": str(config),
        "checks": checks,
    }


def render_human(payload: dict[str, Any]) -> str:
    lines = ["# MemoryWiki MCP Doctor", "", "Status: %s" % payload["status"], ""]
    for name, check in payload["checks"].items():
        lines.append("## %s: %s" % (name, check["status"]))
        for message in check.get("messages", []):
            lines.append("- %s" % message)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check MemoryWiki MCP client bridge health.")
    parser.add_argument("--repo-root", default=str(_repo_root()))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--project-root", default=str(Path.cwd() / ".agent_memory" / "project"))
    parser.add_argument("--global-root", default=str(Path.home() / ".agent_memory" / "global"))
    parser.add_argument("--config", default=str(Path.cwd() / ".mcp.json"))
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_doctor(
        repo_root=args.repo_root,
        python=args.python,
        project_root=args.project_root,
        global_root=args.global_root,
        config_path=args.config,
    )
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 1 if payload["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
