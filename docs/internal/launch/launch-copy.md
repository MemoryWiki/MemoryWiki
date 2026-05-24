# Launch Copy Pack

Use this as the source for public launch posts. Publish only after the repository
is public, CI is green, and the v0.1.0 release candidate is attached.

## Show HN

Title:

```text
Show HN: MemoryWiki - local memory wiki for AI agents with injection defense
```

URL:

```text
https://github.com/MemoryWiki/MemoryWiki
```

Text:

```text
Hi HN, I built MemoryWiki because coding agents kept losing useful project
context between sessions, and I wanted memory I could inspect, diff, back up,
and delete.

MemoryWiki keeps canonical memory in local Markdown/JSONL files: sessions,
daily episodes, semantic memories with confidence/strength/source_refs/update_log,
procedural workflows, source documents, and rebuildable retrieval indexes.
Recall works through CLI and a read-first MCP server. The default path is local
and does not require an API key.

The design choices I would especially value feedback on:

1. Cognitive layering vs. one flat vector store. The bet is that episodic
   "what happened", semantic "what is true", and procedural "how to do it"
   should have different metadata and lifecycles.
2. Bilingual instruction-shaped memory neutralization. English and Chinese
   strings that look like memory poisoning, such as "ignore previous
   instructions" or "忽略之前指示", are neutralized before recall/read output.
   I do not think regex is a complete prompt-injection solution; I am treating
   it as one layer in a defense-in-depth model.
3. Local file safety: path containment, symlink rejection, atomic writes,
   audit logs, dry-run-first forget/delete, and env-gated MCP writes.

This is early v0.1.0 software, Apache-2.0. The repo includes a synthetic memory
root, a two-minute quickstart, a mini recall benchmark, public-clean checks,
and CI across OS/Python versions. I am not claiming large benchmark wins yet;
the next milestone is a reproducible larger retrieval eval and more real client
setup reports.
```

Do not use the old internal project history in the post. Keep the launch story
about the public repo, the local-first design, and specific feedback requests.

## Show HN Reply Prep

Likely questions and concise answers:

- **How is this different from a vector database?** Vector indexes are useful
  retrieval sidecars here, not canonical memory. The canonical layer is human
  readable Markdown/JSONL with provenance, update history, and explicit memory
  kinds.
- **Does regex stop prompt injection?** No. The sanitizer is one layer. Memory
  is still treated as untrusted context data, outputs are neutralized before
  recall/read surfaces, MCP writes are gated, and deletes are audited.
- **Why include Chinese patterns?** The project is designed for bilingual agent
  use. Chinese instruction-shaped memory should not get a free pass just
  because many safety examples are English-only.
- **Does it automatically save chats?** No. Durable writes require explicit
  user intent: save a session, crystallize an answer, ingest a source, forget a
  memory, or write global memory.
- **Why not just use a notes app?** Notes apps are good canonical stores for
  humans. MemoryWiki is an agent-memory workflow on top of local files: recall,
  MCP, provenance, confidence/strength, review, and dry-run delete.

Post timing:

- Prefer Tuesday to Thursday, 7-9 AM US Pacific.
- Stay available for the first hour and reply with concrete issue links when a
  comment identifies a bug, confusing doc, or missing example.
- Do not ask for upvotes or coordinate votes.
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
