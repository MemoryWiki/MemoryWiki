from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from memory_index_maintain import rebuild_scope_index
from memory_system.models import RecallHit, RecallResult, SourceRef
from memory_system.paths import MemoryScopePaths
from memory_system.retrieval_associations import rerank_associations
from memory_system.retrieval_granularity import score_row_views
from memory_system.retrieval_index import (
    LOCAL_EMBEDDING_MODEL,
    build_retrieval_views,
    conflict_update_entries,
    load_index,
    local_embedding_for_index,
    sparse_vector_cosine,
    tokenize_for_index,
)
from memory_system.sanitizer import neutralize_instruction_text, sanitize_text
from memory_system.store import ScopedMemoryStore

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{8}")
DEFAULT_TOKEN_BUDGET = 1200
MAX_QUERY_CHARS = 10_000
MAX_RECALL_LIMIT = 500
MAX_TOKEN_BUDGET = 100_000
SOURCE_WEIGHTS = {
    "index": 1.40,
    "semantic": 1.30,
    "procedure": 1.20,
    "project_profile": 1.15,
    "memory": 1.05,
    "user": 1.05,
    "session": 1.00,
    "episode": 0.95,
}


def tokenize(text: str) -> list[str]:
    return tokenize_for_index(text)


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text or "") / 4))


