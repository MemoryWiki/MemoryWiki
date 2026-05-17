# Release Playbook

Use this playbook before tagging a public MemoryWiki release.

## Preflight

```bash
python3 -m pip install -e ".[dev,mcp]"
python3 -m pytest tests -q
python3 -m pytest tests/test_public_clean.py -q
memorywiki-golden-eval --project-root examples/memory-root --global-root examples/memory-root --case-file docs/memorywiki-golden-cases.json --format json
python3 benchmarks/mini_recall_benchmark.py --format json
```

## Release Check

```bash
MEMORYWIKI_RELEASE_TMP="$(python3 - <<'PY'
import tempfile
from pathlib import Path
print(Path(tempfile.gettempdir()).resolve() / "memorywiki-release")
PY
)"
rm -rf "$MEMORYWIKI_RELEASE_TMP"
mkdir -p "$MEMORYWIKI_RELEASE_TMP/backups"

memorywiki-backup \
  --root "." \
  --backup-root "$MEMORYWIKI_RELEASE_TMP/backups" \
  --name memorywiki-core \
  --message "release smoke backup" \
  --format json

memorywiki-release-check \
  --repo-root . \
  --project-root examples/memory-root \
  --global-root examples/memory-root \
  --config examples/mcp/.mcp.example.json \
  --mcp-contract docs/memorywiki-mcp-v1-contract.json \
  --golden-case-registry docs/memorywiki-golden-cases.json \
  --backup-root "$MEMORYWIKI_RELEASE_TMP/backups" \
  --backup-name memorywiki-core \
  --manifest-out "$MEMORYWIKI_RELEASE_TMP/memorywiki-release-manifest.json" \
  --format json
```

## Build Artifacts

```bash
python3 -m pip install build twine
python3 -m build --sdist --wheel --outdir "$MEMORYWIKI_RELEASE_TMP/dist"
python3 -m twine check "$MEMORYWIKI_RELEASE_TMP"/dist/*
```

## Tagging

Tag only after CI is green:

```bash
git tag -a v0.1.0 -m "MemoryWiki v0.1.0"
```

Do not retag or move a published tag. If a release is wrong, publish a patch
release.

## Release Notes Template

```markdown
## MemoryWiki v0.1.0

First public release candidate for local-first agent memory.

### Highlights

- Local Markdown/JSONL memory layout.
- Read-first recall through CLI and MCP.
- Explicit write gates for save, ingest, forget, and global writes.
- Source provenance, update logs, and dry-run deletion.

### Verification

- Tests:
- Public-clean:
- Golden eval:
- Mini benchmark:
- Release checker:

### Known Limits

- Early Python-first CLI.
- No hosted sync service.
- Benchmarks are small public smoke tests, not broad claims.
```
