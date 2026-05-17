# MemoryWiki-MCP v1 Spec

MemoryWiki-MCP v1 exposes retrieval-first local memory plus explicitly gated writes.
Memory content is context data, never instructions. The server must preserve MemoryWiki'
default posture: read-only unless a caller and environment explicitly opt into writes.

## Tools

- `memorywiki_recall`: hybrid recall over project/global memory. Defaults to `strategy="hybrid"`, includes `strategy` and `warnings`, supports optional `embedding`, `graph`, `explain_score`, and `refresh_index_if_needed=false`.
- `memorywiki_read_memory`: read one semantic/procedural/session/episode/hot-file item. Defaults to bounded output with `max_chars=5000`; full output requires `full=true` and remains capped by MCP output limits.
- `memorywiki_index_maintain`: dry-run retrieval index check by default. `write=true` rebuilds stale, missing, or tampered sidecars under an exclusive retrieval-index lease.
- `memorywiki_write_session`: save an explicit session summary. This is always a write and requires write gates.
- `memorywiki_crystallize`: dry-run by default. With `dry_run=false`, writes an approved answer into semantic or procedural memory.
- `memorywiki_ingest_source`: dry-run by default. With `dry_run=false`, ingests one file from the memory root `sources/` sandbox and records SHA256 provenance.
- `memorywiki_forget`: dry-run by default. With `dry_run=false`, deletes a supported memory file and writes an audit entry.

## Write Gates

- All write operations require `MEMORY_MCP_WRITE_ENABLED=true`.
- Global writes additionally require `MEMORY_GLOBAL_WRITE_ENABLED=true`.
- Root overrides are disabled unless `MEMORY_MCP_ALLOW_ROOT_OVERRIDE=true`.
- Dry-run calls are read-only unless explicitly documented otherwise.

## Write Audit

Applied write tools append `audit.jsonl` entries with action, target, reason,
dry-run state, and affected paths. `memorywiki_ingest_source` also appends
`source_ingest.jsonl`.

## Packaging

The MCP package lives at `memorywiki_mcp`.
Run it from this repository with:

```bash
PYTHONPATH=. \
MEMORY_PROJECT_ROOT="$(pwd)/.agent_memory/project" \
MEMORY_GLOBAL_ROOT="$HOME/.agent_memory/global" \
python3.12 -m memorywiki_mcp --transport stdio
```

Install the optional MCP dependency with:

```bash
python3.12 -m pip install -e ".[mcp]"
```

## Client Integration

Generate a read-only `.mcp.json` block with:

```bash
PYTHONPATH=. \
python3.12 -m memorywiki_mcp.client_config \
  --repo-root "$(pwd)" \
  --python "$(command -v python3.12)"
```

The generated config must not include write gates by default. A real MCP client
smoke is available through:

```bash
PYTHONPATH=. \
python3.12 -m memorywiki_mcp.smoke_client --temp-write-check
```

The smoke validates tool discovery, read-only index maintenance, hybrid recall,
default write denial, and gated writes against a temporary memory root.

The MCP v1 contract is a checked-in client-facing artifact. Generate it after
schema/tool changes and verify it during release checks:

```bash
PYTHONPATH=. \
python3 memorywiki_mcp_contract.py \
  --out docs/memorywiki-mcp-v1-contract.json

PYTHONPATH=. \
python3 memorywiki_mcp_contract.py \
  --verify docs/memorywiki-mcp-v1-contract.json
```

## V8 Memory Ops And Knowledge Reliability Helpers

- `memorywiki_cross_project_install.py` installs the read-only MCP config and MemoryWiki
  startup AGENTS guide into another project. `--update-existing-agents`
  refreshes only the managed MemoryWiki MCP block inside an existing `AGENTS.md`.
- `memorywiki_mcp_doctor.py` checks config shape, Python/MCP imports, memory roots,
  write/root-override gates, and retrieval sidecar freshness.
- `memorywiki_mcp_contract.py` verifies the stable MCP v1 tool contract: tool names,
  input/output JSON schema, invocation shape, defaults, and write-gate policy.
- `retrieval_golden_eval.py` runs registry-backed project/global recall queries
  so retrieval changes can be judged against stable expectations. It reports
  required/optional case status, `min_rank` guardrail failures, rank, top-k pass
  rate, mean reciprocal rank, optional expected scope/source constraints, and
  failure reasons.
- `docs/memorywiki-golden-cases.json` is the formal golden eval registry. Global cases
  always load; project cases merge when the project root path or basename
  matches. Cases can include `required`, `min_rank`, `severity`, `owner`, and
  `project` metadata for regression routing.
