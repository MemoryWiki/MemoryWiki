# FAQ

## Installation

### Does MemoryWiki require an API key?

No. The default workflow is local-first and does not require a hosted model.
The optional OpenAI backend must be installed and enabled explicitly.

### Which Python versions are supported?

The core CLI supports Python 3.9+. MCP support is intended for Python 3.10+.

### Should I install from a checkout or from GitHub?

Use a checkout for the first run because examples, tests, and docs are nearby.
Use a GitHub tag install once you only need the CLI/MCP commands.

### Why did installation fail on my machine?

Most failures come from an old `pip`, an unsupported Python version, or installing
the MCP extra on Python 3.9. See `docs/troubleshooting/common-errors.md`.

## Usage

### Is memory treated as instructions?

No. Memory is context data. System, developer, and current user instructions
stay higher priority than loaded memory.

### Does MemoryWiki automatically save conversations?

No. Durable writes require explicit user intent, such as asking to save a
session summary, ingest a source, crystallize an answer, forget a memory, or
write global memory.

### What is canonical memory?

Markdown/JSONL files under the memory root are canonical. Retrieval indexes are
sidecars and can be rebuilt.

### How do I see what memories exist?

Use:

```bash
memorywiki-list --project-root <root> --scope project --kind all
```

Add `--kind semantic` or `--concept <tag>` to narrow the list.

### Why Markdown?

Markdown keeps memory reviewable by humans. You can grep it, diff it, back it
up, delete it, and version it with normal file tools.

### How is this different from one `AGENTS.md` file?

`AGENTS.md` is a useful startup guide. MemoryWiki adds layered memory, source
provenance, conflict/update history, retrieval indexes, MCP recall, audit logs,
and dry-run-first delete workflows.

### Can I use one global memory across projects?

Yes. Use project roots for local project context and a separate global root for
stable cross-project facts. Keep global writes explicit.

### What should I do when recall returns nothing?

Check the root and scope first:

```bash
memorywiki-list --project-root <root> --scope project
memorywiki-index-maintain --project-root <root> --scope project
```

Then broaden the query or rebuild a stale index with `--write`.

## MCP

### Is MCP read-only?

By default, yes. Read tools work without write gates. Write tools require
explicit environment variables.

### Which MCP tools are available?

The core tool set includes recall, list, read, index maintain, write session,
crystallize, ingest source, and forget.

### How do I debug MCP setup?

Run:

```bash
memorywiki-mcp-doctor --repo-root "$(pwd)" --config .mcp.json --format human
```

### Why are MCP writes denied?

Because write gates are off. Enable them only after explicit user approval:
`MEMORY_MCP_WRITE_ENABLED=true`, and additionally
`MEMORY_GLOBAL_WRITE_ENABLED=true` for global writes.

## Performance

### Do I need embeddings?

No. Local hybrid recall works without a hosted embedding service. `--embedding
local` uses deterministic local hash features, not a network call.

### Why rebuild indexes?

Retrieval indexes are sidecars. Rebuild them when memory files changed and
`memorywiki-index-maintain` reports stale or tampered rows.

### Can MemoryWiki handle many projects?

Yes. Use separate project roots and an optional global root. For larger rollouts,
use the project matrix and MCP doctor tools.

## Safety

### Can memory contain prompt injection text?

Memory is stored as data, not instructions. Instruction-shaped English and
Chinese text is neutralized before recall/read output surfaces.

### Can I delete memory safely?

Use `memorywiki-forget` without `--apply` first. It is dry-run-first and requires
a reason. Add `--apply` only after reviewing the target.
