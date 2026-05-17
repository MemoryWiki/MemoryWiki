from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "memory-root"


@dataclass
class Case:
    name: str
    query: str
    expected: list[str]


CASES = [
    Case(
        name="overview",
        query="What is MemoryWiki?",
        expected=["MemoryWiki", "local-first"],
    ),
    Case(
        name="explicit-save",
        query="How should an agent save a session?",
        expected=["explicit", "session"],
    ),
    Case(
        name="mcp",
        query="Does MemoryWiki support MCP recall?",
        expected=["MCP", "recall"],
    ),
]


def run_case(case: Case) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "memory_recall.py"),
            "--project-root",
            str(EXAMPLE_ROOT),
            "--scope",
            "project",
            "--query",
            case.query,
            "--strategy",
            "hybrid",
            "--embedding",
            "local",
            "--graph",
            "local",
            "--token-budget",
            "600",
            "--format",
            "human",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    haystack = (completed.stdout + "\n" + completed.stderr).lower()
    matched = [item for item in case.expected if item.lower() in haystack]
    passed = completed.returncode == 0 and len(matched) == len(case.expected)
    return {
        "name": case.name,
        "query": case.query,
        "expected": case.expected,
        "matched": matched,
        "passed": passed,
        "returncode": completed.returncode,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# MemoryWiki Mini Recall Benchmark",
        "",
        "This is a tiny public smoke benchmark against `examples/memory-root`.",
        "It checks that local hybrid recall can surface the expected sample memory.",
        "",
        "- Cases: `%s`" % payload["total"],
        "- Passed: `%s`" % payload["passed"],
        "- Pass rate: `%.2f`" % payload["pass_rate"],
        "",
        "| Case | Passed | Matched |",
        "|---|---:|---|",
    ]
    for item in payload["cases"]:
        lines.append(
            "| {name} | {passed} | {matched} |".format(
                name=item["name"],
                passed="yes" if item["passed"] else "no",
                matched=", ".join(item["matched"]) or "-",
            )
        )
    return "\n".join(lines) + "\n"


def run_benchmark() -> dict[str, Any]:
    rows = [run_case(case) for case in CASES]
    passed = sum(1 for item in rows if item["passed"])
    return {
        "benchmark": "memorywiki-mini-recall",
        "total": len(rows),
        "passed": passed,
        "pass_rate": passed / len(rows) if rows else 1.0,
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the public MemoryWiki mini recall benchmark.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    payload = run_benchmark()
    if args.format == "markdown":
        print(render_markdown(payload), end="")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] == payload["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
