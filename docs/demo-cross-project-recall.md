# Demo: Cross-Project Recall

MemoryWiki keeps project memory and global memory separate. A typical agent
startup uses both:

```bash
PYTHONPATH=. python3 memory_recall.py \
  --project-root examples/memory-root \
  --global-root examples/memory-root \
  --scope all \
  --query "MemoryWiki local-first MCP recall explicit save" \
  --strategy hybrid \
  --embedding local \
  --graph local \
  --token-budget 800 \
  --format human
```

Expected behavior:

- The project scope surfaces `semantic/memorywiki-overview.md`.
- The procedure layer surfaces `procedures/explicit-save.md`.
- The output includes provenance labels such as `project/semantic` or
  `project/procedure`.

For real use, point `--project-root` at `your-project/.agent_memory/project` and
`--global-root` at a shared global memory directory such as
`$HOME/.agent_memory/global`.
