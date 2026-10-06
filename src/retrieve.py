"""Metadata-filtered Chroma retrieval with relaxation and a result cache."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.cache import RetrievalCache, make_cache_key
from src.config import get_settings

FIELD_ORDER = ("service", "environment", "host", "owner", "failure_symptom")
RELAX_ORDER = ("failure_symptom", "host", "owner", "environment", "service")


@dataclass
class Hit:
    """One retrieved chunk, with the distance Chroma returned."""

    chunk_id: str
    text: str
    metadata: dict[str, Any]
    distance: float


@dataclass
class RetrievalResult:
    """Retrieved chunks plus the filter plan and cache status."""

    hits: list[Hit]
    cache_hit: bool
    filters_applied: dict[str, str]
    attempts: list[dict[str, Any]] = field(default_factory=list)


def _clean_filters(filters: dict[str, str] | None) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key in (*FIELD_ORDER, *RELAX_ORDER):
        if key in cleaned or not filters or key not in filters:
            continue
        value = filters[key]
        if isinstance(value, str) and value.strip():
            cleaned[key] = value.strip()
    return cleaned


def build_where(filters: dict[str, str] | None) -> dict[str, Any] | None:
    """Build a Chroma where clause. One field stays a flat dict; several use $and."""
    cleaned = _clean_filters(filters)
    clauses = [{key: cleaned[key]} for key in FIELD_ORDER if key in cleaned]
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def relaxation_steps(filters: dict[str, str] | None) -> list[dict[str, str]]:
    """Start with every filter, then drop one field at a time in RELAX_ORDER."""
    current = _clean_filters(filters)
    steps = [dict(current)]
    for key in RELAX_ORDER:
        if key in current:
            del current[key]
            steps.append(dict(current))
    return steps


def _hits_from_query(result: dict[str, Any]) -> list[Hit]:
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    hits: list[Hit] = []
    for chunk_id, text, metadata, distance in zip(ids, documents, metadatas, distances):
        meta = dict(metadata or {})
        hits.append(
            Hit(
                chunk_id=str(meta.get("chunk_id") or chunk_id),
                text=str(text or ""),
                metadata=meta,
                distance=float(distance),
            )
        )
    return hits


def _query(collection, query: str, k: int, where: dict[str, Any] | None) -> list[Hit]:
    if collection.count() == 0:
        return []
    kwargs: dict[str, Any] = {
        "query_texts": [query],
        "n_results": max(k, 1),
        "include": ["documents", "metadatas", "distances"],
    }
    if where is not None:
        kwargs["where"] = where
    return _hits_from_query(collection.query(**kwargs))


def _hit_to_dict(hit: Hit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "text": hit.text,
        "metadata": hit.metadata,
        "distance": hit.distance,
    }


def _hit_from_dict(payload: dict[str, Any]) -> Hit:
    return Hit(
        chunk_id=str(payload["chunk_id"]),
        text=str(payload["text"]),
        metadata=dict(payload.get("metadata") or {}),
        distance=float(payload["distance"]),
    )


def retrieve(
    query: str,
    filters: dict[str, str] | None = None,
    k: int = 5,
    *,
    collection=None,
    cache: RetrievalCache | None = None,
    use_cache: bool = True,
    min_results: int | None = None,
) -> RetrievalResult:
    """Search Chroma. Relax filters until there are enough hits. Cache the result."""
    cfg = get_settings()
    if collection is None:
        from src.ingest import open_collection

        collection = open_collection(cfg.chroma_path, cfg.collection_name)
    if cache is None:
        cache = RetrievalCache(cfg.cache_path, cfg.cache_ttl_seconds)
    needed = cfg.min_results_before_relax if min_results is None else min_results
    cleaned = _clean_filters(filters)
    key = make_cache_key(query, cleaned, k)
    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            return RetrievalResult(
                hits=[_hit_from_dict(item) for item in cached["hits"]],
                cache_hit=True,
                filters_applied=dict(cached.get("filters_applied") or {}),
                attempts=list(cached.get("attempts") or []),
            )

    attempts: list[dict[str, Any]] = []
    hits: list[Hit] = []
    applied: dict[str, str] = {}
    for plan in relaxation_steps(cleaned):
        where = build_where(plan)
        hits = _query(collection, query, k, where)
        applied = plan
        attempts.append({"filters": plan, "where": where, "count": len(hits)})
        if len(hits) >= needed or not plan:
            break

    result = RetrievalResult(
        hits=hits,
        cache_hit=False,
        filters_applied=applied,
        attempts=attempts,
    )
    if use_cache:
        cache.set(
            key,
            {
                "hits": [_hit_to_dict(hit) for hit in hits],
                "filters_applied": applied,
                "attempts": attempts,
            },
        )
    return result
