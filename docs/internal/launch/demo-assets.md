# Demo Assets

Prepared launch assets:

- `docs/assets/memorywiki-avatar.png`: 400x400 GitHub avatar candidate.
- `docs/assets/memorywiki-social-preview.png`: 1280x640 repository social
  preview candidate for GitHub link cards.
- `docs/assets/memorywiki-quickstart.gif`: short terminal-style quickstart demo
  for the README hero section.
- `docs/assets/recall-output.svg`: static recall output screenshot for posts,
  docs, and social previews.
- README Mermaid architecture diagram: local files, CLI, MCP, retrieval index,
  and explicit write gates.

## Demo 1: two-minute quickstart

```bash
git clone https://github.com/MemoryWiki/MemoryWiki.git
cd MemoryWiki
python3 -m pip install -e ".[mcp]"
memorywiki-index-maintain --project-root examples/memory-root --scope project --format human
memorywiki-recall --project-root examples/memory-root --scope project --query "What is MemoryWiki?" --strategy hybrid --embedding local --graph local --format human
```

Message: MemoryWiki works locally, with no hosted memory service.

## Demo 2: cross-project recall

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

Message: project memory and global memory can be recalled together without
mixing them as canonical sources.

## Demo 3: safe forget workflow

```bash
memorywiki-forget \
  --root examples/memory-root \
  --scope project \
  --kind semantic \
  --id memorywiki-overview \
  --reason "synthetic demo cleanup"
```

Message: deletion starts as a dry run and needs an explicit reason. `--apply` is
required for the destructive action.

## Social image caption

```text
MemoryWiki: local-first Markdown memory for AI agents.
grep it. diff it. back it up. delete it.
```

## Short pitch variants

```text
MemoryWiki is local-first Markdown memory for AI agents: grep it, diff it, back it up, delete it, and recall it through CLI or MCP.
```

```text
Agents forget repo context. MemoryWiki keeps project memory in local Markdown/JSONL with provenance, hybrid recall, MCP, and explicit write gates.
```
