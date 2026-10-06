"""Cache hits, misses, expiry, and ingest invalidation."""

from src.cache import RetrievalCache, make_cache_key
from src.ingest import run_ingest
from tests.fake_embed import FakeEmbedder


def test_miss_hit_and_ttl(tmp_path):
    clock = {"now": 1_000.0}
    cache = RetrievalCache(tmp_path / "cache.sqlite", ttl_seconds=10, clock=lambda: clock["now"])
    assert cache.get("missing") is None
    cache.set("alpha", [{"chunk_id": "runbook:disk-full#0"}])
    assert cache.get("alpha") == [{"chunk_id": "runbook:disk-full#0"}]

    restarted = RetrievalCache(
        tmp_path / "cache.sqlite", ttl_seconds=10, clock=lambda: clock["now"]
    )
    assert restarted.get("alpha") == [{"chunk_id": "runbook:disk-full#0"}]

    clock["now"] = 1_011.0
    assert cache.get("alpha") is None
    assert restarted.get("alpha") is None


def test_key_changes_with_filters():
    left = make_cache_key("disk full", {"environment": "prod"}, 3)
    right = make_cache_key("disk full", {"environment": "staging"}, 3)
    assert left != right


def test_ingest_invalidates_cache(tmp_path):
    data = tmp_path / "data"
    runbooks = data / "runbooks"
    runbooks.mkdir(parents=True)
    (data / "ownership.csv").write_text(
        "service,owner,oncall\npayments-db,Payments Platform,Avery Chen\n"
    )
    (data / "inventory.csv").write_text(
        "host,service,environment,region\npayments-db-01,payments-db,prod,us-east-1\n"
    )
    (data / "incidents.json").write_text(
        '[{"id":"inc-900","date":"2026-01-01","host":"payments-db-01",'
        '"service":"payments-db","environment":"prod","symptom":"disk full",'
        '"root_cause":"volume filled","fix":"deleted archives"}]'
    )
    (runbooks / "disk-full.md").write_text(
        "---\nservice: payments-db\nenvironment: prod\nhost: payments-db-01\n"
        "failure_symptom: disk full\n---\n\n## Symptoms\nDisk is full on payments-db-01.\n"
    )
    cache = RetrievalCache(tmp_path / "cache.sqlite", ttl_seconds=3600)
    cache.set("stale", [{"chunk_id": "old"}])
    stats = run_ingest(
        data_dir=data,
        chroma_path=tmp_path / "chroma",
        collection_name="tiny",
        cache=cache,
        embedding_function=FakeEmbedder(),
    )
    assert stats.stored > 0
    assert cache.get("stale") is None
