"""Filter clauses and relaxation order."""

from src.cache import RetrievalCache
from src.retrieve import build_where, relaxation_steps, retrieve


class RecordingCollection:
    """Returns one hit for a narrow filter and three hits for a broad one."""

    def __init__(self) -> None:
        self.wheres: list[dict | None] = []

    def count(self) -> int:
        return 5

    def query(self, query_texts, n_results, where=None, include=None):
        self.wheres.append(where)
        broad = where is None or ("$and" not in where and "service" in where)
        count = 3 if broad else 1
        ids = [f"id-{index}" for index in range(count)]
        return {
            "ids": [ids],
            "documents": [["text"] * count],
            "metadatas": [[{"chunk_id": chunk_id} for chunk_id in ids]],
            "distances": [[0.2] * count],
        }


def test_where_clauses():
    assert build_where({}) is None
    assert build_where({"service": "  ", "host": ""}) is None
    assert build_where({"service": "payments-db"}) == {"service": "payments-db"}
    assert build_where({"environment": "prod", "service": "payments-db"}) == {
        "$and": [{"service": "payments-db"}, {"environment": "prod"}]
    }
    assert build_where(
        {
            "failure_symptom": "disk full",
            "host": "payments-db-01",
            "service": "payments-db",
        }
    ) == {
        "$and": [
            {"service": "payments-db"},
            {"host": "payments-db-01"},
            {"failure_symptom": "disk full"},
        ]
    }


def test_relaxation_order():
    filters = {
        "failure_symptom": "disk full",
        "host": "payments-db-01",
        "owner": "Payments Platform",
        "environment": "prod",
        "service": "payments-db",
    }
    steps = relaxation_steps(filters)
    assert set(steps[0]) - set(steps[1]) == {"failure_symptom"}
    assert set(steps[1]) - set(steps[2]) == {"host"}
    assert set(steps[2]) - set(steps[3]) == {"owner"}
    assert set(steps[3]) - set(steps[4]) == {"environment"}
    assert steps[4] == {"service": "payments-db"}
    assert steps[5] == {}


def test_retrieve_relaxes_until_enough_hits(tmp_path):
    collection = RecordingCollection()
    cache = RetrievalCache(tmp_path / "cache.sqlite", ttl_seconds=60)
    filters = {
        "host": "payments-db-01",
        "environment": "prod",
        "service": "payments-db",
    }
    result = retrieve(
        "disk full",
        filters,
        k=3,
        collection=collection,
        cache=cache,
        min_results=2,
    )
    assert result.cache_hit is False
    assert len(result.hits) == 3
    assert collection.wheres == [
        {
            "$and": [
                {"service": "payments-db"},
                {"environment": "prod"},
                {"host": "payments-db-01"},
            ]
        },
        {"$and": [{"service": "payments-db"}, {"environment": "prod"}]},
        {"service": "payments-db"},
    ]
    cached = retrieve(
        "disk full",
        filters,
        k=3,
        collection=collection,
        cache=cache,
        min_results=2,
    )
    assert cached.cache_hit is True
    assert len(collection.wheres) == 3
