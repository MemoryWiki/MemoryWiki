# GitHub Profile And Visual Assets

This file tracks the launch-facing GitHub account and repository presentation.

## Account Profile

Recommended public profile fields:

```text
Name: MemoryWiki
Bio: Local-first memory wiki for AI agents. Markdown, MCP, retrieval, and auditable knowledge workflows.
Website: https://github.com/MemoryWiki/MemoryWiki
Pinned repository: MemoryWiki/MemoryWiki
```

Current limitation: the authenticated GitHub CLI token used for repository
automation has `repo` and `workflow` scopes but not the `user` scope, so profile
fields and avatar upload must be completed through GitHub Settings or after
refreshing the token with `user` scope.

If the token is refreshed later, the text fields can be applied with:

```bash
gh auth refresh -h github.com -s user
gh api user --method PATCH \
  -f name='MemoryWiki' \
  -f bio='Local-first memory wiki for AI agents. Markdown, MCP, retrieval, and auditable knowledge workflows.' \
  -f blog='https://github.com/MemoryWiki/MemoryWiki'
```

## Visual Assets

Prepared assets:

- `docs/assets/memorywiki-avatar.svg`
- `docs/assets/memorywiki-avatar.png`
- `docs/assets/memorywiki-social-preview.svg`
- `docs/assets/memorywiki-social-preview.png`
- `docs/assets/memorywiki-quickstart.gif`
- `docs/assets/recall-output.svg`

Manual GitHub UI steps:

1. Upload `docs/assets/memorywiki-avatar.png` as the account avatar.
2. Upload `docs/assets/memorywiki-social-preview.png` under repository Settings
   → Social preview.
3. Confirm the public profile is not set to private before launch, because a
   private profile hides activity from site-wide search and Trending surfaces.
4. Pin `MemoryWiki/MemoryWiki` on the profile after the repository is public.

## Short Pitch

```text
MemoryWiki is local-first Markdown memory for AI agents: grep it, diff it, back
it up, delete it, and recall it through CLI or MCP.
```
