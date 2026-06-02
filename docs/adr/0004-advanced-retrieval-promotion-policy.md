---
status: accepted
date: 2026-05-26
related:
  - 0003-memgas-inspired-multigranularity-retrieval
---

# Advanced Retrieval Promotion Policy

MemoryWiki can expose experimental retrieval strategies, but changing defaults
requires explicit evidence, public-safe fixtures, rollback notes, and clean
release gates. This ADR governs advanced retrieval, evaluation, generated
retrieval sidecars, and promotion packets.

## Context

ADR0003 introduced opt-in multi-granularity retrieval ideas:

- retrieval index rows can include deterministic derived views,
- `memory_recall.py` can route over those views with explicit flags,
- MCP recall can pass those flags while keeping write gates unchanged,
- golden evaluation can compare baseline and candidate runs.

These features are useful, but they add ranking complexity. MemoryWiki should
not quietly change retrieval defaults without evidence that the new behavior is
safer, explainable, and reversible.

## Decision

Promotion stages are:

| Stage | Meaning | Exposure |
| --- | --- | --- |
| `experimental` | Prototype exists, evidence is incomplete. | Hidden or documented as exploratory. |
| `promotion-candidate` | First public-safe baseline is clean. | CLI/MCP opt-in flags only. |
| `recommended-opt-in` | Repeated baselines are clean and workflow docs are stable. | Docs may recommend exact flags for exact workflows. |
| `default-candidate` | Proposed default change has rollback proof. | Release candidate only. |
| `default` | Default changed by a dedicated ADR/update. | Normal behavior. |

Advanced retrieval writes include index refreshes, generated retrieval views,
evaluation artifacts, promotion packets, and retrieval sidecar mutations. This
definition does not treat ordinary test temporary directories, throwaway dry-run
output outside retrieval surfaces, or unrelated local build artifacts as
promotion writes.

Hard gates before moving beyond `promotion-candidate`:

- public-safe golden cases pass with no required regression,
- score explanations expose only sanitized metadata,
- prompt-injection shaped memory text remains context data, not instructions,
- no private paths, credentials, local operator notes, or raw memory bodies leak
  into docs, examples, packages, or MCP outputs,
- rollback instructions exist before any default promotion,
- release, security, dependency, and public-clean checks pass.

## Current State

ADR0003 is `promotion-candidate` in the public repository. Multi-granularity
retrieval remains opt-in through explicit CLI/MCP flags. The project may later
document a `recommended-opt-in` workflow if repeated baselines stay clean.

## Consequences

Benefits:

- safer retrieval experiments,
- more credible public benchmarks,
- explicit rollback paths,
- no silent change to memory authority boundaries.

Costs:

- more evaluation work before defaults change,
- extra benchmark and promotion packet maintenance,
- slower rollout for promising retrieval improvements.

## Review Checklist

- Keep advanced retrieval opt-in unless a later ADR promotes it.
- Keep score-explanation output sanitized and metadata-only.
- Keep public benchmark artifacts synthetic and public-safe.
- Keep MCP write behavior gated and explicit.
- Keep generated retrieval sidecars rebuildable, not canonical memory.
