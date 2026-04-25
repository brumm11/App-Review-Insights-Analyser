from __future__ import annotations

from hashlib import sha1

import hdbscan
import numpy as np
import umap
from numpy.typing import NDArray
from sklearn.metrics.pairwise import cosine_distances

from agent.cluster_settings import ClusterSettings
from agent.clustering.embeddings import (
    EmbeddingCache,
    LocalBGEProvider,
    LocalHashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    embed_with_cache,
)
from agent.clustering.models import ClusterOutput, ClusterRecord, ClusterReview


class ClusteringService:
    def __init__(self, settings: ClusterSettings) -> None:
        self.settings = settings

    def cluster(
        self,
        run_id: str,
        reviews: list[ClusterReview],
    ) -> tuple[ClusterOutput, dict[str, int]]:
        filtered = [r for r in reviews if len(r.body) >= self.settings.min_chars]
        if not filtered:
            return ClusterOutput(clusters=[], labels=np.array([], dtype=int), embeddings={}), {
                "input_reviews": 0,
                "embedded_reviews": 0,
                "cache_hits": 0,
            }

        provider = self._build_provider()
        cache = EmbeddingCache(self.settings.cache_path)
        texts = [r.body for r in filtered]
        vectors, cache_hits = embed_with_cache(texts=texts, provider=provider, cache=cache)

        reduced = self._reduce_vectors(vectors)
        labels = self._cluster_vectors(reduced)

        clusters: list[ClusterRecord] = []
        embedding_map = {
            item.review_id: vectors[idx].astype(float).tolist()
            for idx, item in enumerate(filtered)
        }
        for cluster_id in sorted({int(x) for x in labels if int(x) >= 0}):
            idxs = [i for i, value in enumerate(labels) if int(value) == cluster_id]
            if not idxs:
                continue

            subset = vectors[idxs]
            local_reviews = [filtered[i] for i in idxs]
            medoid_local = self._medoid_index(subset)
            medoid_review = local_reviews[medoid_local]
            keyphrases = self._extract_keyphrases(
                [x.body for x in local_reviews],
                self.settings.keyphrase_top_n,
            )
            cluster_hash = sha1(f"{run_id}:{cluster_id}".encode()).hexdigest()
            clusters.append(
                ClusterRecord(
                    id=cluster_hash,
                    run_id=run_id,
                    review_ids=[r.review_id for r in local_reviews],
                    keyphrases=keyphrases,
                    medoid_review_id=medoid_review.review_id,
                )
            )

        return ClusterOutput(clusters=clusters, labels=labels, embeddings=embedding_map), {
            "input_reviews": len(reviews),
            "embedded_reviews": len(filtered),
            "cache_hits": cache_hits,
        }

    def _build_provider(
        self,
    ) -> LocalHashEmbeddingProvider | LocalBGEProvider | OpenAIEmbeddingProvider:
        provider = self.settings.embedding_provider.lower()
        if provider == "openai":
            return OpenAIEmbeddingProvider(
                model_name=self.settings.embedding_model_openai,
                dimensions=self.settings.embedding_dimensions,
            )
        if provider == "local_bge":
            return LocalBGEProvider(model_name=self.settings.embedding_model_local)
        if provider == "local_hash":
            return LocalHashEmbeddingProvider(dimensions=self.settings.embedding_dimensions)
        return LocalBGEProvider(model_name=self.settings.embedding_model_local)

    def _extract_keyphrases(self, docs: list[str], top_n: int) -> list[str]:
        joined = "\n".join(docs)
        if self.settings.use_keybert:
            from keybert import KeyBERT

            kw = KeyBERT()
            values = kw.extract_keywords(
                joined,
                keyphrase_ngram_range=(1, 3),
                stop_words="english",
                top_n=top_n,
            )
            return [item[0] for item in values]
        tokens = [word.lower() for word in joined.split() if word.isalpha() and len(word) > 3]
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:top_n]
        return [token for token, _ in ranked]

    @staticmethod
    def _medoid_index(vectors: NDArray[np.float32]) -> int:
        distances = cosine_distances(vectors)
        sums = distances.sum(axis=1)
        return int(np.argmin(sums))

    def _reduce_vectors(self, vectors: NDArray[np.float32]) -> NDArray[np.float32]:
        if len(vectors) <= max(4, self.settings.umap_n_components + 1):
            return vectors
        reduced = umap.UMAP(
            n_components=self.settings.umap_n_components,
            metric="cosine",
            random_state=42,
            transform_seed=42,
        ).fit_transform(vectors)
        return np.asarray(reduced, dtype=np.float32)

    def _cluster_vectors(self, vectors: NDArray[np.float32]) -> NDArray[np.int_]:
        if len(vectors) < self.settings.hdbscan_min_cluster_size:
            return np.array([0 for _ in range(len(vectors))], dtype=int)
        labels = hdbscan.HDBSCAN(
            min_cluster_size=self.settings.hdbscan_min_cluster_size,
            metric="euclidean",
            prediction_data=False,
        ).fit_predict(vectors)
        return np.asarray(labels, dtype=int)
