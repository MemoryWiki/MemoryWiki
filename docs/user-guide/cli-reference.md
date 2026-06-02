# CLI Reference

Install the public CLI and MCP extras in editable mode:

```bash
python3 -m pip install -e ".[mcp]"
```

Install developer checks when you are working on MemoryWiki itself:

```bash
python3 -m pip install -e ".[dev,mcp]"
```

Use full commands such as `memorywiki-recall`, or the short `mw` alias for daily
operations. `mw --help` lists the supported aliases; the alias forwards arguments
to the matching full command.

## Configuration

```bash
memorywiki-config init
memorywiki-config show
memorywiki-config validate
mw config show
```

MemoryWiki reads `.memorywiki.toml` when present. Command-line flags still win
over config file defaults.

## Daily Context And Recall

```bash
memorywiki-status \
  --project-root .agent_memory/project \
  --global-root ~/.agent_memory/global \
  --scope all
mw status --project-root .agent_memory/project --scope project
```

```bash
memorywiki-index-maintain --project-root .agent_memory/project --scope project
memorywiki-index-maintain --project-root .agent_memory/project --scope project --write
mw index --project-root .agent_memory/project --scope project
```

```bash
memorywiki-context \
  --project-root .agent_memory/project \
  --global-root ~/.agent_memory/global \
  --scope all \
  --mode startup \
  --query "current project status" \
  --format markdown
mw context --project-root .agent_memory/project --scope project --mode startup
```

`memorywiki-context` is read-only by default and is the preferred startup
surface. It separates stable profile, dynamic activity, and task recall. Raw
source excerpts are omitted unless `--include-excerpts` is explicit.

```bash
memorywiki-recall \
  --project-root .agent_memory/project \
  --global-root ~/.agent_memory/global \
  --scope all \
  --query "current project status" \
  --strategy hybrid
```

```bash
memorywiki-list --project-root .agent_memory/project --kind semantic
mw list --project-root .agent_memory/project --kind all
```

```bash
memorywiki-export --project-root .agent_memory/project --scope project --format json
memorywiki-export --project-root .agent_memory/project --kind all --format markdown --out memory-export.md
mw export --project-root .agent_memory/project --kind semantic --format csv
```

`memorywiki-export` is read-only against memory roots. It prints to stdout by
default and writes only when `--out` is explicit. Source document bodies are not
included unless `--include-source-bodies` is also explicit.

Before a full code read, use advisory file history to check prior MemoryWiki
context for a project file without reading that file's contents:

```bash
memorywiki-file-history \
  --path src/app.py \
  --workspace-root "$(pwd)" \
  --project-root .agent_memory/project \
  --scope project \
  --format json
mw file-history --path src/app.py --workspace-root "$(pwd)"
```

## Explicit Writes

```bash
memorywiki-session-summary --save \
  --project-root .agent_memory/project \
  --summary "What changed and why" \
  --keypoint "Stable decision" \
  --action "Completed action" \
  --pending "Next step"
```

```bash
memorywiki-crystallize \
  --root .agent_memory/project \
  --kind semantic \
  --id stable-fact \
  --title "Stable Fact" \
  --answer "The durable fact to remember."
mw crystallize --root .agent_memory/project --kind semantic --id stable-fact --title "Stable Fact" --answer "The durable fact to remember."
```

```bash
memorywiki-ingest-source \
  --root .agent_memory/project \
  --source note.md \
  --id source-backed-fact \
  --title "Source Backed Fact" \
  --summary "Summary with source provenance"
mw ingest --root .agent_memory/project --source note.md --id source-backed-fact --title "Source Backed Fact" --summary "Summary with source provenance"
```

```bash
memorywiki-forget \
  --root .agent_memory/project \
  --scope project \
  --kind semantic \
  --id stable-fact \
  --reason "No longer correct" \
  --apply
```

## Review And Knowledge Operations

