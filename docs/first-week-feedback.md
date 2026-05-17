# First-Week Feedback Loop

For v0.1.x, the priority is first-user success, not new architecture.

## Daily Triage

- Check new Issues and Discussions.
- Label every report: `install`, `mcp`, `docs confusion`, `privacy`,
  `retrieval`, `benchmark`, or `roadmap`.
- Reproduce install and MCP setup problems before changing code.
- Prefer docs fixes when a feature already works but the path is unclear.

## v0.1.1 Scope

Allowed:

- README and installation clarity.
- MCP client setup guides.
- Better example memory roots.
- Windows/macOS/Linux setup fixes.
- Public-clean and packaging fixes.
- Small retrieval correctness fixes backed by tests.

Deferred:

- Hosted sync.
- Automatic background saving.
- Large benchmark claims without reproducible scripts.
- New write automation that bypasses explicit user approval.

## Weekly Note Template

```markdown
## MemoryWiki weekly note

What users tried:

What broke:

What changed:

Open questions:

Next release focus:
```
