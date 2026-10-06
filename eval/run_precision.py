"""Compare precision@3 for plain search, rewriting, and rewriting plus filters."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.cache import RetrievalCache  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.ingest import open_collection  # noqa: E402
from src.retrieve import retrieve  # noqa: E402
from src.rewrite import rewrite_query  # noqa: E402

RESULTS = ROOT / "eval" / "results.md"


def precision_at_3(retrieved: list[str], expected: list[str]) -> float:
    """Fraction of the top 3 ids that appear in the labeled set."""
    top = retrieved[:3]
    hits = sum(1 for chunk_id in top if chunk_id in expected)
    return hits / 3


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


def main() -> None:
    cfg = get_settings()
    questions = json.loads((ROOT / "eval" / "questions.json").read_text())
    collection = open_collection(cfg.chroma_path, cfg.collection_name)
    stored = set(collection.get(include=[])["ids"])
    missing = sorted(
        {
            chunk_id
            for item in questions
            for chunk_id in item["expected_ids"]
            if chunk_id not in stored
        }
    )
    if missing:
        raise SystemExit(
            "Expected chunk ids are not in Chroma. Run python -m src.ingest first. Missing: "
            + ", ".join(missing)
        )

    cache = RetrievalCache(cfg.cache_path, cfg.cache_ttl_seconds)
    scores = {"plain": [], "rewrite": [], "rewrite_filters": []}
    fallbacks = 0
    for item in questions:
        rewritten = rewrite_query(item["question"])
        if rewritten.used_fallback:
            fallbacks += 1
        plain = retrieve(
            item["question"],
            {},
            3,
            collection=collection,
            cache=cache,
            use_cache=False,
        )
        rewritten_only = retrieve(
            rewritten.query,
            {},
            3,
            collection=collection,
            cache=cache,
            use_cache=False,
        )
        filtered = retrieve(
            rewritten.query,
            rewritten.filters,
            3,
            collection=collection,
            cache=cache,
            use_cache=False,
        )
        expected = item["expected_ids"]
        scores["plain"].append(
            precision_at_3([hit.chunk_id for hit in plain.hits], expected)
        )
        scores["rewrite"].append(
            precision_at_3([hit.chunk_id for hit in rewritten_only.hits], expected)
        )
        scores["rewrite_filters"].append(
            precision_at_3([hit.chunk_id for hit in filtered.hits], expected)
        )

    def average(values: list[float]) -> float:
        return sum(values) / len(values)

    plain = average(scores["plain"])
    rewrite = average(scores["rewrite"])
    both = average(scores["rewrite_filters"])
    note = (
        f"Questions: {len(questions)}. Rewrite fell back to the raw query with no filters "
        f"on {fallbacks} of {len(questions)} questions."
    )
    table = "\n".join(
        [
            "| Setup | Precision@3 |",
            "| --- | --- |",
            f"| Plain vector search | {plain:.4f} |",
            f"| Rewriting only | {rewrite:.4f} |",
            f"| Rewriting + metadata filters | {both:.4f} |",
            "",
            note,
        ]
    )
    print(table)
    upsert_section("Precision@3", table)


if __name__ == "__main__":
    main()
