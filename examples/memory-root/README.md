# Example Memory Root

This directory is a synthetic MemoryWiki memory root. It is safe to inspect, copy, and use for demos.

Try:

```bash
memorywiki-index-maintain --project-root examples/memory-root --scope project
memorywiki-recall --project-root examples/memory-root --scope project --query "What is MemoryWiki?"
memorywiki-list --project-root examples/memory-root --kind semantic
```

Canonical memory files live in `semantic/`, `procedures/`, `episodes/`, and `sessions/`. `INDEX.md` and `retrieval/index.jsonl` are rebuildable sidecars.
