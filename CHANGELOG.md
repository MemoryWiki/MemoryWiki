# Changelog

All notable public changes to MemoryWiki will be documented here.

The project uses semantic versioning after the first public release.

## 0.1.0 - Draft

Initial public release draft. The repository is public, but tagged release
artifacts are prepared only after the release checklist is green.

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

Before release:

- Switch the repository from private to public after final approval.
- Recheck branch protection, secret scanning, push protection, and private
  vulnerability reporting after public/account-plan support is available.
- Generate the release manifest and build artifacts from a clean commit.
- Tag the release after CI is green.
