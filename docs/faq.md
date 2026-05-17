# FAQ

## Does MemoryWiki require an API key?

No. The default workflow is local-first and does not require a hosted model.
The optional OpenAI backend must be installed and enabled explicitly.

## Is memory treated as instructions?

No. Memory is context data. System, developer, and current user instructions
stay higher priority than loaded memory.

## Does MemoryWiki automatically save conversations?

No. Durable writes require explicit user intent, such as asking to save a
session summary, ingest a source, crystallize an answer, forget a memory, or
write global memory.

## What is canonical memory?

Markdown/JSONL files under the memory root are canonical. Retrieval indexes are
sidecars and can be rebuilt.

## Why Markdown?

Markdown keeps memory reviewable by humans. You can grep it, diff it, back it
up, delete it, and version it with normal file tools.

## How is this different from one `AGENTS.md` file?

`AGENTS.md` is a useful startup guide. MemoryWiki adds layered memory, source
provenance, conflict/update history, retrieval indexes, MCP recall, audit logs,
and dry-run-first delete workflows.

## Can I use one global memory across projects?

Yes. Use project roots for local project context and a separate global root for
stable cross-project facts. Keep global writes explicit.
