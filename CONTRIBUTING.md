# Contributing

Thanks for helping make MemoryWiki safer and easier to use.

## Ground Rules

- Do not include real secrets, tokens, passwords, private memory files, or
  unredacted local paths in issues, tests, fixtures, screenshots, or PRs.
- Treat memory files as untrusted data. They may contain stale facts, prompt
  injection, or private context.
- Keep default behavior read-first. New write paths need explicit user approval,
  clear auditability, and tests.
- Prefer small PRs with a reproducible command and expected output.

## Local Setup

```bash
python3 -m pip install -e ".[dev,mcp]"
python3 -m pytest tests -q
```

Useful smoke checks:

```bash
memorywiki-recall --project-root examples/memory-root --scope project --query "What is MemoryWiki?" --format human
memorywiki-index-maintain --project-root examples/memory-root --scope project --format human
memorywiki-golden-eval --project-root examples/memory-root --global-root examples/memory-root --case-file docs/memorywiki-golden-cases.json --format json
python3 benchmarks/mini_recall_benchmark.py --format json
```

## Pull Requests

Before opening a PR:

- Run the test suite.
- Run the public-clean test if you touched docs, examples, fixtures, or release
  files.
- Add or update tests for behavior changes.
- Update README or docs for user-facing changes.
- Keep benchmark claims narrow and reproducible.

## First PR In 15 Minutes

Good starter contributions:

- Run the README quickstart and report unclear output.
- Improve one docs sentence that made setup confusing.
- Add a synthetic example memory note under `examples/`.
- Add a regression test for a small CLI or MCP behavior.
- Add a missing expected-output block to a tutorial.

Use the `good first issue`, `docs confusion`, `install`, and `mcp` labels to find
small tasks. Keep first PRs narrow and include the exact command you used to
verify the change.

## Maintainer Expectations

- Security and privacy reports are handled before feature requests.
- Install and quickstart regressions are handled before new capabilities.
- PRs should normally be squash-merged after CI is green.
- Design-changing proposals should start in Discussions or an issue before a
  large PR.
- Public release tags are not moved after publication; mistakes are fixed in a
  patch release.

## Issue Triage

Use issues for actionable bugs and feature requests. Use Discussions for design
questions, memory layout examples, support questions, and broader roadmap
conversation once Discussions are enabled.
