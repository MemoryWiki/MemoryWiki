# MemoryWiki Examples

This directory contains small, public-safe fixtures you can use without a real
personal memory root.

- `memory-root/`: a tiny project memory root with semantic memories, one
  procedure, one episode, one session, and a rebuildable retrieval index.
- `demo-project/`: a minimal project wired to the example memory root.
- `mcp/`: example MCP client configuration.
- `project-matrix.example.json`: a sample cross-project rollout matrix.

Try the example root:

```bash
memorywiki-recall \
  --project-root examples/memory-root \
  --scope project \
  --query "What is MemoryWiki?" \
  --strategy hybrid \
  --embedding local \
  --graph local
```

Export it:

```bash
memorywiki-export \
  --project-root examples/memory-root \
  --scope project \
  --format markdown
```
