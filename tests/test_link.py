"""Lexical linker against the inventory catalog."""

from src.catalog import load_catalog
from src.link import link_text


def _catalog():
    return load_catalog()


def test_host_symptom_and_environment_come_from_the_page():
    link = link_text("why is payments-db-01 in prod out of disk space?", _catalog())
    assert link.host == "payments-db-01"
    assert link.service == "payments-db"
    assert link.environment == "prod"
    assert link.region == "us-east-1"
    assert link.symptom == "disk full"
    assert link.owner == "Payments Platform"
    assert link.oncall == "Avery Chen"
    assert link.warning == ""


def test_aliases_match_without_a_host_name():
    link = link_text("the payments database has no space left on device", _catalog())
    assert link.host == ""
    assert link.service == "payments-db"
    assert link.symptom == "disk full"
    assert link.oncall == "Avery Chen"


def test_inventory_environment_wins_when_the_page_disagrees():
    link = link_text("payments-db-01 staging is disk full", _catalog())
    assert link.host == "payments-db-01"
    assert link.environment == "prod"
    assert "staging" in link.warning
    assert "prod" in link.warning


def test_oncall_plus_symptom_picks_one_service():
    link = link_text("Devon Patel paged for NXDOMAIN", _catalog())
    assert link.service == "dns-resolver"
    assert link.symptom == "dns failure"
    assert link.ambiguous_services == []
    assert link.owner == "Edge Networking"


def test_shared_oncall_stays_ambiguous_without_a_symptom():
    link = link_text("Devon Patel is paged", _catalog())
    assert link.service == ""
    assert link.ambiguous_services == ["dns-resolver", "edge-proxy"]
    assert "which one" in link.warning


def test_unrelated_text_matches_nothing():
    link = link_text("hello is anyone there", _catalog())
    assert link.host == ""
    assert link.service == ""
    assert link.symptom == ""
    assert link.warning == ""
