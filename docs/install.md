# Installation Guide

MemoryWiki is local-first. The default install does not require an API key or a
hosted service.

## Recommended First Run

Use the repository checkout when trying MemoryWiki for the first time. This keeps
examples, docs, and tests beside the CLI commands.

```bash
git clone https://github.com/MemoryWiki/MemoryWiki.git
cd MemoryWiki
python3 -m pip install -e ".[mcp]"
memorywiki-recall --project-root examples/memory-root --scope project --query "What is MemoryWiki?" --strategy hybrid --embedding local --graph local --format human
```

MCP support requires Python 3.10 or newer. If you only want the core CLI, use:

```bash
python3 -m pip install -e .
```

## Compatibility Matrix

| Feature | Python 3.9 | Python 3.10+ | Notes |
| --- | --- | --- | --- |
| Core CLI | Yes | Yes | Local files, recall, list, index, backup |
| MCP server | No | Yes | Install with `.[mcp]` |
| OpenAI optional backend | Yes | Yes | Install with `.[openai]` and set credentials |
| Development tooling | Yes | Yes | Install with `.[dev]` |

## Platform Notes

- **macOS/Linux**: use `python3 -m venv .venv` and activate with
  `. .venv/bin/activate`.
- **Windows PowerShell**: use `py -3.12 -m venv .venv` and activate with
  `.venv\Scripts\Activate.ps1`.
- **All platforms**: run `python -m pip install -U pip` before installing extras.

## Isolated Virtual Environment

```bash
git clone https://github.com/MemoryWiki/MemoryWiki.git
cd MemoryWiki
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[mcp]"
```

## Install From GitHub

This is useful for a quick local smoke without editing the repository:

```bash
python3 -m venv /tmp/memorywiki-smoke
. /tmp/memorywiki-smoke/bin/activate
python -m pip install "memorywiki[mcp] @ git+https://github.com/MemoryWiki/MemoryWiki.git@v0.1.0"
memorywiki-recall --help
```

## Optional Backends

The base install uses local files and deterministic local tooling. Install the
optional OpenAI dependency only when you intentionally want the OpenAI backend:

```bash
python3 -m pip install -e ".[openai]"
```

Then set the backend explicitly:

```bash
export MEMORY_BACKEND=openai
export OPENAI_API_KEY="<your key>"
```

## Quick Health Check

```bash
python3 -m pytest tests/test_public_clean.py -q
memorywiki-index-maintain --project-root examples/memory-root --scope project --format human
memorywiki-golden-eval --project-root examples/memory-root --global-root examples/memory-root --case-file docs/memorywiki-golden-cases.json --format json
```

## Troubleshooting

- If `memorywiki-mcp` is missing, reinstall with `python3 -m pip install -e ".[mcp]"`.
- If MCP dependencies fail on Python 3.9, use Python 3.10 or newer.
- If a recall command warns that an index is stale, run
  `memorywiki-index-maintain --project-root <root> --scope project --write`.
- If you are testing real project memory, start with project scope before adding
  a global memory root.
- For more cases, see `docs/troubleshooting/common-errors.md`.
