# Public Go-Live Runbook

Use this runbook for the final public switch. It separates safe automated
checks from manual GitHub account and repository actions.

## 1. Final Assets

- Replace `docs/assets/memorywiki-avatar.png` with the final 400x400 avatar.
- Replace `docs/assets/memorywiki-social-preview.png` with the final 1280x640
  social preview.
- Keep the matching SVG sources in `docs/assets/` when available.
- Re-run the public-clean test after replacing binaries.

The prepared placeholder files are safe to publish, but they are not the final
brand assets if a separate image-generation pass is planned.

## 2. Clean History Decision

Before switching the repository public, choose exactly one history policy:

- **Keep current history**: safest operationally; no force push.
- **Squash private preparation commits**: cleaner public timeline; requires an
  explicit force-push approval before the repository is public.
- **Create a clean public mirror**: cleanest public timeline; slower, because
  CI and settings need to be verified again on the mirror.

Do not rewrite history after the repository is public unless a secret exposure
requires it.

## 3. Required Verification

```bash
python3 -m pytest tests -q
python3 -m pytest tests/test_public_clean.py -q
python3 -m build --sdist --wheel --outdir /tmp/memorywiki-dist
python3 -m twine check /tmp/memorywiki-dist/*
python3 memorywiki_mcp_contract.py --verify docs/memorywiki-mcp-v1-contract.json --format human
```

Then confirm CI is green on the commit that will become public.

## 4. GitHub Settings

- Keep Issues and Discussions enabled.
- Keep Wiki and Projects disabled until there is a concrete need.
- Prefer squash merges and automatic branch deletion.
- Enable or confirm secret scanning, push protection, Dependabot alerts, and
  private vulnerability reporting where the account plan supports them.
- Add branch protection for `main` after the first public green CI run.

## 5. Manual Profile And Social Preview

- Upload the avatar through GitHub account settings.
- Upload the social preview through repository Settings -> Social preview.
- Pin the repository on the account profile after the repository is public.
- Confirm the public profile, bio, website, and repository description look
  consistent on a logged-out browser session.

## 6. Public Switch

Only switch visibility after an explicit approval in the current work session.
After switching:

1. Open the public repository page in a logged-out browser.
2. Check README rendering, badges, quickstart GIF, and social preview.
3. Open Actions and confirm the latest run is green.
4. Run one fresh clone smoke test in a temporary directory.
5. Tag `v0.1.0` only after the public page and CI both look correct.
