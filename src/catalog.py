"""Inventory, ownership, symptom aliases, and who calls whom."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

# Phrases an alert actually uses. Longer phrases are matched before shorter ones.
SERVICE_ALIASES: dict[str, str] = {
    "payments database": "payments-db",
    "payments db": "payments-db",
    "card charge datastore": "payments-db",
    "card charges": "payments-db",
    "storefront api": "checkout-api",
    "storefront": "checkout-api",
    "checkout": "checkout-api",
    "auth service": "auth-service",
    "login": "auth-service",
    "dns resolver": "dns-resolver",
    "resolver": "dns-resolver",
    "dns": "dns-resolver",
    "public proxy": "edge-proxy",
    "load balancer": "edge-proxy",
    "edge proxy": "edge-proxy",
    "edge": "edge-proxy",
    "stream cluster": "kafka",
    "cache node": "redis",
    "async job pod": "worker",
    "invoice api": "billing-api",
    "billing": "billing-api",
    "notify": "notifications",
    "search api": "search-api",
    "search": "search-api",
}

SYMPTOM_ALIASES: dict[str, str] = {
    "connection pool exhausted": "connection pool exhausted",
    "pool exhausted": "connection pool exhausted",
    "refusing new db sessions": "connection pool exhausted",
    "connection pool": "connection pool exhausted",
    "no space left on device": "disk full",
    "no space left": "disk full",
    "out of disk space": "disk full",
    "out of disk": "disk full",
    "disk space": "disk full",
    "volume filled": "disk full",
    "disk full": "disk full",
    "certificate mismatch": "certificate mismatch",
    "cert name is wrong": "certificate mismatch",
    "certificate date is past": "expired tls",
    "expired certificate": "expired tls",
    "expired tls": "expired tls",
    "consumer lag": "consumer lag",
    "behind on the topic": "consumer lag",
    "cache eviction": "cache eviction",
    "evicting keys": "cache eviction",
    "dropping keys": "cache eviction",
    "network latency": "network latency",
    "memory leak": "memory leak",
    "leaking memory": "memory leak",
    "upstream 5xx": "upstream 5xx",
    "server errors": "upstream 5xx",
    "dns failure": "dns failure",
    "nxdomain": "dns failure",
    "can't resolve": "dns failure",
    "cannot resolve": "dns failure",
    "crashloop": "crashloop",
    "keeps restarting": "crashloop",
    "high cpu": "high cpu",
    "pegged cpu": "high cpu",
    "burning a core": "high cpu",
    "pegged": "high cpu",
}

ENV_ALIASES: dict[str, str] = {
    "production": "prod",
    "prod": "prod",
    "staging": "staging",
    "stage": "staging",
    "development": "dev",
    "dev": "dev",
}


@dataclass(frozen=True)
class HostRecord:
    """One inventory row."""

    host: str
    service: str
    environment: str
    region: str


@dataclass(frozen=True)
class ServiceRecord:
    """Owner and on-call for one service."""

    service: str
    owner: str
    oncall: str


@dataclass(frozen=True)
class Edge:
    """A caller that breaks, or degrades, when callee is unhealthy."""

    caller: str
    callee: str
    why: str


@dataclass(frozen=True)
class Catalog:
    """Everything the linker is allowed to name. Values come from the data files."""

    hosts: dict[str, HostRecord]
    services: dict[str, ServiceRecord]
    symptom_services: dict[str, frozenset[str]]
    edges: tuple[Edge, ...]

    def service_named(self, label: str) -> list[str]:
        """Services whose owner team or on-call person is this label."""
        key = label.strip().lower()
        if not key:
            return []
        found: list[str] = []
        for record in self.services.values():
            if record.owner.lower() == key or record.oncall.lower() == key:
                found.append(record.service)
        return found


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _symptom_services(runbook_dir: Path) -> dict[str, frozenset[str]]:
    grouped: dict[str, set[str]] = {}
    if not runbook_dir.is_dir():
        return {}
    for path in sorted(runbook_dir.glob("*.md")):
        text = path.read_text()
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        meta: dict[str, str] = {}
        for line in parts[1].splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
        symptom = meta.get("failure_symptom", "")
        service = meta.get("service", "")
        if symptom and service:
            grouped.setdefault(symptom, set()).add(service)
    return {symptom: frozenset(services) for symptom, services in grouped.items()}


def load_catalog(data_dir: Path | None = None) -> Catalog:
    """Read inventory, ownership, runbook symptoms, and dependencies."""
    if data_dir is None:
        from src.config import get_settings

        data_dir = get_settings().data_dir
    hosts: dict[str, HostRecord] = {}
    for row in _read_csv(data_dir / "inventory.csv"):
        host = row["host"].strip()
        hosts[host] = HostRecord(
            host=host,
            service=row["service"].strip(),
            environment=row["environment"].strip(),
            region=row["region"].strip(),
        )
    services: dict[str, ServiceRecord] = {}
    for row in _read_csv(data_dir / "ownership.csv"):
        service = row["service"].strip()
        services[service] = ServiceRecord(
            service=service,
            owner=row["owner"].strip(),
            oncall=row["oncall"].strip(),
        )
    edges: list[Edge] = []
    dep_path = data_dir / "dependencies.csv"
    if dep_path.exists():
        for row in _read_csv(dep_path):
            caller = row["caller"].strip()
            callee = row["callee"].strip()
            if caller in services and callee in services:
                edges.append(Edge(caller=caller, callee=callee, why=row["why"].strip()))
    return Catalog(
        hosts=hosts,
        services=services,
        symptom_services=_symptom_services(data_dir / "runbooks"),
        edges=tuple(edges),
    )


def load_incidents(data_dir: Path | None = None) -> list[dict[str, str]]:
    """Return incident records as plain dicts of strings."""
    if data_dir is None:
        from src.config import get_settings

        data_dir = get_settings().data_dir
    records = json.loads((data_dir / "incidents.json").read_text())
    cleaned: list[dict[str, str]] = []
    for record in records:
        cleaned.append({key: str(record[key]) for key in record})
    return cleaned
