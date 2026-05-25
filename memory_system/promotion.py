"""Promotion helpers for copying stable project facts into global memory."""

import re

from memory_system.sanitizer import looks_instruction_shaped

SOURCE_COMMENT_RE = re.compile(r"\s*<!--\s*source:\s*[^>]+-->\s*$", re.IGNORECASE)


class PromotionManager:
    PLACEHOLDER_LINES = {
        "- No stable facts captured yet.",
        "- Keep track of the user's long-term goals and current work.",
    }

    def __init__(
        self,
        global_store,
        project_store,
        source_project,
        global_write_enabled=False,
        core_memory_char_limit=None,
        user_memory_char_limit=None,
    ):
        self.global_store = global_store
        self.project_store = project_store
        self.source_project = self._safe_source_label(source_project)
        self.global_write_enabled = global_write_enabled
        self.core_memory_char_limit = core_memory_char_limit
        self.user_memory_char_limit = user_memory_char_limit

    def promote_user_memory(self):
        self._promote(source="user")

    def promote_core_memory(self):
        self._promote(source="memory")

    def _promote(self, source):
        if not self.global_write_enabled:
            raise PermissionError(
                "Global memory promotion requires MEMORY_GLOBAL_WRITE_ENABLED=true"
            )

        if source == "user":
            current_global = self.global_store.read_user_memory()
            project_text = self.project_store.read_user_memory()
            writer = self.global_store.write_user_memory
            char_limit = self.user_memory_char_limit
        else:
            current_global = self.global_store.read_core_memory()
            project_text = self.project_store.read_core_memory()
            writer = self.global_store.write_core_memory
            char_limit = self.core_memory_char_limit

        merged_lines = []
        existing = set(
            self._dedupe_key(line) for line in current_global.splitlines() if line.strip()
        )
        for line in project_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped in self.PLACEHOLDER_LINES:
                continue
            if looks_instruction_shaped(stripped):
                continue
            promoted = f"{stripped}  <!-- source: {self.source_project} -->"
            dedupe_key = self._dedupe_key(stripped)
            if dedupe_key not in existing:
                merged_lines.append(promoted)
                existing.add(dedupe_key)

        if merged_lines:
            merged = current_global.rstrip() + "\n" + "\n".join(merged_lines) + "\n"
            if char_limit:
                merged = merged[:char_limit]
            writer(merged)

    def _dedupe_key(self, line):
        without_source = SOURCE_COMMENT_RE.sub("", line.strip())
        return " ".join(without_source.lower().split())

    def _safe_source_label(self, value):
        label = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value))
        label = re.sub(r"-{2,}", "-", label).strip(".-_")
        return label[:120] or "unknown"
