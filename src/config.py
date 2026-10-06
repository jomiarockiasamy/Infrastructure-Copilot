"""Runtime settings loaded from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    """Paths, thresholds, and LLM settings. API keys come only from the environment."""

    llm_provider: str
    openai_api_key: str
    anthropic_api_key: str
    openai_model: str
    anthropic_model: str
    chroma_path: Path
    collection_name: str
    dedup_similarity_threshold: float
    weak_distance_threshold: float
    cache_path: Path
    cache_ttl_seconds: int
    retrieval_k: int
    min_results_before_relax: int
    data_dir: Path


def get_settings() -> Settings:
    """Read settings from the environment, with defaults for local runs."""
    chroma_path = _env_path("CHROMA_PATH", ROOT / ".chroma")
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "openai").strip().lower(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest").strip(),
        chroma_path=chroma_path,
        collection_name=os.getenv("CHROMA_COLLECTION", "infra_chunks").strip(),
        dedup_similarity_threshold=_env_float("DEDUP_SIMILARITY_THRESHOLD", 0.95),
        weak_distance_threshold=_env_float("WEAK_DISTANCE_THRESHOLD", 0.55),
        cache_path=_env_path("CACHE_PATH", chroma_path / "retrieval_cache.sqlite"),
        cache_ttl_seconds=_env_int("CACHE_TTL_SECONDS", 3600),
        retrieval_k=_env_int("RETRIEVAL_K", 5),
        min_results_before_relax=_env_int("MIN_RESULTS_BEFORE_RELAX", 2),
        data_dir=ROOT / "data",
    )
