# Generic MCP Client Setup

Use this guide for any MCP-capable client that accepts a JSON server
configuration.

## 1. Install MemoryWiki

```bash
git clone https://github.com/MemoryWiki/MemoryWiki.git
cd MemoryWiki
python3 -m pip install -e ".[mcp]"
```

## 2. Create A Project Memory Root

Inside the project that should have memory:

```bash
mkdir -p .agent_memory/project
```

You can start with the synthetic example root until you are ready to use real
project memory:

```bash
memorywiki-recall --project-root examples/memory-root --scope project --query "What is MemoryWiki?" --strategy hybrid --embedding local --graph local --format human
```

## 3. Generate MCP Config

Run this from the MemoryWiki checkout:

```bash
memorywiki-mcp-config \
  --repo-root "$(pwd)" \
  --project-root "/absolute/path/to/your-project/.agent_memory/project" \
  --global-root "$HOME/.agent_memory/global" \
  --output .mcp.json
```

## 4. Safety Defaults

MemoryWiki MCP is read-first by default. Keep these variables unset unless the
user explicitly asks for writes:

```text
MEMORY_MCP_WRITE_ENABLED=true
MEMORY_GLOBAL_WRITE_ENABLED=true
MEMORY_MCP_ALLOW_ROOT_OVERRIDE=true
```

## 5. Smoke Test

```bash
memorywiki-mcp-smoke \
  --repo-root "$(pwd)" \
  --project-root examples/memory-root \
  --global-root examples/memory-root \
  --temp-write-check
```

Expected result: recall tools work, write tools remain blocked unless gates are
explicitly enabled.
