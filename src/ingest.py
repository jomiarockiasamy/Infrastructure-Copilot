"""Load fake infrastructure documents, chunk them, and store them in Chroma."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from src.cache import RetrievalCache
from src.config import get_settings

logger = logging.getLogger(__name__)

METADATA_FIELDS = (
    "source_type",
    "host",
    "service",
    "environment",
    "owner",
    "failure_symptom",
    "chunk_id",
)


@dataclass
class Chunk:
    """One retrievable piece of a runbook, inventory row, ownership row, or incident."""

    chunk_id: str
    text: str
    source_type: str
    host: str = ""
    service: str = ""
    environment: str = ""
    owner: str = ""
    failure_symptom: str = ""

    def metadata(self) -> dict[str, str]:
        """Metadata stored beside the chunk, including a content hash for exact dedup."""
        meta = {
            "source_type": self.source_type,
            "host": self.host,
            "service": self.service,
            "environment": self.environment,
            "owner": self.owner,
            "failure_symptom": self.failure_symptom,
            "chunk_id": self.chunk_id,
            "content_hash": content_hash(self.text),
        }
        return meta


@dataclass
class IngestStats:
    """Counts from one ingest run."""

    stored: int
    exact_skipped: int
    near_skipped: int


def normalize_text(text: str) -> str:
    """Lowercase text and collapse whitespace so exact copies hash the same."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def content_hash(text: str) -> str:
    """Stable hash of normalized chunk text."""
    return hashlib.sha256(normalize_text(text).encode()).hexdigest()


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, parts[2]


def _split_sections(body: str) -> list[str]:
    parts = re.split(r"(?=^##\s)", body.strip(), flags=re.MULTILINE)
    return [part.strip() for part in parts if part.strip()]


def _owner_map(data_dir: Path) -> dict[str, str]:
    path = data_dir / "ownership.csv"
    owners: dict[str, str] = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            owners[row["service"].strip()] = row["owner"].strip()
    return owners


def load_chunks(data_dir: Path | None = None) -> list[Chunk]:
    """Read every source file and return chunks with joined owner metadata."""
    root = data_dir or get_settings().data_dir
    owners = _owner_map(root)
    chunks: list[Chunk] = []
    chunks.extend(_load_runbooks(root / "runbooks", owners))
    chunks.extend(_load_inventory(root / "inventory.csv", owners))
    chunks.extend(_load_ownership(root / "ownership.csv"))
    chunks.extend(_load_incidents(root / "incidents.json", owners))
    return chunks


