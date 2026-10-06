"""Deterministic embeddings so tests never download a model."""

from __future__ import annotations

import hashlib
import math

from chromadb.api.types import Documents, EmbeddingFunction
from chromadb.utils.embedding_functions import register_embedding_function

from src.ingest import normalize_text


@register_embedding_function
class FakeEmbedder(EmbeddingFunction[Documents]):
    """Maps FAMILY_A texts to one vector and everything else to a hashed vector."""

    def __init__(self) -> None:
        pass

    def __call__(self, input):
        return [self._vector(text) for text in input]

    def embed_documents(self, input):
        return self.__call__(input)

    def embed_query(self, input):
        if isinstance(input, str):
            return self._vector(input)
        return self.__call__(input)

    @staticmethod
    def name() -> str:
        return "fake_infra"

    def default_space(self) -> str:
        return "cosine"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config):
        return FakeEmbedder()

    def _vector(self, text: str) -> list[float]:
        if "FAMILY_A" in text:
            return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        raw = hashlib.sha256(normalize_text(text).encode()).digest()
        vec = [byte / 255.0 for byte in raw[:16]]
        vec[0] = 0.0
        norm = math.sqrt(sum(value * value for value in vec)) or 1.0
        return [value / norm for value in vec]
