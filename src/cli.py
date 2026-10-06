"""Ask the infrastructure copilot from the terminal."""

from __future__ import annotations

import argparse
import time

from src.answer import generate_answer
from src.cache import RetrievalCache
from src.config import get_settings
from src.ingest import open_collection
from src.llm import LLMError
from src.retrieve import retrieve
from src.rewrite import rewrite_query


def _format_filters(filters: dict[str, str]) -> str:
    if not filters:
        return "(none)"
    return ", ".join(f"{key}={value}" for key, value in filters.items())


def main(argv: list[str] | None = None) -> int:
    """Rewrite a question, retrieve supporting chunks, and print a cited answer."""
    parser = argparse.ArgumentParser(description="Ask the infrastructure copilot.")
    parser.add_argument("question", help="Troubleshooting question")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip the rewrite cache and the retrieval cache",
    )
    parser.add_argument(
        "--show-sources",
        action="store_true",
        help="Print retrieved chunk text",
    )
    parser.add_argument(
        "--show-filters",
        action="store_true",
        help="Print each filter relaxation attempt",
    )
    args = parser.parse_args(argv)

    cfg = get_settings()
    started = time.perf_counter()
    use_cache = not args.no_cache
    cache = RetrievalCache(cfg.cache_path, cfg.cache_ttl_seconds)
    rewritten = rewrite_query(args.question, cache=cache, use_cache=use_cache)
    collection = open_collection(cfg.chroma_path, cfg.collection_name)
    result = retrieve(
        rewritten.query,
        rewritten.filters,
        cfg.retrieval_k,
        collection=collection,
        cache=cache,
        use_cache=not args.no_cache,
    )
    print(f"Rewritten query: {rewritten.query}")
    print(f"Filters: {_format_filters(rewritten.filters)}")
    print(f"Filters applied: {_format_filters(result.filters_applied)}")
    if args.no_cache:
        print("Rewrite cache: off")
        print("Cache: off")
    else:
        print(f"Rewrite cache: {'hit' if rewritten.cache_hit else 'miss'}")
        print(f"Cache: {'hit' if result.cache_hit else 'miss'}")
    if args.show_filters:
        for attempt in result.attempts:
            print(
                f"  attempt filters={_format_filters(attempt['filters'])} "
                f"hits={attempt['count']}"
            )
    if args.show_sources:
        for hit in result.hits:
            print(f"\n[{hit.chunk_id}] distance={hit.distance:.3f}")
            print(hit.text)
    try:
        answer = generate_answer(args.question, result.hits)
    except LLMError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"Latency: {elapsed_ms:.0f} ms")
        print(f"LLM request failed: {exc}")
        return 1
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"Latency: {elapsed_ms:.0f} ms")
    print()
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
