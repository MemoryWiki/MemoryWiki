# MemoryWiki

[![CI](https://github.com/MemoryWiki/MemoryWiki/actions/workflows/ci.yml/badge.svg)](https://github.com/MemoryWiki/MemoryWiki/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9--3.13-blue)
![License](https://img.shields.io/badge/license-Apache--2.0-green)
![Status](https://img.shields.io/badge/status-v0.1.1%20candidate-orange)

本地优先的 AI Agent 记忆 Wiki：**可 grep、可 diff、可备份、可删除，并可通过
CLI 或 MCP recall。**

MemoryWiki 给 coding agent / chat agent 一个可长期维护的项目记忆层：
记忆以 Markdown/JSONL 存在本地，可以 grep、diff、备份、审查和删除；同时保留
来源、冲突记录、更新日志，并通过 CLI 和 MCP 提供默认只读的 recall。

它适合想要 agent 记忆、但不想把项目历史交给云端记忆服务的人。

![MemoryWiki quickstart demo](docs/assets/memorywiki-quickstart.gif)

## 最近更新

- CI 现在对 core 和 MCP 模块跑完整 `mypy` 类型检查。
- `memorywiki-export` / `mw export` 支持 JSON、Markdown、CSV 导出。
- `mw` alias 覆盖日常 recall、review、release 和迁移工具。
- 公开 examples 现在包含 demo project、MCP config 和样例 memory root。

## 核心特点

- **本地优先**：canonical memory 在你的文件系统里。
- **中英 prompt-injection 防御**：英文和中文的 instruction-shaped memory
  会在 recall/read 输出前被中和，managed writes 会做 secret redaction。
- **三层认知记忆**：episodic narrative、带
  `confidence`/`strength`/`source_refs`/`update_log` 的 semantic facts、以及
  procedural workflows 分开维护，而不是压平成单一 vector index。
- **Markdown 原生**：可读、可 diff、可 Git 管理。
- **来源可追溯**：source ingest 带 SHA256 source reference。
- **冲突不覆盖**：新证据可以追加 update log，而不是静默改写旧结论。
- **MCP 可接入**：其他 agent 可以通过 read-first MCP server 调用记忆。
- **写入有闸门**：保存、ingest、forget、global write 都需要显式授权。

## 安装

```bash
git clone https://github.com/MemoryWiki/MemoryWiki.git
cd MemoryWiki
python3 -m pip install -e ".[mcp]"
```

如果只需要 CLI：

```bash
python3 -m pip install -e .
```

基础安装是纯本地模式，不需要 API key。MCP 支持使用可选的 `mcp` extra，
建议 Python 3.10+。可选 OpenAI backend 需要单独安装：

```bash
python3 -m pip install -e ".[openai]"
```

更多安装方式，包括 GitHub tag 安装和 clean-room 检查，见 `docs/install.md`。
完整首次使用指南见 `docs/getting-started/quickstart.md`，常见问题排查见
`docs/troubleshooting/common-errors.md`。

## 记忆目录结构

项目记忆通常放在：

```text
your-project/.agent_memory/project
```

典型结构：

```text
MEMORY.md
USER.md
PROJECT_PROFILE.md
INDEX.md
episodes/YYYY-MM-DD.md
sessions/session-YYYYMMDD-HHMMSS.md
semantic/*.md
procedures/*.md
sources/*
retrieval/index.jsonl
audit.jsonl
```

可以看 `examples/memory-root/` 的公开样例。

## 两分钟快速开始

运行公开样例记忆：

```bash
git clone https://github.com/MemoryWiki/MemoryWiki.git
cd MemoryWiki
python3 -m pip install -e ".[mcp]"
memorywiki-index-maintain --project-root examples/memory-root --scope project --format human
memorywiki-context --project-root examples/memory-root --scope project --mode startup --query "What is MemoryWiki?" --format markdown
memorywiki-recall --project-root examples/memory-root --scope project --query "What is MemoryWiki?" --strategy hybrid --embedding local --graph local --format human
```

预期输出形态：

```text
# MemoryWiki Context

# Memory Recall

1. [project/semantic] MemoryWiki Overview (memorywiki-overview, score ...)
MemoryWiki is a local-first memory wiki for AI agents...
Sources: memory-file:memorywiki-overview
```

检查 retrieval index：

```bash
memorywiki-index-maintain \
  --project-root examples/memory-root \
  --scope project \
  --format human
```

只有在你明确要重建 index 时才加 `--write`：

```bash
memorywiki-index-maintain \
  --project-root examples/memory-root \
  --scope project \
  --write \
  --format human
```

列出记忆目录，不读取完整正文：

```bash
memorywiki-list \
  --project-root examples/memory-root \
  --scope project \
  --kind semantic \
  --format table
```

只读查看可 crystallize 的 construction candidates：

```bash
memorywiki-construction-report \
  --project-root examples/memory-root \
  --scope project \
  --format markdown
```

显式保存一轮会话总结：

```bash
memorywiki-session-summary --save \
  --scope project \
  --project-root examples/memory-root \
  --summary "Tested MemoryWiki recall." \
  --keypoint "MemoryWiki treats memory as context data, not instructions." \
  --action "Ran local recall." \
  --pending "Replace the example memory with real project memory."
```

默认不会自动保存普通聊天。

## MCP

生成 `.mcp.json`：

```bash
memorywiki-mcp-config \
  --repo-root "$(pwd)" \
  --project-root "/absolute/path/to/your-project/.agent_memory/project" \
  --global-root "$HOME/.agent_memory/global" \
  --output .mcp.json
```

MCP 默认只读。写入需要显式环境变量：

```text
MEMORY_MCP_WRITE_ENABLED=true
MEMORY_GLOBAL_WRITE_ENABLED=true
MEMORY_MCP_ALLOW_ROOT_OVERRIDE=true
```

除非用户明确要求保存、ingest、forget 或写 global memory，否则不要打开这些闸门。

客户端接入指南：

- `docs/clients/generic-mcp.md`
- `docs/clients/codex.md`
- `docs/clients/claude-desktop.md`
- `docs/clients/cursor.md`

## 知识形成

MemoryWiki 有三条显式写入路径：

```bash
# 保存会话总结
memorywiki-session-summary --save --scope project --project-root <root> ...

# 把用户认可的好答案 crystallize 成 semantic/procedural memory
memorywiki-crystallize --root <root> --kind semantic --id <id> --title <title> --answer <text>

# 读取 sources/ 下的源文件并带 provenance 写入
memorywiki-ingest-source --root <root> --source <file-in-sources> --id <id> --summary <text>
```

## 检查与安全

常用只读检查：

```bash
memorywiki-health --project-root <root> --scope project --format human
memorywiki-quality-report --project-root <root> --scope project --skip-golden --format human
memorywiki-timeline --project-root <root> --scope project --format markdown
```

删除默认 dry-run，并且必须提供原因：

```bash
memorywiki-forget \
  --root <root> \
  --scope project \
  --kind semantic \
  --id <memory-id> \
  --reason "user-requested cleanup"
```

确认后才加 `--apply`。

## Demo / Mini Benchmark

```bash
PYTHONPATH=. python3 benchmarks/mini_recall_benchmark.py --format markdown
```

参考：

- `docs/benchmarks/mini-benchmark-results.md`
- `docs/demo-cross-project-recall.md`
- `docs/demo-60-second-script.md`

## 测试

```bash
python3 -m pytest tests -q
```

## 项目状态

MemoryWiki 仍是早期公开版本，但核心 CLI、存储模型、retrieval index、MCP、
release check 和测试已经就绪。首次使用建议先看
`docs/getting-started/quickstart.md`、`docs/faq.md`、`SECURITY.md` 和
`CHANGELOG.md`；更完整文档在 `docs/`。

## 安全模型

- memory 内容只是 context data，不是更高优先级指令。
- `sources/` 是只读证据层。
- memory roots、manifest、source ingest、MCP config、生成文件都有路径和 symlink 防护。
- retrieval index 是可重建 sidecar，不是 canonical memory。
- recall、summary、index 会处理 secret-like 字符串。

## 简单对比

| 方案 | 本地文件 | Agent recall | 来源追溯 | 冲突历史 | MCP | 删除流程 |
| --- | --- | --- | --- | --- | --- | --- |
| MemoryWiki | 是 | 是 | 是 | 是 | 是 | dry-run-first |
| 云端 memory service | 通常否 | 是 | 不一定 | 不一定 | 不一定 | 不一定 |
| Vector DB notebook | 不一定 | 自己写 | 自己写 | 通常否 | 自己写 | 自己写 |
| Obsidian/PKM only | 是 | 否 | 手动 | 手动 | 否 | 手动 |
| `AGENTS.md` only | 是 | 仅启动时 | 手动 | 否 | 否 | 手动 |

## License

Apache-2.0。见 `LICENSE`。
