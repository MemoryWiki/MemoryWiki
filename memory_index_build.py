from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from memory_system.paths import MemoryScopePaths
from memory_system.retrieval_index import build_and_write_index
from memory_system.store import ScopedMemoryStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a local MemoryWiki retrieval index.")
    parser.add_argument(
        "--root",
        default=str(Path.cwd() / ".agent_memory" / "project"),
        help="Memory root to index.",
    )
    parser.add_argument(
        "--scope",
        choices=("project", "global"),
        default="project",
        help="Scope label to write into index rows.",
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def render_human(payload: dict) -> str:
    return (
        "Built retrieval index for {scope} memory: {indexed} rows\n"
        "Index: {index_path}\n"
    ).format(**payload)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).expanduser()
        if not root.exists():
            raise ValueError(f"Memory root does not exist: {root}")
        store = ScopedMemoryStore(
            MemoryScopePaths.from_root(root, scope=args.scope),
            sanitize_on_write=True,
            secure_permissions=True,
        )
        payload = build_and_write_index(store, args.scope)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
