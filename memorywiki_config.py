from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from memory_system.config import MemoryConfig
from memory_system.config_file import CONFIG_FILE_NAME, find_config_file, write_default_config


def _config_payload(start: str | Path | None = None) -> dict:
    cfg = MemoryConfig.from_env()
    config_path = find_config_file(start)
    payload = asdict(cfg)
    for key, value in list(payload.items()):
        if isinstance(value, Path):
            payload[key] = str(value)
    payload["config_path"] = str(config_path) if config_path else None
    return payload


def render_human(payload: dict) -> str:
    lines = [
        "# MemoryWiki Config",
        "",
        "Config file: %s" % (payload["config_path"] or "(not found)"),
        "Project root: {}".format(payload["project_storage_root"]),
        "Global root: {}".format(payload["global_storage_root"]),
        "Backend: {}".format(payload["backend"]),
        "Model: {}".format(payload["model"]),
        "Timezone: {}".format(payload["timezone"]),
        "Chat writes: %s" % ("enabled" if payload["chat_write_enabled"] else "disabled"),
        "Global writes: %s" % ("enabled" if payload["global_write_enabled"] else "disabled"),
    ]
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and initialize MemoryWiki configuration.")
    subparsers = parser.add_subparsers(dest="command")

    show = subparsers.add_parser("show", help="Show the effective configuration.")
    show.add_argument("--format", choices=("human", "json"), default="human")

    validate = subparsers.add_parser("validate", help="Validate the effective configuration.")
    validate.add_argument("--format", choices=("human", "json"), default="human")

    init = subparsers.add_parser("init", help="Create a starter .memorywiki.toml.")
    init.add_argument("--path", default=CONFIG_FILE_NAME)
    init.add_argument("--overwrite", action="store_true")
    init.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "show"
    try:
        if command == "init":
            path = write_default_config(args.path, overwrite=args.overwrite)
            payload = {"path": str(path), "created": True}
            if args.format == "json":
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"Created MemoryWiki config: {path}")
            return 0

        payload = _config_payload(Path.cwd())
        if command == "validate":
            payload = {"status": "ok", **payload}
        if args.format == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if command == "validate":
                print("MemoryWiki config is valid.")
            print(render_human(payload), end="")
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
