"""Query rewrite parsing, with the LLM mocked."""

import json

from src.cache import RetrievalCache
from src.rewrite import parse_rewrite, rewrite_query


def test_valid_rewrite_extracts_filters():
    raw = json.dumps(
        {
            "query": "payments database disk full",
            "filters": {
                "service": "payments-db",
                "environment": "prod",
                "host": None,
                "owner": "",
                "failure_symptom": "disk full",
            },
        }
    )
    result = rewrite_query("messy question", complete_fn=lambda _prompt: raw, catalog="catalog")
    assert result.used_fallback is False
    assert result.query == "payments database disk full"
    assert result.filters == {
        "service": "payments-db",
        "environment": "prod",
        "failure_symptom": "disk full",
    }


def test_invalid_json_falls_back_to_raw_query():
    result = rewrite_query(
        "why is the payments db timing out?",
        complete_fn=lambda _prompt: "I am not json",
        catalog="catalog",
    )
    assert result.used_fallback is True
    assert result.query == "why is the payments db timing out?"
    assert result.filters == {}


def test_llm_exception_falls_back():
    def explode(_prompt: str) -> str:
        raise RuntimeError("provider down")

    result = rewrite_query("raw question", complete_fn=explode, catalog="catalog")
    assert result.used_fallback is True
    assert result.query == "raw question"
    assert result.filters == {}


def test_repeat_question_skips_the_llm(tmp_path):
    calls = {"n": 0}

    def complete(_prompt: str) -> str:
        calls["n"] += 1
        return json.dumps(
            {"query": "disk full", "filters": {"service": "payments-db", "environment": "prod"}}
        )

    cache = RetrievalCache(tmp_path / "cache.sqlite", ttl_seconds=60)
    first = rewrite_query(
        "Why   is DISK full?",
        complete_fn=complete,
        catalog="catalog",
        cache=cache,
    )
    second = rewrite_query(
        "why is disk full?",
        complete_fn=complete,
        catalog="catalog",
        cache=cache,
    )
    assert calls["n"] == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.query == "disk full"
    assert second.filters == first.filters


def test_rewrite_cache_expires(tmp_path):
    clock = {"now": 1_000.0}
    calls = {"n": 0}

    def complete(_prompt: str) -> str:
        calls["n"] += 1
        return json.dumps({"query": "disk full", "filters": {}})

    cache = RetrievalCache(
        tmp_path / "cache.sqlite",
        ttl_seconds=10,
        clock=lambda: clock["now"],
    )
    rewrite_query("disk full?", complete_fn=complete, catalog="catalog", cache=cache)
    clock["now"] = 1_011.0
    rewrite_query("disk full?", complete_fn=complete, catalog="catalog", cache=cache)
    assert calls["n"] == 2


def test_parse_rejects_non_string_filter():
    raw = '{"query": "disk", "filters": {"host": 12}}'
    result = parse_rewrite(raw, "original question")
    assert result.used_fallback is True
    assert result.query == "original question"
