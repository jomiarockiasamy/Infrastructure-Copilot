"""Match a pasted page to hosts, services, environments, and symptoms.

The match is lexical against the catalog. It does not call a model, so a page
still produces filters when no API key is set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.catalog import (
    ENV_ALIASES,
    SERVICE_ALIASES,
    SYMPTOM_ALIASES,
    Catalog,
)

_TOKEN = re.compile(r"(?<![a-z0-9]){phrase}(?![a-z0-9])")


@dataclass
class LinkResult:
    """Structured fields pulled out of one page, plus any conflict worth showing."""

    host: str = ""
    service: str = ""
    environment: str = ""
    region: str = ""
    symptom: str = ""
    owner: str = ""
    oncall: str = ""
    warning: str = ""
    ambiguous_services: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)


def _spans(text: str, phrases: list[str]) -> list[tuple[int, int, str]]:
    """Leftmost non-overlapping matches. Longer phrases win when they start together."""
    lowered = text.lower()
    found: list[tuple[int, int, str]] = []
    for phrase in sorted({item.lower() for item in phrases if item}, key=len, reverse=True):
        pattern = re.compile(_TOKEN.pattern.format(phrase=re.escape(phrase)))
        for match in pattern.finditer(lowered):
            found.append((match.start(), match.end(), phrase))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    chosen: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for start, end, phrase in found:
        if any(start < right and end > left for left, right in occupied):
            continue
        chosen.append((start, end, phrase))
        occupied.append((start, end))
    chosen.sort()
    return chosen


def _overlaps(start: int, end: int, spans: list[tuple[int, int, str]]) -> bool:
    return any(start < right and end > left for left, right, _phrase in spans)


def link_text(text: str, catalog: Catalog) -> LinkResult:
    """Fill host, service, environment, and symptom from a page of alert text."""
    raw = text or ""
    host_spans = _spans(raw, list(catalog.hosts))
    env_spans = _spans(raw, list(ENV_ALIASES))
    symptom_spans = _spans(raw, list(SYMPTOM_ALIASES))
    service_phrases = list(SERVICE_ALIASES) + list(catalog.services)
    service_spans = [
        span
        for span in _spans(raw, service_phrases)
        if not _overlaps(span[0], span[1], host_spans)
    ]
    people = [record.owner for record in catalog.services.values()]
    people.extend(record.oncall for record in catalog.services.values())
    person_spans = _spans(raw, people)

    result = LinkResult()
    warnings: list[str] = []

    if host_spans:
        record = catalog.hosts[_canonical_host(host_spans[0][2], catalog)]
        result.host = record.host
        result.service = record.service
        result.environment = record.environment
        result.region = record.region
        result.matched.append(f"host {record.host}")
        if len(host_spans) > 1:
            others = ", ".join(
                _canonical_host(phrase, catalog) for _start, _end, phrase in host_spans[1:]
            )
            warnings.append(f"Also mentioned {others}. The desk followed {record.host}.")

    mentioned_services: list[str] = []
    for _start, _end, phrase in service_spans:
        canonical = SERVICE_ALIASES.get(phrase, "")
        if not canonical and phrase in catalog.services:
            canonical = phrase
        if canonical and canonical not in mentioned_services:
            mentioned_services.append(canonical)
    extras = [name for name in mentioned_services if name != result.service]
    if not result.service and mentioned_services:
        result.service = mentioned_services[0]
        extras = mentioned_services[1:]
        result.matched.append(f"service {result.service}")
    elif result.service:
        result.matched.append(f"service {result.service}")
    if extras:
        warnings.append(
            "Also mentions " + ", ".join(extras) + f". The desk followed {result.service or extras[0]}."
        )

    stated_env = ""
    if env_spans:
        stated_env = ENV_ALIASES[env_spans[0][2]]
    if result.host and stated_env and stated_env != result.environment:
        warnings.append(
            f"The page says {stated_env}, but {result.host} is {result.environment} in inventory. "
            f"The desk is using {result.environment}."
        )
    elif not result.host and stated_env:
        result.environment = stated_env
        result.matched.append(f"environment {stated_env}")
    elif result.environment:
        result.matched.append(f"environment {result.environment}")

    if symptom_spans:
        result.symptom = SYMPTOM_ALIASES[symptom_spans[0][2]]
        result.matched.append(f"symptom {result.symptom}")
        other_symptoms = []
        for _start, _end, phrase in symptom_spans[1:]:
            canonical = SYMPTOM_ALIASES[phrase]
            if canonical != result.symptom and canonical not in other_symptoms:
                other_symptoms.append(canonical)
        if other_symptoms:
            warnings.append(
                "Also looks like " + " and ".join(other_symptoms) + f". The desk followed {result.symptom}."
            )

    if not result.service and person_spans:
        label = _canonical_person(person_spans[0][2], catalog)
        candidates = catalog.service_named(label)
        if result.symptom and len(candidates) > 1:
            covered = catalog.symptom_services.get(result.symptom, frozenset())
            narrowed = [name for name in candidates if name in covered]
            if len(narrowed) == 1:
                candidates = narrowed
        if len(candidates) == 1:
            result.service = candidates[0]
            result.matched.append(f"service {result.service}")
        elif len(candidates) > 1:
            result.ambiguous_services = candidates
            warnings.append(
                f"{label} covers {' and '.join(candidates)}. The page does not say which one."
            )

    if result.service and result.service in catalog.services:
        record = catalog.services[result.service]
        result.owner = record.owner
        result.oncall = record.oncall

    result.warning = " ".join(warnings)
    return result


def _canonical_host(phrase: str, catalog: Catalog) -> str:
    for host in catalog.hosts:
        if host.lower() == phrase:
            return host
    return phrase


def _canonical_person(phrase: str, catalog: Catalog) -> str:
    for record in catalog.services.values():
        if record.owner.lower() == phrase:
            return record.owner
        if record.oncall.lower() == phrase:
            return record.oncall
    return phrase
