"""Prompt-driven memory compression adapter used by local and model backends."""

from __future__ import annotations

from memory_system.models import CompactionResult
from memory_system.prompts import build_compaction_prompt
from memory_system.sanitizer import sanitize_text


class MemoryCompressor:
    def __init__(
        self,
        client,
        model,
        core_memory_char_limit,
        user_memory_char_limit,
    ):
        self.client = client
        self.model = model
        self.core_memory_char_limit = core_memory_char_limit
        self.user_memory_char_limit = user_memory_char_limit

    def compact(
        self,
        old_conversation,
        current_memory,
        current_user,
        today_episodic,
    ):
        prompt = build_compaction_prompt(
            old_conversation=sanitize_text(old_conversation),
            current_memory=sanitize_text(current_memory),
            current_user=sanitize_text(current_user),
            today_episodic=sanitize_text(today_episodic),
            core_memory_char_limit=self.core_memory_char_limit,
            user_memory_char_limit=self.user_memory_char_limit,
        )
        payload = self.client.compact_memory(model=self.model, prompt=prompt)
        required_keys = ("updated_memory", "updated_user", "episodic_append")
        missing_keys = [key for key in required_keys if key not in payload]
        if missing_keys:
            raise ValueError(
                "Compaction payload missing required keys: " + ", ".join(missing_keys)
            )
        non_string_keys = [
            key for key in required_keys if not isinstance(payload[key], str)
        ]
        if non_string_keys:
            raise ValueError(
                "Compaction payload values must be strings for keys: "
                + ", ".join(non_string_keys)
            )
        updated_memory = sanitize_text(payload["updated_memory"])
        updated_user = sanitize_text(payload["updated_user"])
        episodic_append = sanitize_text(payload["episodic_append"]).strip()
        if not updated_memory.startswith("# Core Memory"):
            raise ValueError("Compaction payload updated_memory must start with # Core Memory")
        if not updated_user.startswith("# User Memory"):
            raise ValueError("Compaction payload updated_user must start with # User Memory")
        return CompactionResult(
            updated_memory=updated_memory[: self.core_memory_char_limit],
            updated_user=updated_user[: self.user_memory_char_limit],
            episodic_append=episodic_append,
        )
