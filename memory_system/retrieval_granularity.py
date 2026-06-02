from __future__ import annotations

import math
from collections import Counter
from typing import Any, cast

from memory_system.retrieval_index import (
    LOCAL_EMBEDDING_MODEL,
    local_embedding_for_index,
    sparse_vector_cosine,
    tokenize_for_index,
)

VIEW_STATIC_WEIGHTS = {
    "title_concepts": 1.15,
    "body": 1.0,
    "summary_keypoints": 1.05,
    "procedure_trigger_steps": 1.1,
    "source_provenance": 0.65,
}
VIEW_WEIGHT_CAPS = {
    "title_concepts": 1.55,
    "body": 1.35,
    "summary_keypoints": 1.45,
    "procedure_trigger_steps": 1.55,
    "source_provenance": 0.95,
}
MIN_VIEW_EVIDENCE = 0.05


def _coerce_term_counts(value: Any) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not isinstance(value, dict):
        return counts
    for token, count in value.items():
        try:
            counts[str(token)] = int(count)
        except (TypeError, ValueError):
            continue
    return counts


def _coerce_embedding_vector(value: Any) -> dict[str, float]:
    vector: dict[str, float] = {}
    if not isinstance(value, dict):
        return vector
    for bucket, weight in value.items():
        try:
            vector[str(bucket)] = float(weight)
        except (TypeError, ValueError):
            continue
    return vector


def _view_base_score(
    *,
    query: str,
    query_counts: Counter[str],
    query_vector: dict[str, float],
    view: dict,
    embedding: str,
) -> dict[str, float | int | str]:
    counts = _coerce_term_counts(view.get("term_counts") or {})
    if not counts and view.get("text"):
        counts = Counter(tokenize_for_index(str(view.get("text") or "")))
    lexical_hits = sum(min(counts.get(token, 0), 5) for token in query_counts)
    lexical_score = lexical_hits * 3.0
    view_text = str(view.get("text") or "")
    exact_hits = view_text.lower().count(query.lower()) if query else 0
    exact_score = exact_hits * 8.0
    embedding_score = 0.0
    if embedding == "local":
        vector = _coerce_embedding_vector(view.get("embedding_vector") or {})
        if view.get("embedding_model") == LOCAL_EMBEDDING_MODEL and vector:
            embedding_score = max(0.0, sparse_vector_cosine(query_vector, vector)) * 4.0
        elif counts:
            embedding_score = max(0.0, _cosine_counts(query_counts, counts)) * 4.0
    base_score = lexical_score + exact_score + embedding_score
    if lexical_hits <= 0 and embedding_score < MIN_VIEW_EVIDENCE and exact_hits <= 0:
        base_score = 0.0
    return {
        "view_name": str(view.get("view_name", "")),
        "lexical_hits": lexical_hits,
        "lexical_score": lexical_score,
        "exact_phrase_hits": exact_hits,
        "exact_phrase_score": exact_score,
        "embedding_score": embedding_score,
        "base_score": base_score,
    }


def _cosine_counts(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[token] * right.get(token, 0) for token in left)
    left_norm = math.sqrt(sum(count * count for count in left.values()))
    right_norm = math.sqrt(sum(count * count for count in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _entropy_weights(view_scores: list[dict[str, float | int | str]]) -> tuple[dict[str, float], float]:
    positive = [float(item["base_score"]) for item in view_scores if float(item["base_score"]) > 0]
    if not positive:
        return {}, 0.0
    total = sum(positive)
    probabilities = [score / total for score in positive]
    if len(probabilities) == 1:
        entropy = 0.0
    else:
        entropy = -sum(p * math.log(p) for p in probabilities if p > 0) / math.log(
            len(probabilities)
        )
    weights: dict[str, float] = {}
    baseline = 1.0 / max(1, len(positive))
    for item in view_scores:
        name = str(item["view_name"])
        score = float(item["base_score"])
        static = VIEW_STATIC_WEIGHTS.get(name, 1.0)
        if score <= 0 or total <= 0:
            weights[name] = static
            continue
        concentration = score / total
        multiplier = 1.0 + max(0.0, concentration - baseline) * (1.0 - entropy + 0.25)
        weights[name] = min(VIEW_WEIGHT_CAPS.get(name, 1.5), static * multiplier)
    return weights, entropy


def score_row_views(
    *,
    query: str,
    row: dict,
    embedding: str = "off",
    router: str = "off",
) -> tuple[float, dict] | None:
    if router == "off":
        return None
    if router not in {"static", "entropy"}:
        raise ValueError(f"Unsupported granularity router: {router}")
    views = row.get("views") or []
    if not isinstance(views, list) or not views:
        return None
    query_counts = Counter(tokenize_for_index(query))
    if not query_counts:
        return 0.0, {
            "granularity_router": router,
            "aggregation": "no_query_terms",
            "view_count": len(views),
            "final_view_score": 0.0,
        }
    query_vector = local_embedding_for_index(query) if embedding == "local" else {}
    view_scores = [
        _view_base_score(
            query=query,
            query_counts=query_counts,
            query_vector=query_vector,
            view=view,
            embedding=embedding,
        )
        for view in views
        if isinstance(view, dict)
    ]
    if router == "entropy":
        weights, entropy = _entropy_weights(view_scores)
    else:
        weights = {
            str(item["view_name"]): VIEW_STATIC_WEIGHTS.get(str(item["view_name"]), 1.0)
            for item in view_scores
        }
        entropy = 0.0
    weighted_scores = []
    for item in view_scores:
        name = str(item["view_name"])
        score = float(item["base_score"])
        weight = min(VIEW_WEIGHT_CAPS.get(name, 1.5), weights.get(name, 1.0))
        weighted_scores.append(score * weight)
        item["weight"] = weight
    max_score = max((float(item["base_score"]) for item in view_scores), default=0.0)
    fused_score = min(sum(weighted_scores), max_score * 2.5) if max_score > 0 else 0.0
    explanation = {
        "granularity_router": router,
        "aggregation": "bounded_weighted_sum_collapsed_to_canonical_hit",
        "view_count": len(view_scores),
        "view_entropy": entropy,
        "max_view_score": max_score,
        "final_view_score": fused_score,
        "per_view_top_scores": sorted(
            [
                {
                    "view_name": str(item["view_name"]),
                    "base_score": float(item["base_score"]),
                    "weight": float(item.get("weight") or 0.0),
                    "lexical_hits": int(item["lexical_hits"]),
                    "embedding_score": float(item["embedding_score"]),
                }
                for item in view_scores
                if float(item["base_score"]) > 0
            ],
            key=lambda item: cast(float, item["base_score"]),
            reverse=True,
        )[:5],
    }
    return fused_score, explanation
