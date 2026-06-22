# Memory Review Follow-Ups

This note records review items intentionally deferred after security and
correctness passes. They are public roadmap items, not private launch notes.

## Deferred Architecture Items

- `history.jsonl` and `tokens.jsonl` history rotation is not implemented in
  this pass. A monthly shard such as `history-YYYY-MM.jsonl` is a reasonable
  next step once runtime usage volume is clearer.
- SQLite FTS is not implemented in this pass. It should be considered when
  search latency or multi-run indexing becomes a real bottleneck.
- Background compaction and retention jobs are not implemented in this pass.
  They should be designed with the future agent runtime scheduler rather than
  added as ad hoc file maintenance.

## Already Addressed

- Global memory promotion requires an explicit write flag and CLI confirmation.
- Episodic date access rejects path traversal.
- Memory compaction sanitizes inputs and validates returned headings.
- JSONL search skips corrupt rows.
- File writes use atomic replace or single `os.write` append paths.
- The optional OpenAI backend has timeout, retry, and output-token limits, and
  the base local-first install no longer depends on the OpenAI SDK.
