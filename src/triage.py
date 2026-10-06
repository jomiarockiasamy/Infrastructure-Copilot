"""Turn a pasted page into a runbook checklist, last fix, and blast radius.

The checklist and the last fix are read from files. A model narrative is added
only when an API key is set, and only from chunks the retriever returned.
"""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.catalog import Catalog, Edge, load_catalog, load_incidents
from src.link import LinkResult, link_text
from src.retrieve import Hit

logger = logging.getLogger(__name__)

CONFIDENCE_NOTES = {
    "strong": "Host and symptom are in the inventory, so the runbook is specific.",
    "partial": "Part of the page matched the inventory. Read the lit signals before you act.",
    "weak": "Nothing on the page matched a host, service, or symptom. No runbook was guessed.",
}


@dataclass
class SimilarIncident:
    """A past incident that shares a host, service, or symptom with this page."""

    incident_id: str
    date: str
    host: str
    service: str
    environment: str
    symptom: str
    root_cause: str
    fix: str
    reasons: list[str]
    score: int


@dataclass
class Touch:
    """One dependency edge, from the caller's point of view or the callee's."""

    service: str
    why: str


@dataclass
class Evidence:
    """One retrieved chunk, trimmed for the desk."""

    chunk_id: str
    source_type: str
    distance: float
    text: str


@dataclass
class Runbook:
    """The first Symptoms, Likely cause, and Steps sections of one runbook file."""

    stem: str
    service: str
    environment: str
    host: str
    symptom: str
    likely_cause: str
    steps: list[str]


