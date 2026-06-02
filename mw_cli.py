from __future__ import annotations

import argparse
import sys
from importlib import import_module

CommandTarget = tuple[str, str, str]


COMMANDS: dict[str, CommandTarget] = {
    "agents-review": (
        "Generate an evidence-driven AGENTS.md maintenance prompt.",
        "agents_review_prompt",
        "main",
    ),
    "backup": ("Create a local Git backup bundle.", "memory_backup", "main"),
    "candidates": (
        "Propose crystallization candidates for review.",
        "memory_crystallize_candidates",
        "main",
    ),
    "config": ("Inspect or initialize configuration.", "memorywiki_config", "main"),
    "construction-report": (
        "Render a read-only memory-construction report.",
        "memorywiki_construction_report",
        "main",
    ),
    "context": (
        "Assemble a profile-first startup context capsule.",
        "memorywiki_context",
        "main",
    ),
    "capture-ingest": (
        "Stage public-safe lifecycle JSONL into _pending/.",
        "memory_capture_ingest",
        "main",
    ),
    "crystallize": ("Promote an explicit answer into memory.", "memory_crystallize", "main"),
    "feedback": ("Record explicit recall feedback.", "memory_feedback", "main"),
    "export": ("Export memory data for review or migration.", "memorywiki_export", "main"),
    "file-history": (
        "Show advisory MemoryWiki history for a project file.",
        "memorywiki_file_history",
        "main",
    ),
    "forget": ("Dry-run or apply explicit deletion.", "memory_forget", "main"),
    "golden-eval": ("Run retrieval golden-case evaluation.", "retrieval_golden_eval", "main"),
    "health": ("Inspect memory health signals.", "memory_health", "main"),
    "index": ("Check or refresh retrieval indexes.", "memory_index_maintain", "main"),
    "index-build": ("Rebuild a single retrieval index.", "memory_index_build", "main"),
    "ingest": ("Ingest a source document with provenance.", "source_ingest", "main"),
    "install": (
        "Install MemoryWiki startup/MCP files into a project.",
        "memorywiki_cross_project_install",
        "main",
    ),
    "knowledge-ops": (
        "Render the read-mostly knowledge operations loop.",
        "memorywiki_knowledge_ops",
        "main",
    ),
    "lifecycle": ("Review ledger lifecycle and archive candidates.", "memory_lifecycle", "main"),
    "list": ("List memory inventory.", "memorywiki_list", "main"),
    "merge": ("Merge legacy daily files into episodes.", "merge_episodes", "main"),
    "mcp": ("Run the MemoryWiki MCP server.", "memorywiki_mcp.cli", "main"),
    "mcp-config": ("Generate an MCP client configuration.", "memorywiki_mcp.client_config", "main"),
    "mcp-contract": ("Generate or verify the MCP contract.", "memorywiki_mcp_contract", "main"),
    "mcp-doctor": ("Diagnose local MCP setup.", "memorywiki_mcp_doctor", "main"),
    "mcp-smoke": ("Smoke-test an MCP client configuration.", "memorywiki_mcp.smoke_client", "main"),
    "ops-dashboard": ("Render the operator dashboard.", "memorywiki_ops_dashboard", "main"),
    "project-agents": ("Render a project AGENTS.md template.", "project_agents", "main"),
    "project-matrix": ("Inspect cross-project rollout state.", "memorywiki_project_matrix", "main"),
    "project-profile": ("Render a project memory profile.", "project_profile", "main"),
    "quality": ("Run the unified quality report.", "memorywiki_quality_report", "main"),
    "recall": ("Recall memory with hybrid retrieval.", "memory_recall", "main"),
    "release-check": ("Run release-readiness checks.", "memorywiki_release_check", "main"),
    "release-manifest": ("Build or verify a release manifest.", "memorywiki_release_manifest", "main"),
    "restore-check": ("Run a restore drill against a memory root.", "memorywiki_restore_check", "main"),
    "review": ("Review pending memory items.", "memory_review", "main"),
    "status": ("Show read-only MemoryWiki startup status.", "memorywiki_status", "main"),
    "timeline": ("Render a memory timeline.", "memory_timeline", "main"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mw",
        description="Short MemoryWiki command alias. Use `mw <command> --help` for details.",
    )
    parser.add_argument("command", nargs="?", choices=sorted(COMMANDS))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        parser = build_parser()
        parser.print_help()
        print("\nCommands:")
        width = max(len(name) for name in COMMANDS)
        for name, (description, _, _) in sorted(COMMANDS.items()):
            print(f"  {name:<{width}} {description}")
        return 0
    command = args[0]
    if command not in COMMANDS:
        print(f"Unknown mw command: {command}", file=sys.stderr)
        return 2
    _, module_name, function_name = COMMANDS[command]
    module = import_module(module_name)
    command_main = getattr(module, function_name)
    result = command_main(args[1:])
    return 0 if result is None else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
