"""Live Markdown/JSONL retriever for MemoryWiki memory roots."""

from __future__ import annotations

import json
from json import JSONDecodeError

from memory_system.models import RetrievalHit, RetrievalResult
from memory_system.paths import validate_episodic_date
from memory_system.sanitizer import sanitize_text

LEGACY_EPISODE_DEPRECATION_NOTE = (
    "Legacy root daily memory files (YYYY-MM-DD.md) are read-only compatibility "
    "fallbacks. V2 episodes/YYYY-MM-DD.md is canonical; migrate legacy files with "
    "merge_episodes.py before disabling legacy reads after 2026-06-30."
)


def _center_excerpt(text: str, needle: str, limit: int = 400) -> str:
    if len(text) <= limit:
        return text
    index = text.lower().find(needle.lower())
    if index < 0:
        return text[:limit]
    start = max(0, index - limit // 2)
    end = min(len(text), start + limit)
    if end - start < limit:
        start = max(0, end - limit)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end] + suffix


class MemoryRetriever:
    def __init__(self, overlay_store) -> None:
        self.overlay_store = overlay_store

    def get_day(self, date_text: str) -> RetrievalHit:
        validate_episodic_date(date_text)
        episode = self.overlay_store.project_store.read_episode(date_text)
        legacy_path = self.overlay_store.project_store.paths.episodic_for_date(date_text)
        legacy_fallback = episode is None and legacy_path.exists()
        text = (
            episode.body
            if episode is not None
            else self.overlay_store.project_store.read_episodic(date_text)
        )
        return RetrievalHit(
            scope="project",
            source="episodic",
            identifier=date_text,
            excerpt=text[:400],
            score=1,
            deprecated=legacy_fallback,
            note=LEGACY_EPISODE_DEPRECATION_NOTE if legacy_fallback else "",
        )

    def search(
        self, keyword: str, source: str = "all", scope: str = "all"
    ) -> RetrievalResult:
        valid_sources = {"all", "history", "episodic", "memory"}
        valid_scopes = {"all", "global", "project"}
        if source not in valid_sources:
            raise ValueError(
                "Unknown memory source {!r}. Expected one of: {}".format(source, ", ".join(sorted(valid_sources)))
            )
        if scope not in valid_scopes:
            raise ValueError(
                "Unknown memory scope {!r}. Expected one of: {}".format(scope, ", ".join(sorted(valid_scopes)))
            )
        hits = []
        needle = keyword.lower()
        stores = (
            ("global", self.overlay_store.global_store),
            ("project", self.overlay_store.project_store),
        )

        for scope_name, store in stores:
            if scope != "all" and scope_name != scope:
                continue

            if (
                source in ("history", "all")
                and scope_name == "project"
                and store._is_safe_readable_file(store.paths.history)
            ):
                lines = store._read_lines_bounded(store.paths.history)
                for line_number, line in enumerate(lines, start=1):
                    try:
                        row = json.loads(line)
                        content = sanitize_text(str(row["content"]))
                    except (JSONDecodeError, KeyError, TypeError):
                        continue
                    lowered = content.lower()
                    if needle in lowered:
                        hits.append(
                            RetrievalHit(
                                scope=scope_name,
                                source="history",
                                identifier=f"history:{line_number}",
                                excerpt="{} [{}] {}".format(
                                    row.get("ts", ""),
                                    row.get("role", ""),
                                    _center_excerpt(content, needle),
                                ),
                                score=lowered.count(needle),
                            )
                        )

            if source in ("episodic", "all"):
                v2_episode_dates = set()
                for path in store._iter_safe_managed_files(
                    store.paths.episodes_dir, "20??-??-??.md"
                ):
                    try:
                        validate_episodic_date(path.stem)
                        episode = store.read_episode(path.stem)
                        text = episode.body if episode is not None else ""
                    except (OSError, UnicodeDecodeError, ValueError):
                        continue
                    v2_episode_dates.add(path.stem)
                    lowered = text.lower()
                    if needle in lowered:
                        hits.append(
                            RetrievalHit(
                                scope=scope_name,
                                source="episodic",
                                identifier=path.stem,
                                excerpt=_center_excerpt(text, needle),
                                score=lowered.count(needle),
                                deprecated=False,
                                note="",
                            )
                        )
                for path in store._iter_safe_managed_files(
                    store.paths.root, "20??-??-??.md"
                ):
                    try:
                        validate_episodic_date(path.stem)
                        if path.stem in v2_episode_dates:
                            continue
                        text = store.read_episodic(path.stem)
                    except (OSError, UnicodeDecodeError, ValueError):
                        continue
                    lowered = text.lower()
                    if needle in lowered:
                        hits.append(
                            RetrievalHit(
                                scope=scope_name,
                                source="episodic",
                                identifier=path.stem,
                                excerpt=_center_excerpt(text, needle),
                                score=lowered.count(needle),
                                deprecated=True,
                                note=LEGACY_EPISODE_DEPRECATION_NOTE,
                            )
                        )

            if source in ("memory", "all"):
                for label, text in (
                    ("memory", store.read_core_memory()),
                    ("user", store.read_user_memory()),
                ):
                    lowered = text.lower()
                    if needle in lowered:
                        hits.append(
                            RetrievalHit(
                                scope=scope_name,
                                source=label,
                                identifier=label,
                                excerpt=_center_excerpt(text, needle),
                                score=lowered.count(needle),
                            )
                        )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return RetrievalResult(hits=hits)
