from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from memorywiki_mcp.schema import (
    CrystallizeInput,
    CrystallizeOutput,
    ContextInput,
    ContextOutput,
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
from memorywiki_mcp.server import TOOL_NAMES, tool_specs

SCHEMA = "memorywiki-mcp-contract-v1"
INPUT_MODELS: dict[str, type[BaseModel]] = {
    "memorywiki_recall": RecallInput,
    "memorywiki_context": ContextInput,
    "memorywiki_list": ListInput,
    "memorywiki_read_memory": ReadMemoryInput,
    "memorywiki_index_maintain": IndexMaintainInput,
    "memorywiki_write_session": WriteSessionInput,
    "memorywiki_crystallize": CrystallizeInput,
    "memorywiki_ingest_source": IngestSourceInput,
    "memorywiki_forget": ForgetInput,
}
OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "memorywiki_recall": RecallOutput,
    "memorywiki_context": ContextOutput,
    "memorywiki_list": ListOutput,
    "memorywiki_read_memory": ReadMemoryOutput,
    "memorywiki_index_maintain": IndexMaintainOutput,
    "memorywiki_write_session": WriteSessionOutput,
    "memorywiki_crystallize": CrystallizeOutput,
    "memorywiki_ingest_source": IngestSourceOutput,
    "memorywiki_forget": ForgetOutput,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _model_defaults(model: type[Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if field.is_required():
            continue
        default = field.default
        if str(default) != "PydanticUndefined":
            defaults[name] = default
    return defaults


def _body(now: str | None = None) -> dict[str, Any]:
    specs = tool_specs()
    tools = []
    for name in TOOL_NAMES:
        input_model = INPUT_MODELS[name]
        output_model = OUTPUT_MODELS[name]
        spec = specs[name]
        tools.append(
            {
                "name": name,
                "description": spec["description"],
                "read_only": spec["read_only"],
                "write_gated": spec["write_gated"],
                "input_model": input_model.__name__,
                "output_model": output_model.__name__,
                "input_schema": input_model.model_json_schema(),
                "output_schema": output_model.model_json_schema(),
                "defaults": _model_defaults(input_model),
            }
        )
    return {
        "schema": SCHEMA,
        "generated_at": now or _now(),
        "transport": ["stdio", "streamable-http"],
        "invocation": {
            "argument": "input",
            "shape": {"input": "<tool input object>"},
            "note": "MemoryWiki MCP v1 exposes one top-level tool argument named input.",
        },
        "write_gates": {
            "project": ["MEMORY_MCP_WRITE_ENABLED=true"],
            "global": ["MEMORY_MCP_WRITE_ENABLED=true", "MEMORY_GLOBAL_WRITE_ENABLED=true"],
            "root_override": ["MEMORY_MCP_ALLOW_ROOT_OVERRIDE=true"],
        },
        "tools": tools,
    }


def _fingerprint(payload: dict[str, Any]) -> str:
    stable = dict(payload)
    stable.pop("generated_at", None)
    stable.pop("contract_sha256", None)
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_contract(now: str | None = None) -> dict[str, Any]:
    payload = _body(now=now)
    payload["contract_sha256"] = _fingerprint(payload)
    return payload


def _write_json_no_follow(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError(f"MCP contract output may not be a symlink: {path}")
    _assert_no_symlink_output_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _assert_no_symlink_output_parent(path: Path) -> None:
    parent = path.parent
    cursor = parent
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.exists() and cursor.is_symlink():
        raise ValueError(f"MCP contract output parent may not be a symlink: {cursor}")
    for ancestor in [parent] + list(parent.parents):
        if ancestor.exists() and ancestor.is_symlink():
            raise ValueError(
                f"MCP contract output parent may not be below a symlink: {ancestor}"
            )


def write_contract(out: str | Path, now: str | None = None) -> Path:
    path = Path(out).expanduser()
    _write_json_no_follow(path, build_contract(now=now))
    return path


def verify_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path).expanduser()
    if not contract_path.exists() or contract_path.is_symlink() or not contract_path.is_file():
        raise ValueError(f"MCP contract must be a real file: {contract_path}")
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"MCP contract must be a JSON object: {contract_path}")
    current = build_contract(now=payload.get("generated_at"))
    stored_fingerprint = _fingerprint(payload)
    checks = [
        {"target": "schema", "status": "ok" if payload.get("schema") == SCHEMA else "changed"},
        {
            "target": "tools",
            "status": "ok"
            if [item.get("name") for item in payload.get("tools", [])] == list(TOOL_NAMES)
            else "changed",
        },
        {
            "target": "stored_contract_sha256",
            "status": "ok"
            if payload.get("contract_sha256") == stored_fingerprint
            else "changed",
        },
        {
            "target": "contract_sha256",
            "status": "ok"
            if payload.get("contract_sha256") == current.get("contract_sha256")
            else "changed",
        },
    ]
    return {
        "status": "ok" if all(item["status"] == "ok" for item in checks) else "fail",
        "contract_path": str(contract_path),
        "checks": checks,
    }


def render_human(payload: dict[str, Any]) -> str:
    if payload.get("schema") == SCHEMA:
        return "# MemoryWiki MCP Contract\n\nTools: {}\nDigest: {}\n".format(
            ", ".join(item["name"] for item in payload["tools"]),
            payload["contract_sha256"],
        )
    lines = ["# MemoryWiki MCP Contract Verify", "", "Status: {}".format(payload["status"]), ""]
    for check in payload["checks"]:
        lines.append("- [{status}] {target}".format(**check))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate or verify the MemoryWiki MCP v1 contract.")
    parser.add_argument("--out")
    parser.add_argument("--verify")
    parser.add_argument("--now")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify:
            payload = verify_contract(args.verify)
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else render_human(payload)
            print(text, end="")
            return 0 if payload["status"] == "ok" else 1
        if args.out:
            path = write_contract(args.out, now=args.now)
            payload = {"contract_path": str(path), "contract": json.loads(path.read_text(encoding="utf-8"))}
        else:
            payload = build_contract(now=args.now)
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else render_human(payload.get("contract", payload))
        print(text, end="")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
