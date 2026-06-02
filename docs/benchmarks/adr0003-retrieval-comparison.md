# ADR0003 Retrieval Comparison

Date: 2026-05-26

This public-safe comparison records aggregate retrieval metrics only. It uses
the synthetic example memory root and does not include private memory body text,
absolute local paths, source excerpts, credentials, or user identifiers.

## Compared Configurations

Baseline:

```bash
PYTHONPATH=. python3 retrieval_golden_eval.py \
  --case-file docs/memorywiki-golden-cases.json \
  --strategy hybrid \
  --embedding local \
  --graph local \
  --ranker score \
  --granularity-router off \
  --association-reranker off
```

ADR0003 candidate:

```bash
PYTHONPATH=. python3 retrieval_golden_eval.py \
  --case-file docs/memorywiki-golden-cases.json \
  --strategy hybrid \
  --embedding local \
  --graph local \
  --ranker score \
  --granularity-router entropy \
  --association-reranker local \
  --index-schema-version 3
```

## Results

| Registry | Config | Required pass rate | Overall pass rate | MRR | Query-type slices |
| --- | --- | ---: | ---: | ---: | --- |
| Public example root | Baseline | 100% (5/5) | 100% (7/7) | 1.000 | `mcp`, `semantic`, `source_provenance`, `lifecycle`, `cross_project`, `safety`, `ops`: all 100% |
| Public example root | ADR0003 candidate | 100% (5/5) | 100% (7/7) | 1.000 | `mcp`, `semantic`, `source_provenance`, `lifecycle`, `cross_project`, `safety`, `ops`: all 100% |

## Decision

Multi-granularity retrieval is documented as experimental and opt-in.

The candidate has no observed public regression, but it is not the default
until more public cases cover timeline lookup, ambiguous/noisy synonym queries,
and false-positive conflict queries.
