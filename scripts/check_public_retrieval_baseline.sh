#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$(mktemp -d "$REPO_ROOT/.tmp-public-retrieval.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

PROJECT_ROOT="$WORKDIR/project-memory"
GLOBAL_ROOT="$WORKDIR/global-memory"
mkdir -p "$PROJECT_ROOT"
cp -R "$REPO_ROOT/examples/memory-root" "$GLOBAL_ROOT"

"$PYTHON" "$REPO_ROOT/memory_index_build.py" \
  --root "$PROJECT_ROOT" \
  --scope project \
  --format json >/dev/null

"$PYTHON" "$REPO_ROOT/memory_index_build.py" \
  --root "$GLOBAL_ROOT" \
  --scope global \
  --format json >/dev/null

"$PYTHON" "$REPO_ROOT/retrieval_golden_eval.py" \
  --project-root "$PROJECT_ROOT" \
  --global-root "$GLOBAL_ROOT" \
  --case-file "$REPO_ROOT/docs/memorywiki-golden-cases.json" \
  --strategy hybrid \
  --embedding local \
  --graph local \
  --ranker score \
  --granularity-router entropy \
  --association-reranker local \
  --index-schema-version 3 \
  --min-mrr 1.0 \
  --format human