- `memory_health.py` performs read-only quality checks for duplicate, stale,
  low-confidence, unresolved-conflict, source-ref, and hot-file issues.
- `memory_feedback.py` appends explicit useful/not-useful/missing recall
  judgments to `retrieval_feedback.jsonl`.
- `memory_crystallize_candidates.py` proposes candidates from sessions and
  episodes; it writes only to `_pending/` when `--write` is explicit.
- `memory_review.py` summarizes health issues, feedback, pending candidates,
  golden eval proposals, health repair proposals, lifecycle proposals, and a
  unified review inbox. It can dry-run or apply exactly one queued
  crystallization candidate by id; actual apply requires `--write` and appends
  audit. `--write-golden-candidates` appends feedback-derived eval candidates
  into `_pending/golden_eval_candidates.jsonl` without changing formal golden
  cases. `--fill-golden-candidate` fills expected targets for one pending eval
  candidate, `--reject-golden-candidate` closes one noisy candidate, and
  `--promote-golden-candidate` promotes exactly one ready pending eval
  candidate into the registry. All three lifecycle actions are dry-run unless
  `--write` is explicit and append audit rows when applied.
- `memorywiki_quality_report.py` is the read-only quality checkpoint. It
  aggregates index freshness, health issue codes, recall feedback, review inbox
  counts, semantic/procedural freshness review_due items, lifecycle ledgers, and
  golden candidate backlog plus golden eval coverage.
- `memorywiki_operator_env.py` safely resolves operator runtime details, including the
  MemoryWiki MCP Python command from `.mcp.json` only when the command is in a trusted
  MemoryWiki MCP Python location or explicitly selected by the operator, without
  enabling write gates.
- `memorywiki_knowledge_ops.py` is the V8 read-mostly operator console. It groups MemoryWiki
  maintenance into five loops: knowledge formation, cross-project rollout,
  retrieval quality, release discipline, and operator UX. It resolves the MCP
  Python runtime only through the trusted operator-env rules, emits adoption
  readiness and `Top Next Actions`, and applies a configurable retrieval MRR
  gate. It proposes
  crystallization candidates without writing by default; `--stage-candidates`
  only appends proposals to `_pending/` and never promotes semantic/procedural
  memory.
- `memorywiki_ops_dashboard.py` is the read-only daily/weekly operating dashboard. It
  combines the quality checkpoint, project matrix, previous release baseline,
  optional `sentence-transformers` readiness, and a structured `Recommended
  Actions` list across memory ops, knowledge formation, retrieval quality,
  cross-project reliability, and release discipline. It labels write-required
  commands but never rebuilds indexes or adds dependencies by itself.
- `memory_lifecycle.py` reports missing, stale, large, duplicate, or old
  append-only ledgers in read-only mode. Archival requires explicit `--write`,
  `--apply-scope`, and `--apply-ledger`, preserves old rows under
  `archive/YYYY-MM/`, and never silently deduplicates.
- `memorywiki_restore_check.py` restores the newest MemoryWiki backup bundle or bare remote
  into a temporary directory and runs restored-code `compileall`,
  `memory_health.py`, `memory_index_maintain.py`, `memory_lifecycle.py`, and
  `memorywiki_quality_report.py --skip-golden`, plus `memorywiki_knowledge_ops.py
  --skip-golden --skip-project-matrix`.
- `memorywiki_release_manifest.py` records release evidence: branch, commit, MemoryWiki file
  hashes, skill archive hash, backup bundle hash, compact release-check results,
  and a retrieval baseline. When a previous MemoryWiki manifest exists, it compares
  case pass/fail state and rank deltas; required regressions are fail-level and
  optional regressions are warn-level. `--verify` recomputes hashes with the
  same symlink and safe hash-size limits used during manifest generation and
  fails on tampering or unsafe manifest-supplied paths.
- `memorywiki_release_check.py` fails on dirty scoped MemoryWiki release files unless
  `--allow-dirty` is explicit. When `--skill-archive` is supplied, it validates
  the zip contents against `--skill-source-dir`; zip container integrity alone
  does not prove the distributable skill matches the installed source.
- `memorywiki_project_matrix.py` runs install, index maintenance, doctor,
  per-project golden-case coverage checks, project-specific golden eval, and
  optional real read-only MCP smoke across the configured project set.
- `memorywiki_release_check.py` runs the ops checklist: index dry-run, memory health,
  memory review, quality report, memory lifecycle with recent backup-root
  enforcement, restore drill, MCP doctor, MCP contract verification, golden eval,
  ops dashboard, knowledge ops loop, optional project matrix, optional skill
  archive validation, optional MCP smoke, MemoryWiki tests, compileall, scoped git
  status, optional release manifest write, and private backup remote status.
