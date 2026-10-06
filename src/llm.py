"""Thin client for the configured OpenAI or Anthropic chat model."""

from __future__ import annotations

from src.config import Settings, get_settings


class LLMError(RuntimeError):
    """The LLM could not be called."""


def complete(
    prompt: str,
    *,
    max_tokens: int = 800,
    settings: Settings | None = None,
) -> str:
    """Send one user prompt and return the model text."""
    cfg = settings or get_settings()
    if cfg.llm_provider == "openai":
        return _openai(prompt, max_tokens, cfg)
    if cfg.llm_provider == "anthropic":
        return _anthropic(prompt, max_tokens, cfg)
    raise LLMError(
        f"Unknown LLM_PROVIDER '{cfg.llm_provider}'. Use openai or anthropic."
    )


def _openai(prompt: str, max_tokens: int, cfg: Settings) -> str:
    if not cfg.openai_api_key:
        raise LLMError("OPENAI_API_KEY is not set.")
    from openai import OpenAI

    client = OpenAI(api_key=cfg.openai_api_key)
    response = client.chat.completions.create(
        model=cfg.openai_model,
        temperature=0,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def _anthropic(prompt: str, max_tokens: int, cfg: Settings) -> str:
    if not cfg.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set.")
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    message = client.messages.create(
        model=cfg.anthropic_model,
        temperature=0,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    parts: list[str] = []
    for block in message.content:
        text = getattr(block, "text", "")
        if text:
            parts.append(text)
    return "".join(parts)
