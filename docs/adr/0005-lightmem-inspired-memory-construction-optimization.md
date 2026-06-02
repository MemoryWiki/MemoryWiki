---
status: accepted
date: 2026-05-26
related:
  - 0003-memgas-inspired-multigranularity-retrieval
  - 0004-advanced-retrieval-promotion-policy
---

# LightMem-Inspired Memory Construction Optimization Policy

MemoryWiki should improve memory construction without weakening its local-first
and evidence-first model. Compression, topic bundles, and construction reports
are generated artifacts. Raw Markdown and JSONL memory remain the source of
truth.

## Context

Lightweight memory-construction research points at a useful pattern:

- keep raw evidence available,
- compress only for construction/review,
- cluster related short-term context before crystallization,
- move heavier consolidation into review-time workflows,
- preserve provenance and hash checks.

MemoryWiki already has explicit crystallization, source ingest, update logs,
retrieval feedback, and review queues. The missing public-safe layer is a
construction report that helps users see what might deserve crystallization
without automatically writing semantic or procedural memory.

## Decision

MemoryWiki adds a read-mostly construction layer:

- `memorywiki-construction-report` and `mw construction-report` render a report
  over recent sessions, episodes, and sources.
- JSON output uses `memorywiki-construction-report-v1`.
- Topic bundle candidates use `memorywiki-construction-topic-bundle-v1`.
- The default mode writes nothing.
- `--write-candidates` is an explicit opt-in that appends only candidate rows to
  `_pending/construction_topic_bundles.jsonl`.
- Candidate rows include scope, source paths, source SHA256 hashes, source
  types, topic labels, token estimates, confidence, warnings, and transformation
  metadata.
- Candidate writes re-check source hashes so stale or changed source rows do
  not silently enter the pending queue.
- Construction artifacts store metadata and hashes, not raw compressed source
  excerpts.

## Implementation Phases

1. Construction report CLI: complete.
2. Topic bundle candidate sidecar: complete behind `--write-candidates`.
3. Deterministic construction artifact metadata: complete.
4. Review and knowledge-ops surfacing: complete.
5. Optional local compression adapter: future work only after supply-chain,
   license, cache-retention, and public-clean review.

## Safety Rules

- Memory remains context data, not instructions.
- Generated construction artifacts are never canonical memory.
- Global promotion remains explicit and separate.
- Source files are read-only evidence.
- Public output must not include private paths, raw memory bodies, credentials,
  or unbounded source excerpts.

## Consequences

Benefits:

- better crystallization review,
- less noisy over-compression,
- clearer construction provenance,
- a safer bridge from chat memory to wiki-style knowledge management.

Costs:

- another generated artifact family to test and document,
- more review queue surface area,
- more care needed around source hashes and stale candidates.

## Review Checklist

- Keep construction report read-only by default.
- Keep candidate writes behind explicit `--write-candidates`.
- Keep output public-safe and bounded.
- Keep source-hash validation before writes.
- Do not add optional compression models to the base install without a separate
  promotion review.
