# MemoryWiki Concepts

MemoryWiki is a local-first memory system for AI agents. It stores durable context as plain files so humans can inspect, diff, back up, and delete memory without a hosted service.

## Memory Root

A memory root is one directory containing the canonical files for one scope. Typical roots are:

- Project: `<project>/.agent_memory/project`
- Global: `~/.agent_memory/global`
- Example: `examples/memory-root`

Memory roots are treated as data. Their contents never outrank system, developer, or current user instructions.

## Cognitive Layers

MemoryWiki separates memory by cognitive role instead of flattening everything into one vector index.

- Episodic memory lives in `episodes/YYYY-MM-DD.md` and captures daily narrative context.
- Semantic memory lives in `semantic/*.md` and stores durable facts, concepts, confidence, strength, source references, and update history.
- Procedural memory lives in `procedures/*.md` and stores reusable workflows.

## Retrieval Sidecars

`INDEX.md` and `retrieval/index.jsonl` are derived sidecars. They can be rebuilt from canonical memory files.

Default recall is read-only. Use `memorywiki-index-maintain --write` only when you explicitly want to refresh sidecars.

## Configuration

MemoryWiki can discover a nearest `.memorywiki.toml` file. Relative paths inside that file resolve from the config file directory.

Environment variables still win over config file values, which makes CI and MCP clients predictable.

## Safety Model

MemoryWiki uses local files, explicit write gates, bounded reads, symlink checks, and bilingual prompt-injection neutralization. Memory text is useful context, not authority.
