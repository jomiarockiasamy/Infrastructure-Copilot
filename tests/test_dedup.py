"""Dedup skips exact hashes and near-duplicate embeddings."""

from src.ingest import Chunk, content_hash, load_chunks, open_collection, store_chunks
from tests.fake_embed import FakeEmbedder


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        source_type="runbook",
        service="payments-db",
        environment="prod",
        owner="Payments Platform",
        failure_symptom="disk full",
    )


def test_source_data_contains_exact_duplicates():
    chunks = load_chunks()
    hashes = [content_hash(chunk.text) for chunk in chunks]
    assert len(hashes) - len(set(hashes)) >= 2


def test_skips_exact_and_near_duplicates(tmp_path):
    collection = open_collection(tmp_path / "chroma", "dedup", FakeEmbedder())
    chunks = [
        _chunk("a", "alpha procedure for disk cleanup"),
        _chunk("b", "alpha   procedure\nfor disk cleanup"),
        _chunk("c", "FAMILY_A first wording of the maintenance note"),
        _chunk("d", "FAMILY_A second wording of the maintenance note"),
        _chunk("e", "unrelated dns zone restore procedure"),
    ]
    stats = store_chunks(chunks, collection, similarity_threshold=0.95)
    assert stats.exact_skipped == 1
    assert stats.near_skipped == 1
    assert stats.stored == 3
    stored = collection.get(include=[])
    assert set(stored["ids"]) == {"a", "c", "e"}
