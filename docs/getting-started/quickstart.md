# Quickstart

This guide takes a new user from a fresh checkout to the first successful recall.
It uses the synthetic memory root in `examples/memory-root`, so it is safe to run
without touching real project data.

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

## 3. Run Your First Recall

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

## 4. Browse Available Memories

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

## 5. Next Steps

- Connect an agent through MCP: see `docs/clients/generic-mcp.md`.
- Create a project memory root at `your-project/.agent_memory/project`.
- Read common problems: see `docs/troubleshooting/common-errors.md`.
- Learn the safety model: see `SECURITY.md`.

MemoryWiki does not automatically save ordinary chat. Durable writes happen only
when a user explicitly asks to save, ingest, crystallize, or forget memory.
