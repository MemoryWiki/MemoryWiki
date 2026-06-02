# Quickstart

This guide takes a new user from a fresh checkout to the first context capsule
and focused recall. It uses the synthetic memory root in `examples/memory-root`,
so it is safe to run without touching real project data.

## 1. Clone And Install

```bash
git clone https://github.com/MemoryWiki/MemoryWiki.git
cd MemoryWiki
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[mcp]"
```

Expected check:

```bash
memorywiki-recall --help
```

You should see CLI help. If the command is missing, activate the virtual
environment and reinstall with `python -m pip install -e ".[mcp]"`.

## 2. Check The Example Index

Run the read-only status helper first:

```bash
memorywiki-status \
  --project-root examples/memory-root \
  --scope project \
  --format human
```

```bash
memorywiki-index-maintain \
  --project-root examples/memory-root \
  --scope project \
  --format human
```

Expected output shape:

```text
# MemoryWiki Retrieval Index Maintenance

Mode: dry-run
Scope: project
Rebuild needed: no
```

If it says the index is missing or stale, rebuild the example sidecar:

```bash
memorywiki-index-maintain \
  --project-root examples/memory-root \
  --scope project \
  --write \
  --format human
```

## 3. Assemble Your First Context Capsule

Use context first when an agent is starting work. It returns a bounded
profile-first capsule, then a small task recall section when a query is
provided:

```bash
memorywiki-context \
  --project-root examples/memory-root \
  --scope project \
  --mode startup \
  --query "What is MemoryWiki?" \
  --format markdown
```

Expected output shape:

```text
# MemoryWiki Context

Mode: startup
Scope: project
Read-only: yes
Metadata-first: yes
```

## 4. Run Focused Recall

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

Expected output shape:

```text
# Memory Recall

Query: What is MemoryWiki?
Strategy: hybrid

1. [project/semantic] MemoryWiki Overview (memorywiki-overview, score ...)
MemoryWiki is a local-first memory wiki for AI agents...
Sources: memory-file:memorywiki-overview
```

Use recall after context when you need ranked candidates, score/debug metadata,
or deeper evidence selection.

## 5. Browse Available Memories

```bash
memorywiki-list \
  --project-root examples/memory-root \
  --scope project \
  --kind semantic \
  --format table
```

Expected output shape:

```text
scope   kind      id                         title
project semantic  memorywiki-overview        MemoryWiki Overview
```

Use concept filtering when you know the topic:

```bash
memorywiki-list \
  --project-root examples/memory-root \
  --scope project \
  --kind semantic \
  --concept memory
```

## 6. Next Steps

- Connect an agent through MCP: see `docs/clients/generic-mcp.md`.
- Create a project memory root at `your-project/.agent_memory/project`.
- For file-specific work, run `memorywiki-file-history --path PATH --workspace-root "$(pwd)"` before reading large files.
- Read common problems: see `docs/troubleshooting/common-errors.md`.
- Learn the safety model: see `SECURITY.md`.

MemoryWiki does not automatically save ordinary chat. Durable writes happen only
when a user explicitly asks to save, ingest, crystallize, or forget memory.
