from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class ClusterReview:
    review_id: str
    body: str
    rating: int


@dataclass(frozen=True)
class ClusterRecord:
    id: str
    run_id: str
    review_ids: list[str]
    keyphrases: list[str]
    medoid_review_id: str


@dataclass(frozen=True)
class ClusterOutput:
    clusters: list[ClusterRecord]
    labels: NDArray[np.int_]
    embeddings: dict[str, list[float]]
