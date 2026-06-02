# MemoryWiki Public Retrieval Baseline

This is the public-safe retrieval baseline for MemoryWiki. It uses only the
synthetic example memory root under `examples/memory-root`; it does not depend
on private user memory or local project state.

## Command

```bash
scripts/check_public_retrieval_baseline.sh
```

## Baseline

- Date: 2026-05-26
- Strategy: `hybrid`
- Embedding: `local`
- Graph: `local`
- Ranker: `score`
- Granularity router: `entropy`
- Association reranker: `local`
- Index schema version: `3`
- Cases: 5 required / 2 optional
- Expected pass rate: 100%
- Expected MRR: 1.000

## Latest Comparison

| Registry | Router / association | Required pass rate | Overall pass rate | MRR |
| --- | --- | ---: | ---: | ---: |
| Public example root | `off` / `off` | 100% (5/5) | 100% (7/7) | 1.000 |
| Public example root | `entropy` / `local` | 100% (5/5) | 100% (7/7) | 1.000 |

## Expected Output

```text
# MemoryWiki Retrieval Golden Eval

Status: pass
Pass rate: 100% (7/7)
Required: 100% (5/5)
MRR: 1.000
Min MRR: 1.0 | MRR OK: True
Router: entropy | Association: local | Ranker: score
```

## Maintenance Rule

When retrieval ranking changes, run this public baseline before publishing.
Failures must be fixed or documented before release.
