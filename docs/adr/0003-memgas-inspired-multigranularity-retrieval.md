---
status: promotion-candidate
date: 2026-05-26
---

# MemGAS-Inspired Multi-Granularity Retrieval Policy

MemoryWiki will absorb the retrieval ideas behind MemGAS as a bounded,
local-first retrieval enhancement. MemoryWiki will not vendor MemGAS, adopt its
state format, expose a `memgas` mode, or add heavyweight model/runtime
dependencies to the base system.

This ADR is a `promotion-candidate`: a bounded prototype exists and the current
public example baseline shows no regression, but multi-granularity retrieval
remains opt-in and is not the default recall behavior.

## Decision

Canonical memory remains Markdown/JSONL. Multi-granularity data is derived
sidecar state under `retrieval/index.jsonl` schema v3 and is rebuildable from
canonical memory.

Initial deterministic views:

- `title_concepts`
- `body`
- `summary_keypoints`
- `procedure_trigger_steps`
- `source_provenance`

Recall adds explicit flags:

```text
--granularity-router off|static|entropy
--association-reranker off|local
```

Defaults remain `off`. The router and reranker must not call network APIs,
load heavy model stacks, write canonical memory, or treat retrieved memory as
instructions.

## Safety Rules

- Derived views are sidecars, never canonical memory.
- Recall remains read-only unless an existing explicit refresh/write flag is
  passed.
- Stale or tampered indexes must warn and fall back to canonical reads.
- Score explanations must be bounded and metadata-only by default.
- Prompt-injection neutralization applies to every generated view.
- Base install must not add PyTorch, transformers, sentence-transformers, vLLM,
  scikit-learn, igraph, FAISS, or vector databases.

## Evidence

Current public-safe comparison:

| Config | Required pass rate | Overall pass rate | MRR |
| --- | ---: | ---: | ---: |
| `off` / `off` | 100% (5/5) | 100% (7/7) | 1.000 |
| `entropy` / `local` | 100% (5/5) | 100% (7/7) | 1.000 |

See `docs/benchmarks/adr0003-retrieval-comparison.md`.

## Rollout

1. Keep `off` as the default.
2. Expose `static` and `entropy` as experimental CLI/MCP options.
3. Require public baseline pass before release.
4. Add more public cases for timeline lookup, ambiguity, noisy synonyms, and
   false-positive conflict queries.
5. Promote only after repeated clean baselines.

## Non-Goals

- Do not vendor MemGAS.
- Do not add heavy retrieval dependencies to base install.
- Do not make OpenAI or any LLM backend mandatory.
- Do not enable automatic memory writes.
- Do not replace Markdown/JSONL canonical storage.
- Do not change MCP write gates.
