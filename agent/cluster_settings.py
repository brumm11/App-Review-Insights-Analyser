from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.config import Settings


@dataclass(frozen=True)
class ClusterSettings:
    language: str
    min_chars: int
    embedding_provider: str
    embedding_model_local: str
    embedding_model_openai: str
    embedding_dimensions: int
    cache_path: Path
    umap_n_components: int
    hdbscan_min_cluster_size: int
    keyphrase_top_n: int
    use_keybert: bool


def from_settings(settings: Settings) -> ClusterSettings:
    return ClusterSettings(
        language=settings.cluster_language,
        min_chars=settings.cluster_min_chars,
        embedding_provider=settings.embedding_provider,
        embedding_model_local=settings.embedding_model_local,
        embedding_model_openai=settings.embedding_model_openai,
        embedding_dimensions=settings.embedding_dimensions,
        cache_path=settings.embedding_cache_path,
        umap_n_components=settings.umap_n_components,
        hdbscan_min_cluster_size=settings.hdbscan_min_cluster_size,
        keyphrase_top_n=settings.keyphrase_top_n,
        use_keybert=settings.use_keybert,
    )
