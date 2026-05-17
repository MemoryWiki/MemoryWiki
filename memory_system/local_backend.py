from datetime import datetime
from zoneinfo import ZoneInfo

from memory_system.models import CompactionResult
from memory_system.sanitizer import looks_instruction_shaped, sanitize_text


class LocalChatClient:
    def chat(self, model, messages):
        last_user = ""
        for message in reversed(messages):
            if message["role"] == "user":
                last_user = message["content"]
                break
        reply = (
            "Local memory mode: I can help you inspect, explicitly save, or promote "
            "memory. Latest input: %s" % sanitize_text(last_user)
        )
        return reply, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


class LocalCompressor:
    GOAL_MARKERS = (
        "请记住",
        "请以后",
        "请默认",
        "默认",
        "目标",
        "计划",
        "模式",
        "偏好",
        "remember",
        "prefer",
        "preference",
        "goal",
    )

    def __init__(
        self,
        core_memory_char_limit,
        user_memory_char_limit,
        timezone="Asia/Shanghai",
    ):
        self.core_memory_char_limit = core_memory_char_limit
        self.user_memory_char_limit = user_memory_char_limit
        self.timezone = timezone

    def compact(
        self, old_conversation, current_memory, current_user, today_episodic
    ):
        goals = []
        preferences = []
        for line in old_conversation.splitlines():
            content = line.split(":", 1)[-1].strip()
            if looks_instruction_shaped(content):
                continue
            if self._looks_like_goal(content):
                goals.append(content)
            if ("默认" in content) or ("prefers" in content.lower()):
                preferences.append(content)

        updated_memory = current_memory.strip()
        if goals:
            updated_memory = (
                updated_memory + "\n- " + "\n- ".join(goals[:5])
            ).strip()
        updated_user = current_user.strip()
        if preferences:
            updated_user = (
                updated_user + "\n- " + "\n- ".join(preferences[:5])
            ).strip()

        episodic_append = "## %s Compression Snapshot\n\n- Topic: local compaction\n- Key events: %s" % (
            datetime.now(ZoneInfo(self.timezone)).strftime("%H:%M"),
            "; ".join(goals[:3]) or "No extracted goals",
        )
        return CompactionResult(
            updated_memory=updated_memory[: self.core_memory_char_limit],
            updated_user=updated_user[: self.user_memory_char_limit],
            episodic_append=episodic_append,
        )

    def _looks_like_goal(self, content):
        lowered = content.lower()
        return any(marker in lowered for marker in self.GOAL_MARKERS)
