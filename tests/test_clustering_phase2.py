from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from agent.cluster_settings import ClusterSettings
from agent.clustering.models import ClusterReview
from agent.clustering.service import ClusteringService
from agent.ingestion.models import RawReview
from agent.storage import (
    initialize_db,
    mark_run_status,
    replace_clusters_for_run,
    upsert_reviews,
)


def _seed_reviews(db_path: Path, run_id: str) -> None:
    mark_run_status(
        db_path,
        run_id=run_id,
        product_key="groww",
        iso_week="2026-W16",
        window_start="2026-04-13",
        window_end="2026-04-19",
        status="ingested",
    )
    base = datetime(2026, 4, 18, 10, 0, 0)
    rows: list[RawReview] = []
    for idx in range(16):
        positive = idx < 8
        body = (
            "App is smooth fast onboarding and easy investing"
            if positive
            else "App keeps crashing lagging and failing during payment"
        )
        rows.append(
            RawReview(
                id=f"r-{idx}",
                product_key="groww",
                source="playstore",
                external_id=f"e-{idx}",
                rating=5 if positive else 1,
                title=None,
                body=body,
                posted_at=base,
                version="1.0.0",
                language="en",
                country="in",
                raw_json="{}",
            )
        )
    upsert_reviews(db_path, rows)


def test_phase2_cluster_persists_clusters_and_embeddings(tmp_path: Path) -> None:
    db_path = tmp_path / "pulse.db"
    cache_path = tmp_path / "embeddings.json"
    initialize_db(db_path)
    run_id = "run-cluster-1"
    _seed_reviews(db_path, run_id)
    settings = ClusterSettings(
        language="en",
        min_chars=20,
        embedding_provider="local_hash",
        embedding_model_local="BAAI/bge-small-en-v1.5",
        embedding_model_openai="text-embedding-3-small",
        embedding_dimensions=64,
        cache_path=cache_path,
        umap_n_components=5,
        hdbscan_min_cluster_size=2,
        keyphrase_top_n=5,
        use_keybert=False,
    )

    with sqlite3.connect(db_path) as conn:
        reviews_count = conn.execute("SELECT COUNT(1) FROM reviews").fetchone()[0]
    assert reviews_count == 16

    # Run clustering end-to-end
    from agent.storage import load_reviews_for_run, upsert_review_embeddings

    reviews = load_reviews_for_run(db_path, run_id=run_id, language="en", min_chars=20)
    output, metrics = ClusteringService(settings).cluster(run_id=run_id, reviews=reviews)
    upsert_review_embeddings(db_path, output.embeddings)
    replace_clusters_for_run(db_path, run_id, output.clusters)

    assert metrics["embedded_reviews"] == 16
    assert len(output.embeddings) == 16
    assert len(output.clusters) >= 1

    with sqlite3.connect(db_path) as conn:
        emb_rows = conn.execute("SELECT COUNT(1) FROM review_embeddings").fetchone()[0]
        cl_rows = conn.execute(
            "SELECT COUNT(1) FROM clusters WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
    assert emb_rows == 16
    assert cl_rows == len(output.clusters)


def test_phase2_embedding_cache_hits_on_rerun(tmp_path: Path) -> None:
    cache_path = tmp_path / "embeddings.json"
    settings = ClusterSettings(
        language="en",
        min_chars=20,
        embedding_provider="local_hash",
        embedding_model_local="BAAI/bge-small-en-v1.5",
        embedding_model_openai="text-embedding-3-small",
        embedding_dimensions=32,
        cache_path=cache_path,
        umap_n_components=5,
        hdbscan_min_cluster_size=2,
        keyphrase_top_n=5,
        use_keybert=False,
    )
    reviews = [
        RawReview(
            id=f"x{i}",
            product_key="groww",
            source="playstore",
            external_id=f"x{i}",
            rating=5,
            title=None,
            body="great app for stock investing",
            posted_at=datetime(2026, 4, 18, 10, 0, 0),
            version="1.0.0",
            language="en",
            country="in",
            raw_json="{}",
        )
        for i in range(4)
    ]
    cluster_reviews = [
        ClusterReview(review_id=row.id, body=row.body, rating=row.rating)
        for row in reviews
    ]
    service = ClusteringService(settings)
    _, first = service.cluster(run_id="r1", reviews=cluster_reviews)
    _, second = service.cluster(run_id="r1", reviews=cluster_reviews)
    assert first["cache_hits"] == 0
    assert second["cache_hits"] == 4