```bash
memorywiki-health --project-root .agent_memory/project --scope project
memorywiki-quality-report --project-root .agent_memory/project --scope project --skip-golden
memorywiki-construction-report --project-root .agent_memory/project --scope project --format markdown
memorywiki-review --project-root .agent_memory/project --scope project
memorywiki-lifecycle --project-root .agent_memory/project --scope project
mw construction-report --project-root .agent_memory/project --scope project --format markdown
mw quality --project-root .agent_memory/project --scope project --skip-golden
```

`memorywiki-construction-report` is read-only by default. Add
`--write-candidates` only when you explicitly want to append topic bundle
candidates to `_pending/construction_topic_bundles.jsonl`; this still does not
promote semantic or procedural memory.

Lifecycle capture is also pending-only. It imports public-safe agent lifecycle
JSONL in dry-run mode by default:

```bash
memorywiki-capture-ingest \
  --adapter generic-jsonl \
  --source lifecycle-events.jsonl \
  --project-root .agent_memory/project \
  --format json
mw capture-ingest --source lifecycle-events.jsonl --project-root .agent_memory/project
```

Use `--write --reason "..."` only when you explicitly want to stage rows under
`_pending/session_captures.jsonl`; this does not promote canonical memory.

```bash
memorywiki-knowledge-ops \
  --project-root .agent_memory/project \
  --global-root ~/.agent_memory/global \
  --period daily \
  --format markdown
```

```bash
memorywiki-ops-dashboard \
  --project-root .agent_memory/project \
  --global-root ~/.agent_memory/global \
  --period weekly \
  --format markdown
```

## Retrieval And Evaluation

```bash
memorywiki-index-build --root .agent_memory/project --scope project
memorywiki-golden-eval --case-file docs/memorywiki-golden-cases.json
```

```bash
memorywiki-feedback \
  --project-root .agent_memory/project \
  --query "current project status" \
  --rating useful \
  --reason "Top hit answered the question"
```

```bash
memorywiki-crystallize-candidates \
  --project-root .agent_memory/project \
  --scope project \
  --format human
```

## Project Rollout

```bash
memorywiki-project-profile --project-root .agent_memory/project --format markdown
memorywiki-project-matrix --config examples/project-matrix.example.json --format markdown
memorywiki-project-agents --workspace-root . --format markdown
memorywiki-agents-review-prompt --workspace-root . --hours 24
```

```bash
memorywiki-cross-project-install \
  --project-root /path/to/project \
  --memorywiki-root /path/to/MemoryWiki \
  --dry-run
```

## Backup, Restore, And Release

```bash
memorywiki-backup \
  --root .agent_memory/project \
  --backup-root ~/memorywiki-backups \
  --name demo-project
```

```bash
memorywiki-restore-check --root .agent_memory/project --format human
memorywiki-release-check --root .agent_memory/project --format human
memorywiki-release-manifest --root . --output release-manifest.json
mw release-check --root .agent_memory/project --format human
```

## Migration And Timeline Helpers

```bash
memorywiki-merge-episodes \
  --src legacy-memory \
  --dst .agent_memory/project \
  --scope project \
  --dry-run
mw merge --src legacy-memory --dst .agent_memory/project --scope project --dry-run
```

```bash
memorywiki-timeline --project-root .agent_memory/project --format markdown
memorywiki-wake-prompt --project-root .agent_memory/project --format markdown
```

## MCP

```bash
memorywiki-mcp-config --client codex --output .mcp.json
memorywiki-mcp-contract --output docs/memorywiki-mcp-v1-contract.json
memorywiki-mcp-contract --verify docs/memorywiki-mcp-v1-contract.json
memorywiki-mcp-doctor --config .mcp.json
memorywiki-mcp-smoke --config .mcp.json
mw mcp-contract --verify docs/memorywiki-mcp-v1-contract.json
```

MCP write tools are disabled by default. Enable writes only for explicit
save/update/delete workflows.
