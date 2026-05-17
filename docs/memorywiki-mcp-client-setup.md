# MCP Client Setup

MemoryWiki exposes a local stdio MCP server named `memorywiki-memory`.

## Generate `.mcp.json`

From the MemoryWiki repository:

```bash
PYTHONPATH=. python3 -m memorywiki_mcp.client_config \
  --repo-root "$(pwd)" \
  --project-root "/absolute/path/to/your-project/.agent_memory/project" \
  --global-root "$HOME/.agent_memory/global" \
  --output /absolute/path/to/your-project/.mcp.json
```

The generated server is read-only by default.

## Write Gates

Only enable write gates for trusted local clients and explicit user-approved
operations:

```text
MEMORY_MCP_WRITE_ENABLED=true       # project writes
MEMORY_GLOBAL_WRITE_ENABLED=true    # global writes
MEMORY_MCP_ALLOW_ROOT_OVERRIDE=true # tool-provided root overrides
```

Without these gates, write tools such as session save, crystallize, source
ingest, and forget stay dry-run or denied.

## Smoke Test

```bash
PYTHONPATH=. python3 -m memorywiki_mcp.smoke_client \
  --python python3 \
  --repo-root "$(pwd)" \
  --project-root examples/memory-root \
  --global-root examples/memory-root \
  --query "MemoryWiki local-first memory"
```

## Doctor

```bash
PYTHONPATH=. python3 memorywiki_mcp_doctor.py \
  --python python3 \
  --project-root examples/memory-root \
  --global-root examples/memory-root \
  --config examples/mcp/.mcp.example.json \
  --format human
```

## Contract

```bash
PYTHONPATH=. python3 memorywiki_mcp_contract.py \
  --verify docs/memorywiki-mcp-v1-contract.json
```

The contract is useful for catching tool-schema drift before publishing a new
release.