def center_excerpt(text: str, query_tokens: Iterable[str], limit: int = 420) -> str:
    clean = sanitize_text(text or "").strip()
    if len(clean) <= limit:
        return clean
    lowered = clean.lower()
    first_index = -1
    for token in query_tokens:
        index = lowered.find(token.lower())
        if index >= 0 and (first_index < 0 or index < first_index):
            first_index = index
    if first_index < 0:
        return clean[:limit].rstrip() + "..."
    start = max(0, first_index - limit // 3)
    end = min(len(clean), start + limit)
    prefix = "..." if start else ""
    suffix = "..." if end < len(clean) else ""
    return prefix + clean[start:end].rstrip() + suffix


def _safe_output_text(text: str | None) -> str:
    return neutralize_instruction_text(sanitize_text(text or ""))


def _safe_output_json(value):
    if isinstance(value, dict):
        return {_safe_output_text(str(key)): _safe_output_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_output_json(item) for item in value]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _safe_output_text(str(value))


def cosine_score(query_counts: Counter, doc_counts: Counter) -> float:
    if not query_counts or not doc_counts:
        return 0.0
    dot = sum(query_counts[token] * doc_counts.get(token, 0) for token in query_counts)
    query_norm = math.sqrt(sum(count * count for count in query_counts.values()))
    doc_norm = math.sqrt(sum(count * count for count in doc_counts.values()))
    if not query_norm or not doc_norm:
        return 0.0
    return dot / (query_norm * doc_norm)


def score_document(
    query: str,
    title: str,
    text: str,
    concepts: list[str],
    confidence: float = 0.0,
    strength: float = 0.0,
    embedding: str = "off",
) -> float:
    explanation = score_document_explanation(
        query,
        title,
        text,
        concepts,
        confidence=confidence,
        strength=strength,
        embedding=embedding,
    )
    return float(explanation["base_score"])


def score_document_explanation(
    query: str,
    title: str,
    text: str,
    concepts: list[str],
    confidence: float = 0.0,
    strength: float = 0.0,
    embedding: str = "off",
    doc_counts: Counter | None = None,
    embedding_vector: dict[str, float] | None = None,
) -> dict:
    query_tokens = tokenize(query)
    if not query_tokens:
        return {
            "lexical_hits": 0,
            "lexical_score": 0.0,
            "exact_phrase_hits": 0,
            "exact_phrase_score": 0.0,
            "concept_hits": 0,
            "concept_score": 0.0,
            "confidence_score": 0.0,
            "strength_score": 0.0,
            "embedding_score": 0.0,
            "embedding_model": "off",
            "embedding_source": "off",
            "graph_score": 0.0,
            "base_score": 0.0,
        }
    query_counts = Counter(query_tokens)
    weighted_text = " ".join([title, text, " ".join(concepts)])
    if doc_counts is None:
        doc_tokens = tokenize(weighted_text)
        doc_counts = Counter(doc_tokens)
    lexical = sum(min(doc_counts.get(token, 0), 5) for token in query_counts)
    exact = weighted_text.lower().count(query.lower()) if query else 0
    concept_hits = sum(1 for concept in concepts if concept.lower() in query.lower())
    lexical_score = lexical * 3.0
    exact_score = exact * 8.0
    concept_score = concept_hits * 2.0
    embedding_score = 0.0
    embedding_model = "off"
    embedding_source = "off"
    if embedding == "local":
        embedding_model = LOCAL_EMBEDDING_MODEL
        if embedding_vector:
            query_vector = local_embedding_for_index(query)
            embedding_score = max(0.0, sparse_vector_cosine(query_vector, embedding_vector)) * 4.0
            embedding_source = "cached-index-vector"
        else:
            embedding_score = max(0.0, cosine_score(query_counts, doc_counts)) * 4.0
            embedding_source = "term-counts"
    match_score = lexical_score + exact_score + concept_score + embedding_score
    confidence_score = max(0.0, min(1.0, confidence)) if match_score > 0 else 0.0
    strength_score = max(0.0, min(1.0, strength)) if match_score > 0 else 0.0
    base_score = (
        lexical_score
        + exact_score
        + concept_score
        + confidence_score
        + strength_score
        + embedding_score
    )
    return {
        "lexical_hits": lexical,
        "lexical_score": lexical_score,
        "exact_phrase_hits": exact,
        "exact_phrase_score": exact_score,
        "concept_hits": concept_hits,
        "concept_score": concept_score,
        "confidence_score": confidence_score,
        "strength_score": strength_score,
        "embedding_score": embedding_score,
        "embedding_model": embedding_model,
        "embedding_source": embedding_source,
        "graph_score": 0.0,
        "base_score": base_score,
    }


def safe_store(root: Path, scope: str) -> ScopedMemoryStore | None:
    root = root.expanduser()
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Memory root must be a real directory: {root}")
    return ScopedMemoryStore(
        MemoryScopePaths.from_root(root, scope=scope),
        sanitize_on_write=True,
        secure_permissions=False,
    )


def memory_file_ref(kind: str, path: str, identifier: str) -> SourceRef:
    return SourceRef(kind=kind, path=path, identifier=identifier, excerpt=None)


def _concept_keys(concepts: Iterable[str]) -> set[str]:
    keys: set[str] = set()
    for concept in concepts:
        normalized = str(concept or "").strip().lower()
        if not normalized:
            continue
        keys.add(normalized)
        keys.update(tokenize(normalized))
    return keys


def _concept_labels_for_keys(concepts: Iterable[str], keys: set[str]) -> list[str]:
    labels = []
    for concept in concepts:
        label = str(concept or "").strip()
        if not label:
            continue
        normalized = label.lower()
        if normalized in keys or (_concept_keys([label]) & keys):
            labels.append(label)
    return labels


def _has_direct_query_signal(explanation: dict) -> bool:
    return any(
        float(explanation.get(key) or 0.0) > 0.0
        for key in (
            "lexical_score",
            "exact_phrase_score",
            "concept_score",
            "embedding_score",
            "final_view_score",
        )
    )


def _conflict_fields(update_log: Iterable[str]) -> dict:
    entries = conflict_update_entries(update_log)
    return {
        "conflict_history": bool(entries),
        "conflict_count": len(entries),
        "conflict_entries": entries[:5],
    }


def _live_view_row(
    *,
    scope: str,
    source: str,
    identifier: str,
    source_path: str,
    title: str,
    text: str,
    concepts: list[str],
    provenance: list[SourceRef],
    update_log: Iterable[str] = (),
) -> dict:
    safe_update_log = [str(entry) for entry in update_log]
    return {
        "scope": scope,
        "source": source,
        "identifier": identifier,
        "source_path": source_path,
        "title": title,
        "text": text,
        "concepts": concepts,
        "provenance": [asdict(ref) for ref in provenance],
        "update_log": safe_update_log,
        "views": build_retrieval_views(
            scope=scope,
            source=source,
            identifier=identifier,
            source_path=source_path,
            title=title,
            text=text,
            concepts=concepts,
            source_refs=provenance,
            update_log=safe_update_log,
            indexed_at="live",
        ),
    }


def _apply_granularity_router(
    *,
    query: str,
    explanation: dict,
    row: dict,
    embedding: str,
    granularity_router: str,
) -> dict:
    if granularity_router == "off":
        explanation["granularity_router"] = "off"
        return explanation
    view_result = score_row_views(
        query=query,
        row=row,
        embedding=embedding,
        router=granularity_router,
    )
    if view_result is None:
        explanation["granularity_router"] = granularity_router
        explanation["granularity_router_status"] = "no_views"
        return explanation
    view_score, view_explanation = view_result
    previous_base = float(explanation.get("base_score") or 0.0)
    explanation["pre_router_base_score"] = previous_base
    explanation.update(view_explanation)
    view_score = float(view_score)
    if previous_base > 0:
        router_bonus = min(max(0.0, view_score - previous_base), max(1.0, previous_base * 0.25))
        explanation["base_score"] = previous_base + router_bonus
    else:
        router_bonus = min(view_score, 12.0)
        explanation["base_score"] = router_bonus
    explanation["router_bonus"] = router_bonus
    return explanation


def _apply_graph_expansion(candidates: list[dict], graph: str) -> list[RecallHit]:
    if graph != "local":
        return [candidate["hit"] for candidate in candidates if candidate["hit"].score > 0]

    seed_keys: set[str] = set()
    for candidate in candidates:
        if candidate["hit"].score <= 0:
            continue
        if _has_direct_query_signal(candidate["hit"].score_explanation):
            seed_keys.update(candidate["concept_keys"])

    expanded: list[RecallHit] = []
    for candidate in candidates:
        hit: RecallHit = candidate["hit"]
        explanation = hit.score_explanation
        graph_score = 0.0
        overlap = candidate["concept_keys"] & seed_keys
        if overlap:
            if hit.score > 0:
                graph_score = min(1.0, 0.25 * len(overlap))
            else:
                graph_score = min(3.0, 1.25 * len(overlap))
            hit.score += graph_score
        explanation["graph_score"] = graph_score
        explanation["graph_related_concepts"] = _concept_labels_for_keys(
            candidate["concepts"], overlap
        )
        explanation["graph_seed_concepts"] = sorted(overlap)[:12]
        if hit.score > 0:
            expanded.append(hit)
    return expanded


def candidates_for_store(
    store: ScopedMemoryStore,
    scope: str,
    query: str,
    embedding: str,
    graph: str = "local",
    granularity_router: str = "off",
):
    query_tokens = tokenize(query)
    semantic_candidates = []
    for semantic_item in store.list_semantic_memories(limit=200):
        text = semantic_item.content
        explanation = score_document_explanation(
            query,
            semantic_item.title,
            text,
            semantic_item.concepts,
            semantic_item.confidence,
            semantic_item.strength,
            embedding=embedding,
        )
        explanation.update(_conflict_fields(semantic_item.update_log))
        explanation["concepts"] = list(semantic_item.concepts)
        provenance = semantic_item.source_refs + [
            memory_file_ref("memory-file", f"semantic/{semantic_item.id}.md", semantic_item.id)
        ]
        if explanation["conflict_history"]:
            provenance.append(
                memory_file_ref("update-log", f"semantic/{semantic_item.id}.md", semantic_item.id)
            )
        if granularity_router == "off":
            explanation["granularity_router"] = "off"
        else:
            explanation = _apply_granularity_router(
                query=query,
                explanation=explanation,
                row=_live_view_row(
                    scope=scope,
                    source="semantic",
                    identifier=semantic_item.id,
                    source_path=f"semantic/{semantic_item.id}.md",
                    title=semantic_item.title,
                    text=text,
                    concepts=list(semantic_item.concepts),
                    provenance=provenance,
                    update_log=semantic_item.update_log,
                ),
                embedding=embedding,
                granularity_router=granularity_router,
            )
        score = explanation["base_score"]
        hit = RecallHit(
            scope=scope,
            source="semantic",
            identifier=semantic_item.id,
            title=semantic_item.title,
            excerpt=center_excerpt(text, query_tokens),
            score=score,
            provenance=provenance,
            tokens=estimate_tokens(text),
            score_explanation={**explanation, "strategy": "live"},
        )
        semantic_candidates.append(
            {
                "hit": hit,
                "concepts": list(semantic_item.concepts),
                "concept_keys": _concept_keys(semantic_item.concepts),
            }
        )

    for hit in _apply_graph_expansion(semantic_candidates, graph):
        yield hit

    for procedural_item in store.list_procedural_memories(limit=200):
        text = "\n".join([procedural_item.trigger] + procedural_item.steps)
        explanation = score_document_explanation(
            query,
            procedural_item.title,
            text,
            [],
            procedural_item.confidence,
            procedural_item.strength,
            embedding=embedding,
        )
        provenance = procedural_item.source_refs + [
            memory_file_ref(
                "memory-file", f"procedures/{procedural_item.id}.md", procedural_item.id
            )
        ]
        if granularity_router == "off":
            explanation["granularity_router"] = "off"
        else:
            explanation = _apply_granularity_router(
                query=query,
                explanation=explanation,
                row=_live_view_row(
                    scope=scope,
                    source="procedure",
                    identifier=procedural_item.id,
                    source_path=f"procedures/{procedural_item.id}.md",
                    title=procedural_item.title,
                    text=text,
                    concepts=[],
                    provenance=provenance,
                ),
                embedding=embedding,
                granularity_router=granularity_router,
            )
        score = explanation["base_score"]
        if score <= 0:
            continue
        yield RecallHit(
            scope=scope,
            source="procedure",
            identifier=procedural_item.id,
            title=procedural_item.title,
            excerpt=center_excerpt(text, query_tokens),
            score=score,
            provenance=provenance,
            tokens=estimate_tokens(text),
            score_explanation={**explanation, "strategy": "live"},
        )

    for session_meta in store.list_sessions(limit=200):
        session = store.read_session(session_meta.id)
        if session is None:
            continue
        text = "\n".join(
            [session.title, session.body] + session.keypoints + session.actions + session.pending
        )
        explanation = score_document_explanation(
            query, session.title, text, [], embedding=embedding
        )
        provenance = [memory_file_ref("session", f"sessions/{session.id}.md", session.id)]
        if granularity_router == "off":
            explanation["granularity_router"] = "off"
        else:
            explanation = _apply_granularity_router(
                query=query,
                explanation=explanation,
                row=_live_view_row(
                    scope=scope,
                    source="session",
                    identifier=session.id,
                    source_path=f"sessions/{session.id}.md",
                    title=session.title,
                    text=text,
                    concepts=[],
                    provenance=provenance,
                ),
                embedding=embedding,
                granularity_router=granularity_router,
            )
        score = explanation["base_score"]
        if score <= 0:
            continue
        yield RecallHit(
            scope=scope,
            source="session",
            identifier=session.id,
            title=session.title,
            excerpt=center_excerpt(text, query_tokens),
            score=score,
            provenance=provenance,
            tokens=estimate_tokens(text),
            score_explanation={**explanation, "strategy": "live"},
        )

    for date_text in store.list_episodes():
        episode = store.read_episode(date_text)
        if episode is None:
            continue
        explanation = score_document_explanation(
            query, date_text, episode.body, [], embedding=embedding
        )
        provenance = [memory_file_ref("episode", f"episodes/{date_text}.md", date_text)]
        if granularity_router == "off":
            explanation["granularity_router"] = "off"
        else:
            explanation = _apply_granularity_router(
                query=query,
                explanation=explanation,
                row=_live_view_row(
                    scope=scope,
                    source="episode",
                    identifier=date_text,
                    source_path=f"episodes/{date_text}.md",
                    title=date_text,
                    text=episode.body,
                    concepts=[],
                    provenance=provenance,
                ),
                embedding=embedding,
                granularity_router=granularity_router,
            )
        score = explanation["base_score"]
        if score <= 0:
            continue
        yield RecallHit(
            scope=scope,
            source="episode",
            identifier=date_text,
            title=date_text,
            excerpt=center_excerpt(episode.body, query_tokens),
            score=score,
            provenance=provenance,
            tokens=estimate_tokens(episode.body),
            score_explanation={**explanation, "strategy": "live"},
        )

    for label, path in (
        ("index", store.paths.index),
        ("memory", store.paths.core_memory),
        ("user", store.paths.user_memory),
        ("project_profile", store.paths.project_profile),
    ):
        if not store._is_safe_readable_file(path):
            continue
        text = sanitize_text(store._read_text_bounded(path))
        explanation = score_document_explanation(query, label, text, [], embedding=embedding)
        provenance = [memory_file_ref("hot-file", path.name, label)]
        if granularity_router == "off":
            explanation["granularity_router"] = "off"
        else:
            explanation = _apply_granularity_router(
                query=query,
                explanation=explanation,
                row=_live_view_row(
                    scope=scope,
                    source=label,
                    identifier=label,
                    source_path=path.name,
                    title=label.upper(),
                    text=text,
                    concepts=[],
                    provenance=provenance,
                ),
                embedding=embedding,
                granularity_router=granularity_router,
            )
        score = explanation["base_score"]
        if score <= 0:
            continue
        yield RecallHit(
            scope=scope,
            source=label,
            identifier=label,
            title=label.upper(),
            excerpt=center_excerpt(text, query_tokens),
            score=score,
            provenance=provenance,
            tokens=estimate_tokens(text),
            score_explanation={**explanation, "strategy": "live"},
        )


def _source_refs_from_index(rows: list[dict]) -> list[SourceRef]:
    refs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        refs.append(
            SourceRef(
                kind=str(row.get("kind", "")),
                path=str(row.get("path", "")),
                identifier=row.get("identifier"),
                excerpt=row.get("excerpt"),
            )
        )
    return refs


def _term_counts_from_index(row: dict) -> Counter[str]:
    counts: Counter[str] = Counter()
    for token, count in (row.get("term_counts") or {}).items():
        try:
            counts[str(token)] = int(count)
        except (TypeError, ValueError):
            continue
    return counts


def _embedding_vector_from_index(row: dict) -> dict[str, float]:
    vector: dict[str, float] = {}
    if row.get("embedding_model") != LOCAL_EMBEDDING_MODEL:
        return vector
    for bucket, value in (row.get("embedding_vector") or {}).items():
        try:
            vector[str(bucket)] = float(value)
        except (TypeError, ValueError):
            continue
    return vector


def candidates_for_index(
    root: Path,
    scope: str,
    query: str,
    embedding: str,
    graph: str = "local",
    granularity_router: str = "off",
) -> tuple[list[RecallHit], list[str], bool]:
    load_result = load_index(root, scope)
    query_tokens = tokenize(query)
    candidates = []
    for row in load_result.rows:
        title = str(row.get("title", ""))
        text = str(row.get("text", ""))
        concepts = [str(item) for item in row.get("concepts", [])]
        explanation = score_document_explanation(
            query,
            title,
            text,
            concepts,
            float(row.get("confidence") or 0.0),
            float(row.get("strength") or 0.0),
            embedding=embedding,
            doc_counts=_term_counts_from_index(row),
            embedding_vector=_embedding_vector_from_index(row),
        )
        explanation.update(
            {
                "conflict_history": bool(row.get("conflict_history")),
                "conflict_count": len(row.get("conflict_entries") or []),
                "conflict_entries": [
                    str(entry) for entry in (row.get("conflict_entries") or [])[:5]
                ],
                "concepts": concepts,
            }
        )
        provenance = _source_refs_from_index(row.get("provenance") or [])
        if explanation["conflict_history"]:
            provenance.append(
                memory_file_ref(
                    "update-log",
                    str(row.get("source_path", "")),
                    str(row.get("identifier", "")),
                )
            )
        explanation = _apply_granularity_router(
            query=query,
            explanation=explanation,
            row=row,
            embedding=embedding,
            granularity_router=granularity_router,
        )
        score = explanation["base_score"]
        hit = RecallHit(
            scope=scope,
            source=str(row.get("source", "")),
            identifier=str(row.get("identifier", "")),
            title=title,
            excerpt=center_excerpt(text, query_tokens),
            score=score,
            provenance=provenance,
            tokens=estimate_tokens(text),
            score_explanation={**explanation, "strategy": "indexed"},
        )
        candidates.append(
            {
                "hit": hit,
                "concepts": concepts,
                "concept_keys": _concept_keys(concepts),
            }
        )
    hits = _apply_graph_expansion(candidates, graph)
    return hits, load_result.warnings, load_result.fresh


def _recency_key(hit: RecallHit) -> str:
    candidates = [hit.identifier, hit.title]
    candidates.extend(ref.path or "" for ref in hit.provenance)
    candidates.extend(ref.identifier or "" for ref in hit.provenance)
    for value in candidates:
        match = DATE_RE.search(value or "")
        if match:
            return match.group(0).replace("-", "")
    return ""


def _rrf_scores(rankings: list[list[RecallHit]], constant: int = 60) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranked in rankings:
        for rank, hit in enumerate(ranked, start=1):
            scores[id(hit)] = scores.get(id(hit), 0.0) + (1.0 / (constant + rank))
    return scores


def _round_robin_by_source(hits: list[RecallHit]) -> list[RecallHit]:
    source_order = []
    buckets: dict[str, list[RecallHit]] = {}
    for hit in hits:
        if hit.source not in buckets:
            source_order.append(hit.source)
            buckets[hit.source] = []
        buckets[hit.source].append(hit)
    diversified = []
    while any(buckets[source] for source in source_order):
        for source in source_order:
            if buckets[source]:
                diversified.append(buckets[source].pop(0))
    return diversified


def rank_hits(hits: list[RecallHit], ranker: str = "rrf") -> list[RecallHit]:
    for hit in hits:
        hit.score_explanation.setdefault("base_score", hit.score)
        hit.score_explanation["source_weight"] = SOURCE_WEIGHTS.get(hit.source, 1.0)
    if ranker == "score":
        ranked = sorted(hits, key=lambda hit: hit.score, reverse=True)
        for rank, hit in enumerate(ranked, start=1):
            hit.score_explanation["score_rank"] = rank
            hit.score_explanation["final_score"] = hit.score
        return ranked
    if not hits:
        return []
    by_score = sorted(hits, key=lambda hit: hit.score, reverse=True)
    by_source = sorted(
        hits,
        key=lambda hit: (SOURCE_WEIGHTS.get(hit.source, 1.0), hit.score),
        reverse=True,
    )
    by_recency = sorted(
        hits,
        key=lambda hit: (_recency_key(hit), hit.score),
        reverse=True,
    )
    score_ranks = {id(hit): rank for rank, hit in enumerate(by_score, start=1)}
    source_ranks = {id(hit): rank for rank, hit in enumerate(by_source, start=1)}
    recency_ranks = {id(hit): rank for rank, hit in enumerate(by_recency, start=1)}
    rrf = _rrf_scores([by_score, by_source, by_recency])
    ranked = sorted(
        hits,
        key=lambda hit: (rrf.get(id(hit), 0.0), hit.score),
        reverse=True,
    )
    for hit in ranked:
        bonus = rrf.get(id(hit), 0.0) * 100.0
        hit.score_explanation["score_rank"] = score_ranks[id(hit)]
        hit.score_explanation["source_rank"] = source_ranks[id(hit)]
        hit.score_explanation["recency_rank"] = recency_ranks[id(hit)]
        hit.score_explanation["recency_key"] = _recency_key(hit)
        hit.score_explanation["rrf_bonus"] = bonus
        hit.score = hit.score + bonus
        hit.score_explanation["final_score"] = hit.score
    return _round_robin_by_source(ranked)


def apply_budget(hits: list[RecallHit], limit: int, token_budget: int) -> RecallResult:
    selected = []
    tokens_used = 0
    truncated = len(hits) > limit
    for hit in hits[:limit]:
        remaining = token_budget - tokens_used
        if remaining <= 0:
            truncated = True
            break
        tokens = estimate_tokens(hit.excerpt)
        if tokens > remaining:
            max_chars = max(20, remaining * 4 - 4)
            hit.excerpt = hit.excerpt[:max_chars].rstrip()
            if len(hit.excerpt) == max_chars:
                hit.excerpt = hit.excerpt.rstrip(". ") + "..."
            tokens = estimate_tokens(hit.excerpt)
            truncated = True
        if tokens <= remaining:
            hit.tokens = tokens
            selected.append(hit)
            tokens_used += tokens
        else:
            truncated = True
            break
    if len(selected) < len(hits):
        truncated = True
    return RecallResult(query="", hits=selected, tokens_used=tokens_used, truncated=truncated)


def _conflict_warnings(hits: list[RecallHit]) -> list[str]:
    warnings = []
    seen = set()
    for hit in hits:
        if not hit.score_explanation.get("conflict_history"):
            continue
        key = (hit.scope, hit.source, hit.identifier)
        if key in seen:
            continue
        seen.add(key)
        warnings.append(
            f"Conflict history present for {hit.scope}/{hit.source}/{hit.identifier}; review semantic update_log "
            "before treating it as settled fact."
        )
    return warnings


def recall(args) -> RecallResult:
    roots = []
    if args.scope in ("all", "global"):
        roots.append(("global", Path(args.global_root).expanduser()))
    if args.scope in ("all", "project"):
        roots.append(("project", Path(args.project_root).expanduser()))

    hits = []
    warnings = []
    graph = getattr(args, "graph", "local")
    granularity_router = getattr(args, "granularity_router", "off")
    association_reranker = getattr(args, "association_reranker", "off")
    for scope, root in roots:
        store = safe_store(root, scope)
        if store is None:
            continue
        if getattr(args, "refresh_index_if_needed", False):
            refresh_report = rebuild_scope_index(root, scope)
            if refresh_report.get("rebuilt"):
                warnings.append(
                    "Refreshed retrieval index for {} memory: {}".format(scope, refresh_report.get("index_path", ""))
                )
        if args.strategy == "live":
            hits.extend(
                candidates_for_store(
                    store,
                    scope,
                    args.query,
                    args.embedding,
                    graph,
                    granularity_router,
                )
            )
            continue
        indexed_hits, index_warnings, index_fresh = candidates_for_index(
            root,
            scope,
            args.query,
            args.embedding,
            graph,
            granularity_router,
        )
        warnings.extend(index_warnings)
        if args.strategy == "indexed":
            if index_fresh:
                hits.extend(indexed_hits)
            else:
                warnings.append(
                    f"Indexed recall skipped {scope} memory because the retrieval index is stale, "
                    "tampered, missing, or mixed-schema."
                )
            continue
        if index_fresh:
            hits.extend(indexed_hits)
        else:
            warnings.append(
                f"Hybrid fallback to live recall for {scope} memory because the retrieval "
                "index is stale or missing."
            )
            hits.extend(
                candidates_for_store(
                    store,
                    scope,
                    args.query,
                    args.embedding,
                    graph,
                    granularity_router,
                )
            )

    hits = rerank_associations(hits, association_reranker)
    hits = rank_hits(hits, args.ranker)
    result = apply_budget(hits, limit=args.limit, token_budget=args.token_budget)
    result.query = args.query
    result.strategy = args.strategy
    result.warnings = warnings + _conflict_warnings(result.hits)
    return result


def _round_score_explanation(explanation: dict) -> dict:
    rounded = {}
    for key, value in explanation.items():
        if isinstance(value, float):
            rounded[key] = round(value, 4)
        else:
            rounded[key] = value
    return rounded


def result_to_dict(result: RecallResult, explain_score: bool = False) -> dict:
    hits = []
    for hit in result.hits:
        row = {
            "scope": _safe_output_text(hit.scope),
            "source": _safe_output_text(hit.source),
            "identifier": _safe_output_text(hit.identifier),
            "title": _safe_output_text(hit.title),
            "excerpt": _safe_output_text(hit.excerpt),
            "score": round(hit.score, 4),
            "tokens": hit.tokens,
            "provenance": _safe_output_json([asdict(ref) for ref in hit.provenance]),
        }
        if explain_score:
            row["score_explanation"] = _safe_output_json(
                _round_score_explanation(hit.score_explanation)
            )
        hits.append(row)
    return {
        "query": _safe_output_text(result.query),
        "strategy": _safe_output_text(result.strategy),
        "tokens_used": result.tokens_used,
        "truncated": result.truncated,
        "warnings": [_safe_output_text(warning) for warning in result.warnings],
        "hits": hits,
    }


def _json_dumps_cli(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2)


def render_human(result: RecallResult, explain_score: bool = False) -> str:
    if not result.hits:
        return f"No matching memory found for: {_safe_output_text(result.query)}\n"
    lines = [
        "# Memory Recall",
        "",
        f"Query: {_safe_output_text(result.query)}",
        f"Strategy: {_safe_output_text(result.strategy)}",
        f"Tokens used: {result.tokens_used}",
        "Truncated: %s" % ("yes" if result.truncated else "no"),
        "",
    ]
    if result.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {_safe_output_text(warning)}" for warning in result.warnings)
        lines.append("")
    for index, hit in enumerate(result.hits, start=1):
        lines.extend(
            [
                f"{index}. [{_safe_output_text(hit.scope)}/{_safe_output_text(hit.source)}] {_safe_output_text(hit.title)} ({_safe_output_text(hit.identifier)}, score {hit.score:.2f})",
                _safe_output_text(hit.excerpt),
            ]
        )
        if hit.provenance:
            refs = ", ".join(
                f"{_safe_output_text(ref.kind)}:{_safe_output_text(ref.identifier or ref.path)}"
                for ref in hit.provenance[:3]
            )
            lines.append(f"Sources: {refs}")
        if explain_score and hit.score_explanation:
            explanation = _safe_output_json(_round_score_explanation(hit.score_explanation))
            lines.append(f"Score explanation: {json.dumps(explanation, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recall local memory with provenance.")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument(
        "--project-root",
        default=str(Path.cwd() / ".agent_memory" / "project"),
        help="Project memory root",
    )
    parser.add_argument(
        "--global-root",
        default=str(Path.home() / ".agent_memory" / "global"),
        help="Global memory root",
    )
    parser.add_argument(
        "--scope",
        choices=("all", "project", "global"),
        default="all",
        help="Memory scope to search",
    )
    parser.add_argument("--limit", type=int, default=8, help="Maximum hits")
    parser.add_argument(
        "--token-budget",
        type=int,
        default=DEFAULT_TOKEN_BUDGET,
        help="Approximate output token budget",
    )
    parser.add_argument(
        "--embedding",
        choices=("off", "local"),
        default="off",
        help="Optional local lexical-vector scoring; never calls an API",
    )
    parser.add_argument(
        "--graph",
        choices=("off", "local"),
        default="local",
        help="Use the local semantic concept graph to expand related memories.",
    )
    parser.add_argument(
        "--granularity-router",
        choices=("off", "static", "entropy"),
        default="off",
        help=(
            "Opt-in deterministic multi-view retrieval router; local-only and "
            "API-free."
        ),
    )
    parser.add_argument(
        "--association-reranker",
        choices=("off", "local"),
        default="off",
        help=(
            "Opt-in local association reranking over the candidate set. This is "
            "separate from --graph local."
        ),
    )
    parser.add_argument(
        "--ranker",
        choices=("rrf", "score"),
        default="rrf",
        help="Ranking strategy. rrf blends lexical score, source weight, and recency.",
    )
    parser.add_argument(
        "--strategy",
        choices=("live", "indexed", "hybrid"),
        default="live",
        help=(
            "Recall source. hybrid uses retrieval/index.jsonl when fresh and falls "
            "back to live reads."
        ),
    )
    parser.add_argument(
        "--refresh-index-if-needed",
        action="store_true",
        help=(
            "Opt-in write: rebuild missing, stale, or tampered retrieval indexes "
            "before recall using an exclusive retrieval-index lease."
        ),
    )
    parser.add_argument(
        "--explain-score",
        action="store_true",
        help="Include score component breakdowns for debugging recall ranking.",
    )
    parser.add_argument(
        "--trace-feedback-root",
        help=(
            "Explicit write opt-in: append a recall_trace row to "
            "<root>/retrieval_feedback.jsonl for later quality review."
        ),
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit must be positive")
    if args.limit > MAX_RECALL_LIMIT:
        parser.error(f"--limit must be at most {MAX_RECALL_LIMIT}")
    if args.token_budget <= 0:
        parser.error("--token-budget must be positive")
    if args.token_budget > MAX_TOKEN_BUDGET:
        parser.error(f"--token-budget must be at most {MAX_TOKEN_BUDGET}")
    if len(args.query) > MAX_QUERY_CHARS:
        parser.error(f"--query must be at most {MAX_QUERY_CHARS} characters")
    try:
        result = recall(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.trace_feedback_root:
        try:
            from memory_feedback import append_recall_trace

            append_recall_trace(root=args.trace_feedback_root, result=result)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.format == "json":
        print(_json_dumps_cli(result_to_dict(result, explain_score=args.explain_score)))
    else:
        print(render_human(result, explain_score=args.explain_score))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
