# Security Policy

MemoryWiki is a local-first memory system. Security and privacy reports are
treated as first-class project work.

## Supported Versions

The public project is starting at `0.1.x`. Security fixes will target the latest
published release and `main`.

## Reporting A Vulnerability

Once the GitHub repository is public, prefer GitHub private vulnerability
reporting if it is enabled. If it is not enabled yet, open a minimal public issue
that describes the affected component without posting secrets, tokens, real
memory files, private paths, or exploit payloads that would expose other users.

Please include:

- Affected version or commit.
- Operating system and Python version.
- A safe reproduction using synthetic data.
- Expected impact.
- Whether the issue affects CLI, MCP, source ingestion, recall, deletion, or
  packaging.

## Security Model

- Memory content is data, not instructions.
- MCP writes are disabled by default and require explicit environment gates.
- Global memory writes require a separate explicit gate.
- Retrieval indexes are rebuildable sidecars, not canonical memory.
- Source ingestion is constrained to the configured source area.
- Forget/delete flows are dry-run-first and require a reason.

## Out Of Scope

- Reports that require access to a user's private memory files.
- Reports based only on social engineering a maintainer.
- Hosted-service assumptions; MemoryWiki does not run a hosted memory service by
  default.
