# MCP Example

`.mcp.example.json` shows how an MCP-capable client can connect to MemoryWiki in read-only mode.

Generate a local config:

```bash
memorywiki-mcp-config --output .mcp.json
memorywiki-mcp-doctor --config .mcp.json
```

Writes are disabled unless `MEMORY_MCP_WRITE_ENABLED=true` is explicitly set. Global writes also require `MEMORY_GLOBAL_WRITE_ENABLED=true`.
