# Launch Copy Pack

Use this as the source for public launch posts. Publish only after the repository
is public, CI is green, and the v0.1.0 release candidate is attached.

## Show HN

Title:

```text
Show HN: MemoryWiki - local-first Markdown memory for AI agents
```

Post:

```text
Hi HN, I built MemoryWiki: a local-first, Markdown-native memory system for AI agents.

The problem: agents forget project context, and hosted memory can be opaque. MemoryWiki keeps durable memory in local Markdown/JSONL files that you can grep, diff, back up, and delete. It has read-first CLI/MCP recall, source provenance, update/conflict logs, and explicit write gates for save/ingest/forget/global writes.

The project is early, but the core storage model, recall path, MCP server, synthetic example root, mini benchmark, public-clean checks, and release checks are in place.

I would especially value critique on:
- whether the memory layout is understandable,
- whether the quickstart is low-friction,
- whether the security/write-gate model feels right for local agent memory.
```

## X / Twitter Thread

1. Agents forget your repo. Hosted memory can be opaque. I built MemoryWiki: local-first, Markdown-native memory for AI agents.
2. MemoryWiki stores durable agent context as Markdown/JSONL: sessions, episodes, semantic notes, procedures, sources, and rebuildable retrieval indexes.
3. The pitch: grep it, diff it, back it up, delete it. No hosted service required for the default local workflow.
4. Recall works through CLI and MCP. MCP is read-first by default; writes require explicit environment gates.
5. Source ingest records SHA256-backed provenance, so durable memory can point back to evidence.
6. New facts can append update/conflict history instead of silently overwriting older conclusions.
7. Delete/forget is dry-run-first and reason-required. Generated retrieval indexes are rebuildable sidecars, not canonical memory.
8. The public repo includes synthetic example memory, a cross-project recall demo, a mini benchmark, public-clean tests, and release checks.
9. This is early v0.1 software. I am looking for feedback on install friction, memory layout, MCP setup, and docs clarity.
10. Repo: https://github.com/MemoryWiki/MemoryWiki

## Short English Blog Outline

Title: Why agent memory should be Markdown

- Agents need durable project context, not just chat personalization.
- Local files make memory inspectable and reversible.
- Markdown keeps memory readable; JSONL keeps logs and indexes machine-friendly.
- Provenance and conflict logs matter because knowledge changes.
- MCP should be read-first by default.
- Writes need explicit gates because memory can become a policy and privacy boundary.
- MemoryWiki v0.1 is an experiment in local-first agent memory.

## Chinese Launch Draft

标题：

```text
我做了一个本地优先的 Agent 记忆 Wiki：MemoryWiki
```

正文：

```text
AI Agent 最大的问题之一是：它会忘项目上下文。

MemoryWiki 的思路不是把记忆交给一个云端黑盒，而是把 durable memory 放回本地文件系统：Markdown/JSONL，可 grep、可 diff、可备份、可删除。

它支持：
- sessions / episodes / semantic / procedures / sources 分层记忆
- CLI 和 MCP recall
- 默认只读的 MCP
- source ingest 的 SHA256 provenance
- update/conflict log
- dry-run-first forget/delete
- public-clean 和 release check

现在是 v0.1 公开候选版。我最想要的反馈不是“功能越多越好”，而是：
1. README 能不能两分钟跑起来？
2. memory layout 是否直观？
3. MCP 默认只读 + 显式写入闸门是否合理？
4. 你会在哪类项目里用它？

Repo: https://github.com/MemoryWiki/MemoryWiki
```
