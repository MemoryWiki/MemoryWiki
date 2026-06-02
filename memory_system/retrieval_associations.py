from __future__ import annotations

from typing import Iterable

from memory_system.models import RecallHit
from memory_system.retrieval_index import tokenize_for_index

MAX_ASSOCIATION_BOOST = 1.0
MAX_ASSOCIATION_FEATURES = 80
PROTECTED_FLAGS = (
    "stale_source",
    "digest_drifted",
    "forgotten",
    "unverifiable",
    "source_ref_digest_changed",
)


def _feature_tokens(values: Iterable[str]) -> set[str]:
    features: set[str] = set()
    for value in values:
        text = str(value or "").strip().lower()
        if not text:
            continue
        features.add(text)
        features.update(tokenize_for_index(text))
        if len(features) >= MAX_ASSOCIATION_FEATURES:
            break
    return features


def _hit_features(hit: RecallHit) -> set[str]:
    values: list[str] = []
    values.extend(str(item) for item in hit.score_explanation.get("concepts", []) or [])
    for ref in hit.provenance:
        if ref.kind in {"source", "memory-file", "session", "episode", "update-log"}:
            values.extend([ref.path or "", ref.identifier or ""])
    return _feature_tokens(values)


def _has_direct_signal(hit: RecallHit) -> bool:
    return any(
        float(hit.score_explanation.get(key) or 0.0) > 0.0
        for key in (
            "lexical_score",
            "exact_phrase_score",
            "concept_score",
            "embedding_score",
            "final_view_score",
        )
    )


def _is_protected(hit: RecallHit) -> bool:
    return any(bool(hit.score_explanation.get(flag)) for flag in PROTECTED_FLAGS)


def rerank_associations(hits: list[RecallHit], mode: str = "off") -> list[RecallHit]:
    if mode == "off" or not hits:
        return hits
    seeds = [
        hit for hit in sorted(hits, key=lambda item: item.score, reverse=True)
        if hit.score > 0 and _has_direct_signal(hit)
    ][:8]
    seed_feature_map: dict[tuple[str, str, str, str], set[str]] = {}
    for seed in seeds:
        seed_feature_map[(seed.scope, seed.source, seed.identifier, seed.title)] = _hit_features(seed)
    if not any(seed_feature_map.values()):
        return hits
    for hit in hits:
        explanation = hit.score_explanation
        explanation["association_reranker"] = mode
        if hit.score <= 0 or _is_protected(hit):
            explanation["association_score"] = 0.0
            explanation["association_overlap_count"] = 0
            explanation["association_protected"] = bool(_is_protected(hit))
            continue
        seed_features: set[str] = set()
        current_key = (hit.scope, hit.source, hit.identifier, hit.title)
        for key, features in seed_feature_map.items():
            if key != current_key:
                seed_features.update(features)
        overlap = _hit_features(hit) & seed_features
        boost = min(MAX_ASSOCIATION_BOOST, 0.15 * len(overlap))
        if explanation.get("conflict_history"):
            boost = min(boost, 0.75)
            explanation["association_conflict_warning_preserved"] = True
        hit.score += boost
        explanation["association_score"] = boost
        explanation["association_overlap_count"] = len(overlap)
        explanation["association_mode"] = "candidate_set_local"
    return hits
