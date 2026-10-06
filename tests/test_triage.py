"""Desk cards from runbooks and incident history, with retrieval injected."""

from src.retrieve import Hit
from src.triage import build_card, choose_runbook, format_card, load_runbooks, split_steps
from src.config import get_settings


def _card(text, hits=None, narrative=""):
    def retrieve(_query, _filters):
        return hits or []

    def answer(_query, _hits):
        return narrative

    return build_card(text, retrieve_fn=retrieve, answer_fn=answer)


def test_disk_full_card_uses_the_runbook_and_the_last_fix():
    card = _card("payments-db-01 in prod is out of disk space")
    assert card.confidence == "strong"
    assert card.runbook == "disk-full"
    assert card.checklist[0].startswith("Confirm the mount with df -h")
    assert len(card.checklist) == 7
    assert card.similar[0].incident_id == "inc-001"
    assert "same host" in card.similar[0].reasons
    assert all(item.symptom == "disk full" for item in card.similar)
    assert "WAL" in card.similar[0].fix
    callers = {touch.service for touch in card.callers}
    assert callers == {"checkout-api", "billing-api"}
    assert card.needs == []
    assert "No runbook" not in format_card(card)
    assert "inc-001" in format_card(card)


def test_duplicate_steps_section_is_not_repeated():
    card = _card("checkout-api-01 is pegged at high cpu")
    assert card.runbook == "high-cpu"
    assert len(card.checklist) == 5
    assert any("immediately" in step for step in card.checklist)
    assert all("promptly" not in step for step in card.checklist)


def test_weak_page_does_not_invent_a_runbook():
    card = _card("hello is anyone there")
    assert card.confidence == "weak"
    assert card.runbook == ""
    assert card.checklist == []
    assert card.similar == []


def test_host_alone_does_not_guess_between_runbooks():
    data_dir = get_settings().data_dir
    book = choose_runbook(
        load_runbooks(data_dir),
        service="payments-db",
        symptom="",
        host="payments-db-01",
        environment="prod",
    )
    assert book is None


def test_evidence_and_narrative_are_attached_when_provided():
    hit = Hit(
        chunk_id="runbook:disk-full#1",
        text="WAL files filled the volume.",
        metadata={"source_type": "runbook"},
        distance=0.3354,
    )
    card = _card(
        "payments-db-01 disk full",
        hits=[hit],
        narrative="Likely cause: the volume filled [runbook:disk-full#1]",
    )
    assert card.evidence[0].chunk_id == "runbook:disk-full#1"
    assert card.evidence[0].distance == 0.335
    assert "volume filled" in card.narrative
    payload = card.to_dict()
    assert [signal["value"] for signal in payload["signals"] if signal["name"] == "host"] == [
        "payments-db-01"
    ]


def test_split_steps_keeps_sentences():
    steps = split_steps("Stop the job. Then retry the write. Leave pg_wal alone.")
    assert steps == [
        "Stop the job.",
        "Then retry the write.",
        "Leave pg_wal alone.",
    ]
