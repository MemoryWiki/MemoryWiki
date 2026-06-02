# Changelog

All notable public changes to MemoryWiki will be documented here.

The project uses semantic versioning after the first public release.

## 0.1.1 - 2026-05-26

Stabilization pass for public-readiness and day-one operator UX.

Highlights:

- Full `memory_system` and `memorywiki_mcp` mypy gate now passes in CI.
- Coverage threshold is centralized in `pyproject.toml` with an 80% floor.
- Test fixtures are consolidated through `tests/conftest.py`.
- `mw merge` exposes the legacy daily-file migration helper.
- `memorywiki-export` and `mw export` provide read-only JSON, Markdown, and CSV
  exports for review, migration, or portable backups.
- `.memorywiki.toml` examples now document non-secret OpenAI backend settings
  while keeping API keys environment-only.
- Public examples include top-level orientation docs.
- Packaging now uses `include-package-data` instead of a long data-files block.

## 0.1.0 - 2026-05-25

Initial public release candidate. Tagged release artifacts are prepared only
after the release checklist is green.

Highlights:

- Local-first Markdown/JSONL memory layout.
- Sessions, episodes, semantic memory, procedures, sources, and hot files.
- Hybrid recall with local lexical, embedding-style, and graph-style signals.
- Retrieval index build and maintenance tools.
- Read-first MCP server with explicit write gates.
- Source ingestion with provenance.
- Crystallization workflow for user-approved durable memory.
- Dry-run-first forget/delete workflow.
- Public example memory root, mini benchmark, golden eval, and release checks.
- Launch-ready README, roadmap, issue templates, release notes draft, and demo
  assets.

Release checklist:

- Recheck branch protection, secret scanning, push protection, and private
  vulnerability reporting after public/account-plan support is available.
- Generate the release manifest and build artifacts from a clean commit.
- Tag the release after CI is green.
