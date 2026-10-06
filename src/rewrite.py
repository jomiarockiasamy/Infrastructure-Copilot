"""Turn a messy question into a search query and optional metadata filters."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from src.cache import RetrievalCache
from src.llm import complete

FILTER_KEYS = ("host", "service", "environment", "owner", "failure_symptom")

ALIASES = """
Canonical values:
- environment: prod, staging, dev. "production" and "live" mean prod. "stage" means staging.
- service payments-db: payments db, payments database, card charge datastore, card charges
- service checkout-api: checkout, storefront, storefront api
- service auth-service: auth, login
- service dns-resolver: dns, resolver
- service edge-proxy: edge, public proxy, load balancer
- service kafka: kafka, stream cluster
- service redis: redis, cache node
- service worker: worker, async job pod
- service billing-api: billing, invoice api
- service inventory-api: inventory
- service notifications: notifications, notify
- service search-api: search
- failure_symptom "disk full": disk full, no space left, volume filled, out of disk
- failure_symptom "high cpu": high cpu, pegged cpu, burning a core
- failure_symptom "dns failure": dns failure, NXDOMAIN, can't resolve
- failure_symptom "crashloop": crashloop, keeps restarting
- failure_symptom "expired tls": expired tls, expired certificate, certificate date is past
- failure_symptom "connection pool exhausted": connection pool, pool exhausted, timing out, refusing new db sessions
- failure_symptom "memory leak": memory leak, leaking memory
- failure_symptom "network latency": network latency, sluggish downstream
- failure_symptom "consumer lag": consumer lag, behind on the topic
- failure_symptom "cache eviction": cache eviction, evicting keys, dropping keys
- failure_symptom "upstream 5xx": upstream 5xx, server errors, 5xx
- failure_symptom "certificate mismatch": certificate mismatch, cert name is wrong
Use owner team names exactly as listed below when the question names a team or on-call person.
""".strip()


@dataclass
class RewriteResult:
    """Clean query plus validated filters. used_fallback is true when parsing failed."""

    query: str
    filters: dict[str, str]
    used_fallback: bool
    cache_hit: bool = False


def normalize_question(question: str) -> str:
    """Lowercase and collapse whitespace so repeat questions share a cache key."""
    return re.sub(r"\s+", " ", question.lower()).strip()


def rewrite_cache_key(question: str) -> str:
    """Key the rewrite cache by the normalized raw question."""
    digest = hashlib.sha256(normalize_question(question).encode()).hexdigest()
    return f"rewrite:{digest}"


def parse_rewrite(raw: str, original: str) -> RewriteResult:
    """Parse model JSON. On any problem, keep the raw question and use no filters."""
    try:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match is None:
            raise ValueError("no json object")
        data = json.loads(match.group(0))
        query = data.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("missing query")
        filters_in = data.get("filters", {})
        if filters_in is None:
            filters_in = {}
        if not isinstance(filters_in, dict):
            raise ValueError("filters must be an object")
        filters: dict[str, str] = {}
        for key in FILTER_KEYS:
            value = filters_in.get(key)
            if value is None or value == "":
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"bad filter {key}")
            filters[key] = value.strip()
        return RewriteResult(query=query.strip(), filters=filters, used_fallback=False)
    except (json.JSONDecodeError, ValueError, TypeError):
        return RewriteResult(query=original, filters={}, used_fallback=True)


def _catalog(data_dir=None) -> str:
    from src.ingest import load_chunks

    chunks = load_chunks(data_dir)
    services = sorted({c.service for c in chunks if c.service})
    owners = sorted({c.owner for c in chunks if c.owner})
    hosts = sorted({c.host for c in chunks if c.host})
    symptoms = sorted({c.failure_symptom for c in chunks if c.failure_symptom})
    return "\n".join(
        [
            "services: " + ", ".join(services),
            "owners: " + ", ".join(owners),
            "hosts: " + ", ".join(hosts),
            "failure_symptom values: " + ", ".join(symptoms),
        ]
    )


def build_prompt(question: str, catalog: str) -> str:
    """Prompt the model for a JSON search query and optional filters."""
    return f"""You rewrite infrastructure troubleshooting questions for search.
Return JSON only, with this shape:
{{"query": "short search query", "filters": {{"host": null, "service": null, "environment": null, "owner": null, "failure_symptom": null}}}}
Use null for any filter the question does not support. Copy filter values exactly from the catalog.
{ALIASES}

Catalog:
{catalog}

Question: {question}
"""


def _from_cache(payload: dict) -> RewriteResult:
    return RewriteResult(
        query=str(payload["query"]),
        filters={str(key): str(value) for key, value in dict(payload["filters"]).items()},
        used_fallback=bool(payload["used_fallback"]),
        cache_hit=True,
    )


def rewrite_query(
    question: str,
    *,
    complete_fn: Callable[[str], str] | None = None,
    catalog: str | None = None,
    cache: RetrievalCache | None = None,
    use_cache: bool = True,
) -> RewriteResult:
    """Rewrite a question with the LLM. A cached normalized question skips that call."""
    key = rewrite_cache_key(question)
    if cache is not None and use_cache:
        cached = cache.get(key)
        if cached is not None:
            return _from_cache(cached)

    caller = complete_fn or (lambda prompt: complete(prompt, max_tokens=400))
    prompt = build_prompt(question, catalog if catalog is not None else _catalog())
    try:
        raw = caller(prompt)
        result = parse_rewrite(raw, question)
    except Exception:
        result = RewriteResult(query=question, filters={}, used_fallback=True)
    if cache is not None and use_cache:
        cache.set(
            key,
            {
                "query": result.query,
                "filters": result.filters,
                "used_fallback": result.used_fallback,
            },
        )
    return result
