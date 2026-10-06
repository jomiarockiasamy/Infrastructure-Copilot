"""Measure retrieval latency and end-to-end latency, cache off versus warm."""

from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.cache import RetrievalCache  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.ingest import open_collection  # noqa: E402
from src.retrieve import retrieve  # noqa: E402
from src.rewrite import rewrite_query  # noqa: E402

RESULTS = ROOT / "eval" / "results.md"


def percentile(values: list[float], pct: float) -> float:
    """Linear percentile. pct is in the 0-100 range."""
    if not values:
        raise ValueError("no samples")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def upsert_section(heading: str, body: str) -> None:
    """Replace one markdown section, keeping the other eval results."""
    heading_line = f"## {heading}"
    block = f"{heading_line}\n\n{body.strip()}\n"
    text = RESULTS.read_text() if RESULTS.exists() else "# Evaluation results\n\n"
    pattern = rf"## {re.escape(heading)}\n.*?(?=\n## |\Z)"
    if re.search(pattern, text, flags=re.S):
        text = re.sub(pattern, block.rstrip() + "\n", text, count=1, flags=re.S)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text = text.rstrip() + "\n\n" + block
    RESULTS.write_text(text if text.endswith("\n") else text + "\n")


def _reduction(off_ms: float, warm_ms: float) -> float:
    if off_ms == 0:
        return 0.0
    return (off_ms - warm_ms) / off_ms * 100


def _table(off: list[float], warm: list[float], note: str) -> str:
    median_off = percentile(off, 50)
    p95_off = percentile(off, 95)
    median_warm = percentile(warm, 50)
    p95_warm = percentile(warm, 95)
    reduction = _reduction(median_off, median_warm)
    return "\n".join(
        [
            "| Mode | Samples | Median (ms) | P95 (ms) |",
            "| --- | --- | --- | --- |",
            f"| Cache off | {len(off)} | {median_off:.2f} | {p95_off:.2f} |",
            f"| Cache on, warm | {len(warm)} | {median_warm:.2f} | {p95_warm:.2f} |",
            "",
            (
                f"Median reduction, warm versus cache off: {reduction:.2f}% "
                f"(({median_off:.2f} - {median_warm:.2f}) / {median_off:.2f})."
            ),
            note,
        ]
    )


def _time_retrieval(collection, cache: RetrievalCache, query: str, use_cache: bool) -> float:
    started = time.perf_counter()
    retrieve(query, {}, 3, collection=collection, cache=cache, use_cache=use_cache)
    return (time.perf_counter() - started) * 1000


def _time_end_to_end(collection, cache: RetrievalCache, question: str, use_cache: bool) -> tuple[float, bool, bool]:
    """Time rewrite plus retrieval. Returns elapsed ms, cache_hit, used_fallback."""
    started = time.perf_counter()
    rewritten = rewrite_query(question, cache=cache, use_cache=use_cache)
    retrieve(
        rewritten.query,
        rewritten.filters,
        3,
        collection=collection,
        cache=cache,
        use_cache=use_cache,
    )
    elapsed = (time.perf_counter() - started) * 1000
    return elapsed, rewritten.cache_hit, rewritten.used_fallback


def _measure(samples_fn, queries: list[str], repeats: int) -> list[float]:
    measured: list[float] = []
    for _ in range(repeats):
        for query in queries:
            measured.append(samples_fn(query))
    return measured


def main() -> None:
    cfg = get_settings()
    questions = json.loads((ROOT / "eval" / "questions.json").read_text())
    queries = [item["question"] for item in questions[:12]]
    collection = open_collection(cfg.chroma_path, cfg.collection_name)
    if collection.count() == 0:
        raise SystemExit("Chroma collection is empty. Run python -m src.ingest first.")

    cache = RetrievalCache(cfg.chroma_path / "latency_cache.sqlite", ttl_seconds=3600)
    repeats = 4

    cache.clear()
    retrieval_off = _measure(
        lambda query: _time_retrieval(collection, cache, query, False),
        queries,
        repeats,
    )
    for query in queries:
        _time_retrieval(collection, cache, query, True)
    retrieval_warm = _measure(
        lambda query: _time_retrieval(collection, cache, query, True),
        queries,
        repeats,
    )

    cache.clear()
    fallbacks = {"n": 0}
    model_calls = {"n": 0}

    def time_off(question: str) -> float:
        elapsed, _hit, fallback = _time_end_to_end(collection, cache, question, False)
        if fallback:
            fallbacks["n"] += 1
        else:
            model_calls["n"] += 1
        return elapsed

    end_off = _measure(time_off, queries, repeats)
    for query in queries:
        _time_end_to_end(collection, cache, query, True)
    end_warm = _measure(
        lambda question: _time_end_to_end(collection, cache, question, True)[0],
        queries,
        repeats,
    )

    if model_calls["n"] == 0:
        end_note = (
            "Cache-off rewrite did not reach an LLM "
            f"({fallbacks['n']} fallbacks). "
            "This timing is the fallback plus retrieval, not a live model call. "
            "A warm hit skips both the rewrite call and the Chroma query."
        )
    else:
        end_note = (
            f"Cache-off includes the rewrite model call ({model_calls['n']} calls, "
            f"{fallbacks['n']} fallbacks). "
            "A warm hit skips that call and the Chroma query."
        )

    retrieval_table = _table(
        retrieval_off,
        retrieval_warm,
        "Retrieval stage only: embedding plus Chroma, or a cache read. Rewrite is not included.",
    )
    end_table = _table(end_off, end_warm, end_note)
    body = "\n".join(
        [
            "### Retrieval stage",
            "",
            retrieval_table,
            "",
            "### End to end, including rewrite",
            "",
            end_table,
        ]
    )
    print(body)
    upsert_section("Latency", body)


if __name__ == "__main__":
    main()
