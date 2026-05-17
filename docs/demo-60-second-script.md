# 60-Second Demo Script

Use this script for a short terminal recording or narrated launch clip.

## Story

Agents forget project context. MemoryWiki keeps durable memory as local
Markdown/JSONL, then lets CLI or MCP clients recall it read-first.

## Terminal Script

```bash
git clone https://github.com/MemoryWiki/MemoryWiki.git
cd MemoryWiki
python3 -m pip install -e ".[mcp]"
memorywiki-index-maintain --project-root examples/memory-root --scope project --format human
memorywiki-recall --project-root examples/memory-root --scope project --query "How does MemoryWiki save agent memory?" --strategy hybrid --embedding local --graph local --format human
memorywiki-forget --root examples/memory-root --scope project --kind semantic --id memorywiki-overview --reason "demo dry run"
```

## Talking Points

- Memory is stored in files you can inspect, diff, back up, and delete.
- Recall returns provenance labels such as `project/semantic` or
  `project/procedure`.
- Indexes are rebuildable sidecars, not the source of truth.
- Forget/delete is dry-run-first and reason-required.
- MCP writes stay behind explicit gates.

## Closing Line

```text
MemoryWiki is local-first agent memory: grep it, diff it, delete it, and recall it through CLI or MCP.
```
