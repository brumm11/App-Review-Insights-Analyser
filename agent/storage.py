from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agent.clustering.models import ClusterRecord, ClusterReview
from agent.ingestion.models import RawReview

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    key TEXT PRIMARY KEY,
    display TEXT NOT NULL,
    appstore_id TEXT,
    play_package TEXT,
    gdoc_id TEXT,
    gmail_to TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    product_key TEXT NOT NULL,
    source TEXT NOT NULL,
    rating INTEGER NOT NULL,
    title TEXT,
    body TEXT NOT NULL,
    posted_at DATETIME NOT NULL,
    version TEXT,
    language TEXT NOT NULL,
    country TEXT NOT NULL,
    ingested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_embeddings (
    review_id TEXT PRIMARY KEY,
    embedding BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    product_key TEXT NOT NULL,
    iso_week TEXT NOT NULL,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    status TEXT NOT NULL,
    metrics_json TEXT,
    gdoc_heading_id TEXT,
    gmail_message_id TEXT
);

CREATE TABLE IF NOT EXISTS themes (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    label TEXT NOT NULL,
    description TEXT NOT NULL,
    sentiment TEXT NOT NULL,
    review_count INTEGER NOT NULL,
    representative_review_ids_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clusters (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    review_ids_json TEXT NOT NULL,
    keyphrases_json TEXT NOT NULL,
    medoid_review_id TEXT NOT NULL
);
"""


def initialize_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def ensure_product_row(db_path: Path, product_key: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO products (key, display)
            VALUES (?, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (product_key, product_key),
        )
        conn.commit()


def upsert_reviews(db_path: Path, reviews: list[RawReview]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    with sqlite3.connect(db_path) as conn:
        for item in reviews:
            exists = conn.execute("SELECT 1 FROM reviews WHERE id = ?", (item.id,)).fetchone()
            conn.execute(
                """
                INSERT INTO reviews (
                    id, product_key, source, rating, title, body, posted_at,
                    version, language, country, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    rating = excluded.rating,
                    title = excluded.title,
                    body = excluded.body,
                    posted_at = excluded.posted_at,
                    version = excluded.version,
                    language = excluded.language,
                    country = excluded.country,
                    raw_json = excluded.raw_json,
                    ingested_at = CURRENT_TIMESTAMP
                """,
                (
                    item.id,
                    item.product_key,
                    item.source,
                    item.rating,
                    item.title,
                    item.body,
                    item.posted_at.isoformat(),
                    item.version,
                    item.language,
                    item.country,
                    item.raw_json,
                ),
            )
            if exists:
                updated += 1
            else:
                inserted += 1
        conn.commit()
    return inserted, updated


def mark_run_status(
    db_path: Path,
    *,
    run_id: str,
    product_key: str,
    iso_week: str,
    window_start: str,
    window_end: str,
    status: str,
    metrics_json: str | None = None,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO runs (
                id, product_key, iso_week, window_start, window_end, status, metrics_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                metrics_json = COALESCE(excluded.metrics_json, runs.metrics_json)
            """,
            (run_id, product_key, iso_week, window_start, window_end, status, metrics_json),
        )
        conn.commit()


def load_run_window(db_path: Path, run_id: str) -> tuple[str, str, str] | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT product_key, window_start, window_end FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1]), str(row[2])


def load_run_context(db_path: Path, run_id: str) -> tuple[str, str, str, str] | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT product_key, iso_week, window_start, window_end FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1]), str(row[2]), str(row[3])


def load_reviews_for_run(
    db_path: Path,
    *,
    run_id: str,
    language: str,
    min_chars: int,
) -> list[ClusterReview]:
    run = load_run_window(db_path, run_id)
    if run is None:
        return []
    product_key, start, end = run
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, body, rating
            FROM reviews
            WHERE product_key = ?
              AND language = ?
              AND length(body) >= ?
              AND date(posted_at) BETWEEN date(?) AND date(?)
            ORDER BY posted_at ASC, id ASC
            """,
            (product_key, language, min_chars, start, end),
        ).fetchall()
    return [
        ClusterReview(review_id=str(row[0]), body=str(row[1]), rating=int(row[2]))
        for row in rows
    ]


def upsert_review_embeddings(db_path: Path, embeddings: dict[str, list[float]]) -> None:
    with sqlite3.connect(db_path) as conn:
        for review_id, vector in embeddings.items():
            conn.execute(
                """
                INSERT INTO review_embeddings (review_id, embedding)
                VALUES (?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                    embedding = excluded.embedding
                """,
                (review_id, json.dumps(vector)),
            )
        conn.commit()


def replace_clusters_for_run(db_path: Path, run_id: str, clusters: list[ClusterRecord]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM clusters WHERE run_id = ?", (run_id,))
        for cluster in clusters:
            conn.execute(
                """
                INSERT INTO clusters (
                    id, run_id, review_ids_json, keyphrases_json, medoid_review_id
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cluster.id,
                    cluster.run_id,
                    json.dumps(cluster.review_ids),
                    json.dumps(cluster.keyphrases),
                    cluster.medoid_review_id,
                ),
            )
        conn.commit()


