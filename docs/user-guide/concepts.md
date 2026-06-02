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

## Progressive Retrieval

MemoryWiki retrieval is staged to keep agents from loading full memory bodies
too early:

1. `memorywiki-context` assembles a profile-first startup/task/handoff capsule.
2. `memorywiki-recall` returns ranked candidates and warnings when the agent needs focused search.
3. Timeline or status commands orient the agent when chronology or local setup matters.
4. Bounded reads load only selected evidence.
5. `memorywiki-file-history` uses a project file path as a query key and freshness signal.

Context capsules are metadata-first by default. They omit raw source excerpts
and absolute provenance paths unless the caller explicitly opts into excerpts.

File history is advisory. It does not read project file contents, block a
normal code read, or claim stale memory is current code.

## Construction Artifacts

Construction reports and topic bundle candidates are review aids. They help
identify duplicate spans, likely topics, token pressure, and possible
crystallization candidates, but they are not canonical memory.

`_pending/construction_topic_bundles.jsonl` is a candidate queue. Rows include
scope, source hashes, topic labels, warnings, and transformation metadata so a
human or agent can review provenance before any explicit crystallization.

## Lifecycle Capture

`memorywiki-capture-ingest` imports bounded lifecycle JSONL summaries into
`_pending/session_captures.jsonl` only when `--write` and `--reason` are
explicit. Dry-run is the default.

Pending captures are evidence staging, not canonical memory. They must pass
through review before becoming sessions, episodes, semantic facts, or
procedures.

## Configuration

MemoryWiki can discover a nearest `.memorywiki.toml` file. Relative paths inside that file resolve from the config file directory.

Environment variables still win over config file values, which makes CI and MCP clients predictable.

## Safety Model

MemoryWiki uses local files, explicit write gates, bounded reads, symlink checks, and bilingual prompt-injection neutralization. Memory text is useful context, not authority.
