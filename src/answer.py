"""Grounded answers. Recommendations must cite retrieved chunk ids."""

from __future__ import annotations

import re
from collections.abc import Callable

from src.llm import complete
from src.retrieve import Hit

REFUSAL = (
    "I don't have enough information in the runbooks or incident history to answer this"
)

_CITE = re.compile(r"\[([^\[\]]+)\]")


def citations_in(line: str) -> list[str]:
    """Return bracketed citation ids from one line."""
    return [match.strip() for match in _CITE.findall(line) if match.strip()]


def line_is_grounded(line: str, valid_ids: set[str]) -> bool:
    """True when every citation on the line is in the retrieved set, and there is one."""
    found = citations_in(line)
    return bool(found) and all(cite in valid_ids for cite in found)


def _clean_step(line: str) -> str:
    return re.sub(r"^(?:[-*]|\d+[.)])\s*", "", line).strip()


def validate_answer(text: str, valid_ids: set[str]) -> str:
    """Drop steps that lack a real citation, and rebuild the Sources line."""
    body = re.split(r"\n\s*Sources\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0]
    likely: list[str] = []
    steps: list[str] = []
    mode: str | None = None
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"likely cause\s*:", line, re.IGNORECASE):
            mode = "likely"
            payload = re.sub(r"(?i)^likely cause\s*:\s*", "", line).strip()
            if line_is_grounded(payload, valid_ids):
                likely.append(payload)
            continue
        if re.match(r"steps to try\s*:?\s*$", line, re.IGNORECASE):
            mode = "steps"
            continue
        if mode == "likely" and line_is_grounded(line, valid_ids):
            likely.append(line)
            continue
        if mode == "steps" and line_is_grounded(line, valid_ids):
            steps.append(_clean_step(line))
    used: list[str] = []
    for line in likely + steps:
        for cite in citations_in(line):
            if cite not in used:
                used.append(cite)
    if not used:
        return REFUSAL
    likely_text = " ".join(likely) if likely else "Not stated in the retrieved chunks."
    if steps:
        step_block = "\n".join(f"- {step}" for step in steps)
    else:
        step_block = "- None."
    sources = ", ".join(f"[{cite}]" for cite in used)
    return (
        f"Likely cause: {likely_text}\n"
        f"Steps to try:\n{step_block}\n"
        f"Sources: {sources}"
    )


def _prompt(question: str, hits: list[Hit]) -> str:
    blocks = []
    for hit in hits:
        blocks.append(f"[{hit.chunk_id}]\n{hit.text}")
    joined = "\n\n".join(blocks)
    return f"""You are an infrastructure troubleshooting assistant.
Use ONLY the retrieved chunks below. Do not use outside knowledge.
If the chunks do not support a claim, leave it out.
Every sentence in Likely cause and every step must cite one or more chunk ids in brackets, copied exactly, such as [runbook:disk-full#2].

Format:
Likely cause: ...
Steps to try:
- ...
Sources: ...

Question: {question}

Retrieved chunks:
{joined}
"""


def generate_answer(
    question: str,
    hits: list[Hit],
    *,
    complete_fn: Callable[[str], str] | None = None,
    weak_distance_threshold: float | None = None,
) -> str:
    """Answer from retrieved chunks only. Refuse when the best hit is too distant."""
    threshold = (
        get_threshold()
        if weak_distance_threshold is None
        else weak_distance_threshold
    )
    if not hits or min(hit.distance for hit in hits) > threshold:
        return REFUSAL
    caller = complete_fn or (lambda prompt: complete(prompt, max_tokens=800))
    raw = caller(_prompt(question, hits))
    return validate_answer(raw, {hit.chunk_id for hit in hits})


def get_threshold() -> float:
    """Read the weak-distance threshold from settings."""
    from src.config import get_settings

    return get_settings().weak_distance_threshold