def load_clusters_for_run(db_path: Path, run_id: str) -> list[dict[str, object]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, review_ids_json, keyphrases_json, medoid_review_id
            FROM clusters
            WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()
    return [
        {
            "id": str(row[0]),
            "review_ids": json.loads(str(row[1])),
            "keyphrases": json.loads(str(row[2])),
            "medoid_review_id": str(row[3]),
        }
        for row in rows
    ]


def load_reviews_map(db_path: Path, review_ids: list[str]) -> dict[str, dict[str, object]]:
    if not review_ids:
        return {}
    placeholders = ",".join("?" for _ in review_ids)
    query = (
        "SELECT id, body, rating FROM reviews "
        f"WHERE id IN ({placeholders})"
    )
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(query, tuple(review_ids)).fetchall()
    return {
        str(row[0]): {"id": str(row[0]), "body": str(row[1]), "rating": int(row[2])}
        for row in rows
    }


def load_reviews_for_csv(db_path: Path, run_id: str) -> list[dict[str, str]]:
    run = load_run_window(db_path, run_id)
    if run is None:
        return []
    product_key, start, end = run
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, source, rating, title, body, posted_at, language, country
            FROM reviews
            WHERE product_key = ?
              AND date(posted_at) BETWEEN date(?) AND date(?)
            ORDER BY posted_at ASC, id ASC
            """,
            (product_key, start, end),
        ).fetchall()
    return [
        {
            "id": str(row[0]),
            "source": str(row[1]),
            "rating": str(row[2]),
            "title": str(row[3] or ""),
            "body": str(row[4]),
            "posted_at": str(row[5]),
            "language": str(row[6]),
            "country": str(row[7]),
        }
        for row in rows
    ]


def update_run_metrics(db_path: Path, run_id: str, new_metrics: dict[str, object]) -> None:
    with sqlite3.connect(db_path) as conn:
        existing = conn.execute("SELECT metrics_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        base: dict[str, object] = {}
        if existing and existing[0]:
            base = json.loads(str(existing[0]))
        base.update(new_metrics)
        conn.execute(
            "UPDATE runs SET metrics_json = ? WHERE id = ?",
            (json.dumps(base), run_id),
        )
        conn.commit()


def set_product_gdoc_id(db_path: Path, product_key: str, gdoc_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE products SET gdoc_id = ? WHERE key = ?", (gdoc_id, product_key))
        conn.commit()


def get_product_gdoc_id(db_path: Path, product_key: str) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT gdoc_id FROM products WHERE key = ?", (product_key,)).fetchone()
    if row is None or row[0] is None or str(row[0]).strip() == "":
        return None
    return str(row[0])


def set_run_delivery(
    db_path: Path,
    *,
    run_id: str,
    gdoc_heading_id: str | None = None,
    gmail_message_id: str | None = None,
) -> None:
    with sqlite3.connect(db_path) as conn:
        if gdoc_heading_id is not None:
            conn.execute(
                "UPDATE runs SET gdoc_heading_id = ? WHERE id = ?",
                (gdoc_heading_id, run_id),
            )
        if gmail_message_id is not None:
            conn.execute(
                "UPDATE runs SET gmail_message_id = ? WHERE id = ?",
                (gmail_message_id, run_id),
            )
        conn.commit()


def get_run_delivery(db_path: Path, run_id: str) -> tuple[str | None, str | None]:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT gdoc_heading_id, gmail_message_id FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None, None
    heading = str(row[0]) if row[0] is not None and str(row[0]).strip() else None
    message = str(row[1]) if row[1] is not None and str(row[1]).strip() else None
    return heading, message
