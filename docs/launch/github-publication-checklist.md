# GitHub Publication Checklist

This checklist prepares MemoryWiki for a public GitHub launch without publishing
from the local machine.

## 1. Access And Ownership

- Use `gh auth login`, SSH, or a fine-grained token. Do not use account
  passwords in prompts, shell history, or config files.
- Confirm the final repository owner and name.
- Create the repository as private first, then switch to public after CI and
  repository settings are ready.

## 2. Public-Clean Gate

- Keep the public tree on a clean root commit.
- Run the public-clean test.
- Scan working tree paths, text, archives, and git history for secrets, private
  paths, old project names, and real memory content.
- Confirm example memory uses synthetic data only.

## 3. Repository Setup

- Add description: `Local-first Memory Wiki for AI agents`.
- Add topics: `agent-memory`, `local-first`, `mcp`, `knowledge-management`,
  `pkm`, `llm`, `retrieval`, `markdown`, `ai-agents`, `mcp-server`,
  `markdown-notes`, `local-ai`.
- Enable Issues, Pull Requests, Discussions, secret scanning, push protection,
  Dependabot alerts, and Dependabot updates.
- Prefer squash merges and automatic branch deletion.
- Disable unused features until there is a reason to turn them on.

Current private-repo status:

- Description, topics, Issues, Discussions, squash-only merge, and automatic
  branch deletion are configured.
- Wiki and Projects are disabled.
- Dependabot vulnerability alerts are enabled.
- Branch protection, secret scanning, push protection, and private
  vulnerability reporting must be rechecked after the repository is public or
  account-plan support is available.

## 4. Governance Files

- `LICENSE`
- `README.md`
- `README.zh.md`
- `ROADMAP.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `.github/ISSUE_TEMPLATE/*`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/CODEOWNERS` after replacing the placeholder owner.

## 5. CI And Release Gates

- Run tests on Python 3.9 through 3.13.
- Include Linux, macOS, and Windows.
- Run public-clean, golden eval, mini benchmark smoke, and release checker.
- Protect `main` after the first green CI run.

## 6. Release

- Start with `v0.1.0`.
- Tag only after CI is green.
- Attach release notes, benchmark output, release manifest, and MCP contract.
- Do not move published tags.

## 7. Launch Assets

- 20-second terminal GIF.
- Architecture diagram showing local files, CLI, MCP, and write gates.
- Screenshot of recall output with provenance or warnings.
- One five-command demo that requires no hosted service and no API key.

Prepared assets:

- `docs/assets/memorywiki-quickstart.gif`
- `docs/assets/recall-output.svg`
- `docs/launch/demo-assets.md`
- `docs/launch/launch-copy.md`
- `docs/launch/v0.1.0-release-notes.md`

## 8. Launch Sequence

- Quiet public GitHub launch.
- Ask a small trusted group to try the quickstart.
- Fix install and docs issues first.
- Then launch externally with a problem-first story.

## 9. Feedback Loop

- Use Issues for reproducible work.
- Use Discussions for Q&A, memory layout examples, and design proposals.
- Label feedback as bug, docs confusion, privacy concern, integration request,
  benchmark request, or positioning confusion.
- Publish a short weekly note on what changed from feedback.
