"""Citation checks and the weak-retrieval refusal."""

from src.answer import REFUSAL, generate_answer, validate_answer
from src.retrieve import Hit


def _hit(chunk_id: str, distance: float = 0.2) -> Hit:
    return Hit(chunk_id=chunk_id, text="stored text", metadata={}, distance=distance)


def test_validator_drops_fake_chunk_ids():
    raw = """Likely cause: the volume is full [runbook:disk-full#0]
Steps to try:
1. Delete expired WAL archives [runbook:disk-full#2]
2. Restart the moon base [fake:chunk]
Sources: [fake:chunk], [runbook:disk-full#0]
"""
    valid = {"runbook:disk-full#0", "runbook:disk-full#2"}
    cleaned = validate_answer(raw, valid)
    assert "Delete expired WAL archives" in cleaned
    assert "[runbook:disk-full#2]" in cleaned
    assert "[runbook:disk-full#0]" in cleaned
    assert "fake:chunk" not in cleaned
    assert "moon" not in cleaned
    assert cleaned.startswith("Likely cause:")
    assert "Steps to try:" in cleaned
    assert "Sources:" in cleaned


def test_uncited_step_is_dropped():
    raw = """Likely cause: pool exhausted [incident:inc-003]
Steps to try:
- Restart the pool [incident:inc-003]
- Hope it fixes itself
"""
    cleaned = validate_answer(raw, {"incident:inc-003"})
    assert "Restart the pool" in cleaned
    assert "Hope it fixes itself" not in cleaned


def test_weak_retrieval_does_not_call_the_model():
    def fail(_prompt: str) -> str:
        raise AssertionError("LLM should not be called")

    answer = generate_answer(
        "why is the disk full?",
        [_hit("runbook:disk-full#0", distance=0.8)],
        complete_fn=fail,
        weak_distance_threshold=0.55,
    )
    assert answer == REFUSAL


def test_generate_answer_uses_only_the_mock():
    def fake_model(_prompt: str) -> str:
        return (
            "Likely cause: WAL filled the disk [runbook:disk-full#1]\n"
            "Steps to try:\n"
            "- Delete old archives [runbook:disk-full#2]\n"
            "- Reboot the laptop [not-a-real-id]\n"
        )

    answer = generate_answer(
        "disk full",
        [_hit("runbook:disk-full#1"), _hit("runbook:disk-full#2")],
        complete_fn=fake_model,
        weak_distance_threshold=0.55,
    )
    assert "[runbook:disk-full#1]" in answer
    assert "[runbook:disk-full#2]" in answer
    assert "not-a-real-id" not in answer
    assert "laptop" not in answer