@dataclass
class Card:
    """What the desk shows for one page."""

    text: str
    host: str = ""
    service: str = ""
    environment: str = ""
    region: str = ""
    symptom: str = ""
    owner: str = ""
    oncall: str = ""
    confidence: str = "weak"
    confidence_note: str = ""
    warning: str = ""
    ambiguous_services: list[str] = field(default_factory=list)
    runbook: str = ""
    likely_cause: str = ""
    checklist: list[str] = field(default_factory=list)
    similar: list[SimilarIncident] = field(default_factory=list)
    callers: list[Touch] = field(default_factory=list)
    needs: list[Touch] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    index_status: str = "ok"
    narrative: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready card, including the four linker signals."""
        payload = asdict(self)
        payload["signals"] = [
            {"name": "host", "value": self.host},
            {"name": "service", "value": self.service},
            {"name": "environment", "value": self.environment},
            {"name": "symptom", "value": self.symptom},
        ]
        return payload


def _sections(body: str) -> dict[str, str]:
    parts = re.split(r"(?=^##\s)", body.strip(), flags=re.MULTILINE)
    found: dict[str, str] = {}
    for part in parts:
        lines = part.splitlines()
        if not lines or not lines[0].startswith("##"):
            continue
        title = lines[0][2:].strip().lower()
        if title in found:
            continue
        found[title] = "\n".join(lines[1:]).strip()
    return found


def split_steps(text: str) -> list[str]:
    """Split a runbook Steps paragraph into sentences."""
    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return []
    parts = re.split(r"(?<=\.)\s+(?=[A-Z])", flat)
    return [part.strip() for part in parts if part.strip()]


def load_runbooks(data_dir: Path) -> list[Runbook]:
    """Read runbook files. A repeated Steps heading is ignored."""
    directory = data_dir / "runbooks"
    runbooks: list[Runbook] = []
    if not directory.is_dir():
        return runbooks
    for path in sorted(directory.glob("*.md")):
        text = path.read_text()
        meta: dict[str, str] = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].splitlines():
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip()
                body = parts[2]
        sections = _sections(body)
        runbooks.append(
            Runbook(
                stem=path.stem,
                service=meta.get("service", ""),
                environment=meta.get("environment", ""),
                host=meta.get("host", ""),
                symptom=meta.get("failure_symptom", ""),
                likely_cause=re.sub(r"\s+", " ", sections.get("likely cause", "")).strip(),
                steps=split_steps(sections.get("steps", "")),
            )
        )
    return runbooks


def choose_runbook(
    runbooks: list[Runbook],
    *,
    service: str,
    symptom: str,
    host: str,
    environment: str,
) -> Runbook | None:
    """Use the runbook for this symptom, preferring the same host. Never guess a symptom."""
    if not symptom:
        return None
    pool = [book for book in runbooks if book.symptom == symptom]
    if not pool:
        return None

    def rank(book: Runbook) -> tuple[int, int, int]:
        return (
            int(bool(host) and book.host == host),
            int(bool(service) and book.service == service),
            int(bool(environment) and book.environment == environment),
        )

    return max(pool, key=rank)


def rank_incidents(
    incidents: list[dict[str, str]],
    *,
    host: str,
    service: str,
    environment: str,
    symptom: str,
    limit: int = 3,
) -> list[SimilarIncident]:
    """Rank past incidents that share this failure. Environment alone is not enough."""
    ranked: list[SimilarIncident] = []
    for record in incidents:
        reasons: list[str] = []
        score = 0
        same_symptom = bool(symptom) and record.get("symptom") == symptom
        if symptom and not same_symptom:
            continue
        if same_symptom:
            score += 4
            reasons.append("same symptom")
        if host and record.get("host") == host:
            score += 3
            reasons.append("same host")
        if service and record.get("service") == service:
            score += 2
            reasons.append("same service")
        if score == 0:
            continue
        if environment and record.get("environment") == environment:
            score += 1
            reasons.append("same environment")
        ranked.append(
            SimilarIncident(
                incident_id=record.get("id", ""),
                date=record.get("date", ""),
                host=record.get("host", ""),
                service=record.get("service", ""),
                environment=record.get("environment", ""),
                symptom=record.get("symptom", ""),
                root_cause=record.get("root_cause", ""),
                fix=record.get("fix", ""),
                reasons=reasons,
                score=score,
            )
        )
    ranked.sort(key=lambda item: (item.score, item.date), reverse=True)
    return ranked[:limit]


def blast_radius(edges: tuple[Edge, ...], service: str) -> tuple[list[Touch], list[Touch]]:
    """Who calls this service, and what this service calls."""
    if not service:
        return [], []
    callers = [Touch(service=edge.caller, why=edge.why) for edge in edges if edge.callee == service]
    needs = [Touch(service=edge.callee, why=edge.why) for edge in edges if edge.caller == service]
    return callers, needs


def _confidence(link: LinkResult) -> str:
    if link.host and link.symptom:
        return "strong"
    if link.host or link.service or link.symptom or link.ambiguous_services:
        return "partial"
    return "weak"


def _evidence(hits: list[Hit]) -> list[Evidence]:
    items: list[Evidence] = []
    for hit in hits:
        source = str(hit.metadata.get("source_type") or "")
        items.append(
            Evidence(
                chunk_id=hit.chunk_id,
                source_type=source,
                distance=round(float(hit.distance), 3),
                text=hit.text.strip(),
            )
        )
    return items


def live_retrieve(query: str, filters: dict[str, str]) -> tuple[list[Hit], str]:
    """Search the local index when it exists. A missing index is not an error."""
    from src.config import get_settings
    from src.ingest import open_collection
    from src.retrieve import retrieve

    cfg = get_settings()
    if not cfg.chroma_path.exists():
        return [], "missing"
    try:
        collection = open_collection(cfg.chroma_path, cfg.collection_name)
        if collection.count() == 0:
            return [], "empty"
        result = retrieve(query, filters, cfg.retrieval_k, collection=collection)
        return result.hits, "ok"
    except Exception:
        logger.exception("retrieval failed")
        return [], "error"


def _filters(link: LinkResult) -> dict[str, str]:
    filters: dict[str, str] = {}
    if link.service:
        filters["service"] = link.service
    if link.environment:
        filters["environment"] = link.environment
    if link.host:
        filters["host"] = link.host
    if link.symptom:
        filters["failure_symptom"] = link.symptom
    return filters


def _has_model_key() -> bool:
    from src.config import get_settings

    cfg = get_settings()
    if cfg.llm_provider == "openai":
        return bool(cfg.openai_api_key)
    if cfg.llm_provider == "anthropic":
        return bool(cfg.anthropic_api_key)
    return False


def _default_narrative(question: str, hits: list[Hit]) -> str:
    if not hits or not _has_model_key():
        return ""
    from src.answer import generate_answer
    from src.llm import LLMError

    try:
        return generate_answer(question, hits)
    except LLMError:
        logger.exception("narrative failed")
        return ""


def build_card(
    text: str,
    *,
    data_dir: Path | None = None,
    catalog: Catalog | None = None,
    retrieve_fn: Callable[[str, dict[str, str]], list[Hit]] | None = None,
    answer_fn: Callable[[str, list[Hit]], str] | None = None,
) -> Card:
    """Build a desk card from files, then attach retrieval when an index is present."""
    if data_dir is None or catalog is None:
        from src.config import get_settings

        data_dir = data_dir or get_settings().data_dir
    active = catalog or load_catalog(data_dir)
    link = link_text(text, active)
    book = choose_runbook(
        load_runbooks(data_dir),
        service=link.service,
        symptom=link.symptom,
        host=link.host,
        environment=link.environment,
    )
    similar = rank_incidents(
        load_incidents(data_dir),
        host=link.host,
        service=link.service,
        environment=link.environment,
        symptom=link.symptom,
    )
    callers, needs = blast_radius(active.edges, link.service)
    filters = _filters(link)
    index_status = "ok"
    if retrieve_fn is None:
        hits, index_status = live_retrieve(text, filters)
    else:
        hits = list(retrieve_fn(text, filters))
    narrative = ""
    if answer_fn is not None:
        narrative = answer_fn(text, hits) or ""
    elif retrieve_fn is None:
        narrative = _default_narrative(text, hits)
    confidence = _confidence(link)
    return Card(
        text=text.strip(),
        host=link.host,
        service=link.service,
        environment=link.environment,
        region=link.region,
        symptom=link.symptom,
        owner=link.owner,
        oncall=link.oncall,
        confidence=confidence,
        confidence_note=CONFIDENCE_NOTES[confidence],
        warning=link.warning,
        ambiguous_services=list(link.ambiguous_services),
        runbook=book.stem if book else "",
        likely_cause=book.likely_cause if book else "",
        checklist=list(book.steps) if book else [],
        similar=similar,
        callers=callers,
        needs=needs,
        evidence=_evidence(hits),
        index_status=index_status,
        narrative=narrative,
    )


def format_card(card: Card) -> str:
    """Plain-text card for the terminal."""
    title_bits = [bit for bit in (card.host or card.service or "unlinked", card.service if card.host else "", card.environment, card.region) if bit]
    lines = ["  ·  ".join(title_bits)]
    if card.symptom:
        lines.append(card.symptom)
    if card.owner or card.oncall:
        lines.append(f"Owner: {card.owner or 'unknown'}")
        lines.append(f"On-call: {card.oncall or 'unknown'}")
    lines.append(f"Confidence: {card.confidence}")
    if card.warning:
        lines.append(f"Note: {card.warning}")
    lines.append("")
    if card.likely_cause:
        lines.append(f"From the runbook ({card.runbook}):")
        lines.append(card.likely_cause)
        lines.append("")
    else:
        lines.append("No runbook matched.")
        lines.append("")
    if card.checklist:
        lines.append("Checklist:")
        for index, step in enumerate(card.checklist, start=1):
            lines.append(f"{index}. {step}")
        lines.append("")
    if card.similar:
        lines.append("Last time this failed:")
        for item in card.similar:
            why = ", ".join(item.reasons)
            lines.append(
                f"{item.incident_id}  {item.date}  {item.host}  {item.environment}  ({why})"
            )
            lines.append(f"Fix: {item.fix}")
        lines.append("")
    if card.callers or card.needs:
        lines.append("What else this touches:")
        for touch in card.callers:
            lines.append(f"Called by {touch.service} — {touch.why}")
        for touch in card.needs:
            lines.append(f"Calls {touch.service} — {touch.why}")
        lines.append("")
    if card.narrative:
        lines.append("Model note:")
        lines.append(card.narrative)
        lines.append("")
    if card.evidence:
        lines.append("Evidence:")
        for item in card.evidence:
            lines.append(f"[{item.chunk_id}] distance={item.distance:.3f}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    """Print a desk card for one page."""
    parser = argparse.ArgumentParser(description="Triage one infrastructure page.")
    parser.add_argument("text", help="Alert or question to triage")
    args = parser.parse_args(argv)
    print(format_card(build_card(args.text)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