def _load_runbooks(directory: Path, owners: dict[str, str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        meta, body = _parse_frontmatter(path.read_text())
        service = meta.get("service", "")
        for index, section in enumerate(_split_sections(body)):
            chunks.append(
                Chunk(
                    chunk_id=f"runbook:{path.stem}#{index}",
                    text=section,
                    source_type="runbook",
                    host=meta.get("host", ""),
                    service=service,
                    environment=meta.get("environment", ""),
                    owner=owners.get(service, ""),
                    failure_symptom=meta.get("failure_symptom", ""),
                )
            )
    return chunks


# Distinct duties keep short inventory rows from embedding as near-duplicates.
HOST_NOTES = {
    "payments-db-01": "Primary writer for card charges. The live WAL volume sits on this host.",
    "payments-db-02": "West-coast read replica. It applies shipped WAL and never accepts charge writes.",
    "payments-db-03": "Staging sandbox used for replay drills. Archive cleanup is easy to leave off.",
    "payments-db-04": "Developer scratch database. Schema migrations land here before review.",
    "payments-db-05": "EU primary for card charges. Checkpoints can stall readers after a bulk load.",
    "checkout-api-01": "Production storefront that prices carts and calls the payments pool.",
    "checkout-api-02": "EU storefront. Traffic shifts here when the us-east path is congested.",
    "checkout-api-03": "Staging storefront used for promo benchmarks and failover tests.",
    "checkout-api-04": "Dev storefront. Feature flags default off after the unfinished discount path.",
    "auth-01": "Production login host. The certificate name must match this hostname.",
    "auth-02": "Second production login host. Mobile retry storms hit its rate limit.",
    "auth-03": "Staging login host used for certificate name-rotation rehearsals.",
    "dns-01": "Production resolver for internal names such as checkout.internal.",
    "dns-02": "EU production resolver. It forwards recursion through a secondary upstream.",
    "dns-03": "Staging resolver pointed at the staging zone, not the prod serial.",
    "edge-01": "Public prod proxy in us-east-1. It terminates tls and balances checkout.",
    "edge-02": "West-coast public proxy. It stays in reserve when us-east is healthy.",
    "edge-03": "Staging proxy used for certificate labs and chaos drills.",
    "edge-04": "EU public proxy. Packet loss on the peering link diverts traffic away.",
    "kafka-01": "Production broker that leads the payments topic consumer group.",
    "kafka-02": "Second production broker. Clock skew here rejects produce requests.",
    "kafka-03": "Staging broker for scratch topics and poison-message drills.",
    "kafka-04": "Dev broker. New topic configs are tried here first.",
    "redis-01": "Production cache for checkout carts. Eviction starts when maxmemory is hit.",
    "redis-02": "West-coast cache replica. A bad import once ignored its memory cap.",
    "redis-03": "Tiny staging cache used in class exercises.",
    "worker-01": "Production async worker. A bad config mount crashloops this pod.",
    "worker-02": "EU production worker. Deploys here can pause the job queue.",
    "worker-03": "Staging worker. Flag-file typos are caught on this host.",
    "billing-01": "Production invoice api. The PDF cache must stay bounded.",
    "billing-02": "Staging invoice api used when the profiler is attached.",
    "billing-03": "Dev invoice api. Failed smoke tests roll this host back.",
    "inventory-01": "Production catalog api. Nightly snapshots need an object-storage credential.",
    "inventory-02": "EU catalog api. Debug logs here can exhaust inodes.",
    "inventory-03": "Staging catalog api for reindex locks.",
    "notify-01": "Production notifier. Partner webhooks must time out quickly.",
    "notify-02": "Staging notifier. Retries need jitter so a dead webhook cannot storm.",
    "search-01": "Production product search. Leading-wildcard queries are rejected.",
    "search-02": "West-coast search replica serving the same product index.",
    "search-03": "Staging search. Reindex locks can pause product updates.",
}


def _load_inventory(path: Path, owners: dict[str, str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            host = row["host"].strip()
            service = row["service"].strip()
            environment = row["environment"].strip()
            region = row["region"].strip()
            owner = owners.get(service, "")
            note = HOST_NOTES.get(host, "General purpose host.")
            text = (
                f"Host {host} runs service {service} in the {environment} environment "
                f"in region {region}. Owner team: {owner}. {note}"
            )
            chunks.append(
                Chunk(
                    chunk_id=f"inventory:{host}",
                    text=text,
                    source_type="inventory",
                    host=host,
                    service=service,
                    environment=environment,
                    owner=owner,
                )
            )
    return chunks


def _load_ownership(path: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            service = row["service"].strip()
            owner = row["owner"].strip()
            oncall = row["oncall"].strip()
            text = (
                f"Service {service} is owned by {owner}. "
                f"On-call contact: {oncall}."
            )
            chunks.append(
                Chunk(
                    chunk_id=f"ownership:{service}",
                    text=text,
                    source_type="ownership",
                    service=service,
                    owner=owner,
                )
            )
    return chunks


def _load_incidents(path: Path, owners: dict[str, str]) -> list[Chunk]:
    records = json.loads(path.read_text())
    chunks: list[Chunk] = []
    for record in records:
        service = str(record["service"])
        chunk_id = f"incident:{record['id']}"
        text = (
            f"Incident {record['id']} on {record['date']}. "
            f"Host {record['host']}, service {service}, environment {record['environment']}. "
            f"Symptom: {record['symptom']}. "
            f"Root cause: {record['root_cause']} "
            f"Fix: {record['fix']}"
        )
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                text=text,
                source_type="incident",
                host=str(record["host"]),
                service=service,
                environment=str(record["environment"]),
                owner=owners.get(service, ""),
                failure_symptom=str(record["symptom"]),
            )
        )
    return chunks


def open_collection(path: Path, name: str, embedding_function=None):
    """Open a persistent Chroma collection that uses cosine distance."""
    import chromadb

    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(path))
    kwargs: dict = {
        "name": name,
        "metadata": {"hnsw:space": "cosine"},
    }
    if embedding_function is not None:
        kwargs["embedding_function"] = embedding_function
    return client.get_or_create_collection(**kwargs)


def _stored_hashes(collection) -> set[str]:
    if collection.count() == 0:
        return set()
    payload = collection.get(include=["metadatas"])
    hashes: set[str] = set()
    for meta in payload.get("metadatas") or []:
        if meta and meta.get("content_hash"):
            hashes.add(str(meta["content_hash"]))
    return hashes


def nearest_similarity(collection, text: str) -> float | None:
    """Return cosine similarity of the closest stored chunk, if any."""
    if collection.count() == 0:
        return None
    result = collection.query(query_texts=[text], n_results=1, include=["distances"])
    distances = result.get("distances") or []
    if not distances or not distances[0]:
        return None
    return 1.0 - float(distances[0][0])


def store_chunks(
    chunks: list[Chunk],
    collection,
    *,
    cache: RetrievalCache | None = None,
    similarity_threshold: float = 0.95,
) -> IngestStats:
    """Embed and store chunks, skipping exact hashes and near-duplicates."""
    seen = _stored_hashes(collection)
    stored = exact_skipped = near_skipped = 0
    for chunk in chunks:
        if not normalize_text(chunk.text):
            continue
        digest = content_hash(chunk.text)
        if digest in seen:
            exact_skipped += 1
            logger.info("skipped exact duplicate %s", chunk.chunk_id)
            continue
        similarity = nearest_similarity(collection, chunk.text)
        if similarity is not None and similarity > similarity_threshold:
            near_skipped += 1
            logger.info(
                "skipped near duplicate %s similarity=%.3f",
                chunk.chunk_id,
                similarity,
            )
            continue
        collection.upsert(
            ids=[chunk.chunk_id],
            documents=[chunk.text],
            metadatas=[chunk.metadata()],
        )
        seen.add(digest)
        stored += 1
    if stored and cache is not None:
        cache.invalidate()
    return IngestStats(stored=stored, exact_skipped=exact_skipped, near_skipped=near_skipped)


def run_ingest(
    data_dir: Path | None = None,
    chroma_path: Path | None = None,
    collection_name: str | None = None,
    cache: RetrievalCache | None = None,
    embedding_function=None,
    similarity_threshold: float | None = None,
) -> IngestStats:
    """Load the fake corpus and store new chunks. Invalidate the cache when data is added."""
    cfg = get_settings()
    chunks = load_chunks(data_dir or cfg.data_dir)
    collection = open_collection(
        chroma_path or cfg.chroma_path,
        collection_name or cfg.collection_name,
        embedding_function,
    )
    active_cache = cache
    if active_cache is None and chroma_path is None:
        active_cache = RetrievalCache(cfg.cache_path, cfg.cache_ttl_seconds)
    return store_chunks(
        chunks,
        collection,
        cache=active_cache,
        similarity_threshold=(
            cfg.dedup_similarity_threshold
            if similarity_threshold is None
            else similarity_threshold
        ),
    )


def main() -> None:
    """Ingest the corpus and print how many chunks were stored or skipped."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stats = run_ingest()
    print(f"exact duplicates skipped: {stats.exact_skipped}")
    print(f"near duplicates skipped: {stats.near_skipped}")
    print(f"chunks stored: {stats.stored}")


if __name__ == "__main__":
    main()
