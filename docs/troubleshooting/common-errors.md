# Common Errors

Use this page when a command fails, recall returns nothing, or an MCP client
cannot connect.

## 1. Recall returns empty results

Cause: the selected memory root has no matching memories, or the wrong scope was
used.

Fix:

```bash
memorywiki-list --project-root <root> --scope project --kind all
memorywiki-recall --project-root <root> --scope project --query "<topic>" --strategy hybrid
```

## 2. MCP connection fails

Cause: MCP extra is not installed, the Python path is wrong, or the client config
points at a stale checkout.

Fix:

```bash
python -m pip install -e ".[mcp]"
memorywiki-mcp-doctor --repo-root "$(pwd)" --config .mcp.json --format human
```

## 3. Index rebuild fails

Cause: the memory root is not a real directory, contains unsafe symlinks, or is
not writable.

Fix:

```bash
memorywiki-index-maintain --project-root <root> --scope project --format human
```

Then remove unsafe symlinks or fix permissions before retrying with `--write`.

## 4. Path traversal or sandbox error

Cause: a source path tries to escape `sources/`, or a generated path is not under
the selected memory root.

Fix: copy source files into `<memory-root>/sources/` and pass only the filename
or a safe relative path.

## 5. Python version incompatibility

Cause: MCP dependencies require Python 3.10+, while the core CLI supports
Python 3.9+.

Fix:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[mcp]"
```

## 6. Windows shell quoting problems

Cause: PowerShell and POSIX shells quote paths differently.

Fix: wrap paths in double quotes and prefer `python -m <module>` when debugging.

## 7. Permission denied

Cause: the memory root or audit/index files are owned by another user or are
read-only.

Fix:

```bash
ls -la <memory-root>
```

Make the project directory writable by the current user. Do not run MemoryWiki
with elevated privileges unless you understand the file ownership impact.

## 8. Environment variables are ignored

Cause: command-line flags take precedence over environment variables.

Fix: remove conflicting flags or check the effective roots:

```bash
memorywiki-mcp-doctor --format human
```

## 9. Dependency installation fails

Cause: old `pip`, unsupported Python, or optional extras installed on an
unsupported runtime.

Fix:

```bash
python -m pip install -U pip
python -m pip install -e ".[dev]"
python -m pip install -e ".[mcp]"  # Python 3.10+
```

## 10. Disk space is low

Cause: backups, build artifacts, or generated indexes consume local storage.

Fix:

```bash
du -sh . .agent_memory 2>/dev/null
```

Remove temporary build artifacts and old local backups you no longer need.

## 11. `sources/` ingest says the directory is missing

Cause: source ingest only reads from the memory root's `sources/` sandbox.

Fix:

```bash
mkdir -p <memory-root>/sources
cp <file> <memory-root>/sources/
memorywiki-ingest-source --root <memory-root> --source <file-name> ...
```

## 12. Write tools are denied through MCP

Cause: MCP is read-first by default.

Fix: only for explicit user-approved writes, set:

```text
MEMORY_MCP_WRITE_ENABLED=true
MEMORY_GLOBAL_WRITE_ENABLED=true  # only for global writes
```

## 13. `memorywiki-list` does not show procedural memories with a concept filter

Cause: concept filters currently apply to semantic memories only.

Fix: omit `--concept` or use `--kind semantic` when filtering by concept.

## 14. Recall warns that an index is stale or tampered

Cause: canonical memory changed after the retrieval sidecar was built.

Fix:

```bash
memorywiki-index-maintain --project-root <root> --scope project --write
```

## 15. Package commands are not found after install

Cause: the active shell is not using the same virtual environment where the
package was installed.

Fix:

```bash
which python
python -m pip show memorywiki
python -m pip install -e ".[mcp]"
```
