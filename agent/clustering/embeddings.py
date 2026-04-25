from __future__ import annotations

import json
import os
from hashlib import sha1
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        ...


class LocalHashEmbeddingProvider:
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        vectors = []
        for text in texts:
            seed = sha1(text.encode()).digest()
            raw = (seed * ((self.dimensions // len(seed)) + 1))[: self.dimensions]
            vector = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
            centered = (vector - 127.5) / 127.5
            norm = np.linalg.norm(centered)
            vectors.append(centered if norm == 0 else centered / norm)
        return np.array(vectors, dtype=np.float32)


class LocalBGEProvider:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model: Any = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        values = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.array(values, dtype=np.float32)


class OpenAIEmbeddingProvider:
    def __init__(self, model_name: str, dimensions: int) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self._model_name = model_name
        self._dimensions = dimensions

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        response = self._client.embeddings.create(
            model=self._model_name,
            input=texts,
            dimensions=self._dimensions,
        )
        vectors = [item.embedding for item in response.data]
        return np.array(vectors, dtype=np.float32)


class EmbeddingCache:
    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        if self.cache_path.exists():
            raw_text = self.cache_path.read_text(encoding="utf-8")
            self._cache: dict[str, list[float]] = json.loads(raw_text)
        else:
            self._cache = {}

    @staticmethod
    def key(text: str) -> str:
        return sha1(text.strip().encode()).hexdigest()

    def get(self, text: str) -> list[float] | None:
        return self._cache.get(self.key(text))

    def put(self, text: str, vector: NDArray[np.float32]) -> None:
        self._cache[self.key(text)] = vector.astype(float).tolist()

    def save(self) -> None:
        self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")


def embed_with_cache(
    texts: list[str],
    provider: EmbeddingProvider,
    cache: EmbeddingCache,
) -> tuple[NDArray[np.float32], int]:
    cached_vectors: list[NDArray[np.float32] | None] = [None] * len(texts)
    missing_indices: list[int] = []
    hits = 0
    for idx, text in enumerate(texts):
        hit = cache.get(text)
        if hit is None:
            missing_indices.append(idx)
        else:
            cached_vectors[idx] = np.array(hit, dtype=np.float32)
            hits += 1

    if missing_indices:
        generated = provider.embed([texts[i] for i in missing_indices])
        for position, idx in enumerate(missing_indices):
            vector = generated[position]
            cache.put(texts[idx], vector)
            cached_vectors[idx] = vector
        cache.save()

    vectors = np.vstack([v for v in cached_vectors if v is not None]).astype(np.float32)
    return vectors, hits
