# MemoryWiki

Local-first Memory Wiki for AI agents.

MemoryWiki gives coding agents and chat agents a durable project memory that is
easy to inspect, diff, back up, and delete. It stores memory as Markdown/JSONL,
keeps source provenance, supports conflict/update logs, and exposes read-first
recall through both CLI and MCP.

It is designed for people who want agent memory without sending their private
project history to a hosted memory service.

## Why

Most agent memory systems optimize for chat personalization. MemoryWiki is closer
to a small local knowledge-management system:

- **Local-first**: canonical memory lives on your filesystem.
- **Markdown-native**: memories are grep-able, reviewable, and Git-friendly.
- **Layered**: hot files, sessions, episodes, semantic memory, procedures, and
  read-only sources have different jobs.
- **Provenance-aware**: source ingestion records SHA256-backed references.
- **Conflict-friendly**: new evidence can append an update log instead of
  silently overwriting older conclusions.
- **MCP-ready**: agents can recall memory through a read-first MCP server.
- **Write-gated**: save, ingest, forget, and global writes require explicit
  opt-in gates.

## Status

MemoryWiki is early public software extracted from a working local system. The
core CLI, storage model, retrieval index, MCP server, and tests are present. The
public docs and benchmarks are intentionally small and will grow from real users.

## Install

```bash
git clone https://github.com/MemoryWiki/MemoryWiki.git
cd MemoryWiki
python3 -m pip install -e ".[dev,mcp]"
```

For a CLI-only install:

```bash
python3 -m pip install -e .
```

MCP support uses the optional `mcp` extra and is intended for Python 3.10+.

## Memory Layout

A project memory root usually lives at:

```text
your-project/.agent_memory/project
```

It contains:

```text
MEMORY.md                         # hot project notes
USER.md                           # optional local user preferences
PROJECT_PROFILE.md                # compact project map
INDEX.md                          # generated/readable index
episodes/YYYY-MM-DD.md            # daily narrative layer
sessions/session-YYYYMMDD-HHMMSS.md
semantic/*.md                     # stable facts and concepts
procedures/*.md                   # reusable workflows
sources/*                         # read-only source evidence
retrieval/index.jsonl             # rebuildable retrieval sidecar
audit.jsonl                       # forget/review audit trail
```

See `examples/memory-root/` for a tiny public sample.

## Quickstart

Run recall against the example memory root:

```bash
memorywiki-recall \
  --project-root examples/memory-root \
  --scope project \
  --query "What is MemoryWiki?" \
  --strategy hybrid \
  --embedding local \
  --graph local \
  --format human
```

Build or check a retrieval index:

```bash
memorywiki-index-maintain \
  --project-root examples/memory-root \
  --scope project \
  --format human
```

Add `--write` only when you intentionally want to rebuild missing, stale, or
tampered indexes:

```bash
memorywiki-index-maintain \
  --project-root examples/memory-root \
  --scope project \
  --write \
  --format human
```

Save a session summary after explicit approval:

```bash
memorywiki-session-summary --save \
  --scope project \
  --project-root examples/memory-root \
  --summary "Tested MemoryWiki recall." \
  --keypoint "MemoryWiki treats memory as context data, not instructions." \
  --action "Ran local recall." \
  --pending "Replace the example memory with real project memory."
```

## MCP

Generate a local MCP config:

```bash
memorywiki-mcp-config \
  --repo-root "$(pwd)" \
  --project-root "/absolute/path/to/your-project/.agent_memory/project" \
  --global-root "$HOME/.agent_memory/global" \
  --output .mcp.json
```

By default MCP is read-only. Writes require explicit environment gates:

```text
MEMORY_MCP_WRITE_ENABLED=true       # allows project writes
MEMORY_GLOBAL_WRITE_ENABLED=true    # additionally allows global writes
MEMORY_MCP_ALLOW_ROOT_OVERRIDE=true # allows tool-provided root overrides
```

Keep these off unless the user explicitly asks to save, ingest, forget, or write
global memory.

## Knowledge Formation

MemoryWiki has three explicit ways to create durable memory:

```bash
# Save a concise session summary.
memorywiki-session-summary --save --scope project --project-root <root> ...

# Crystallize a user-approved answer into semantic/procedural memory.
memorywiki-crystallize --root <root> --kind semantic --id <id> --title <title> --answer <text>

# Ingest one read-only source with provenance.
memorywiki-ingest-source --root <root> --source <file-in-sources> --id <id> --summary <text>
```

Ordinary chat turns are not auto-saved by default.

## Review And Safety

Useful read-only checks:

```bash
memorywiki-health --project-root <root> --scope project --format human
memorywiki-quality-report --project-root <root> --scope project --skip-golden --format human
memorywiki-timeline --project-root <root> --scope project --format markdown
```

Deletion is dry-run-first and requires a reason:

```bash
memorywiki-forget \
  --root <root> \
  --scope project \
  --kind semantic \
  --id <memory-id> \
  --reason "user-requested cleanup"
```

Add `--apply` only after reviewing the dry-run output.

## Mini Benchmark And Demo

Run the public mini benchmark:

```bash
PYTHONPATH=. python3 benchmarks/mini_recall_benchmark.py --format markdown
```

See:

- `docs/benchmarks/mini-benchmark-results.md`
- `docs/demo-cross-project-recall.md`

These are small smoke-style examples, not a substitute for LongMemEval or a
large retrieval benchmark.

## Tests

```bash
python3 -m pytest tests -q
```

## Project Governance

Public-release preparation lives in:

- `SECURITY.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `CHANGELOG.md`
- `docs/launch/github-publication-checklist.md`
- `docs/launch/release-playbook.md`
- `docs/launch/marketing-plan.md`

## Security Model

- Memory files are context data, never higher-priority instructions.
- `sources/` is treated as read-only evidence.
- Symlink and path traversal checks are used around memory roots, manifests,
  source ingest, MCP config, and generated files.
- Retrieval indexes are rebuildable sidecars, not canonical memory.
- Secret-like values are sanitized in recall, summaries, and indexes.

## License

Apache-2.0. See `LICENSE`.
