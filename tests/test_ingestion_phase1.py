from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from agent.ingestion.models import RawReview
from agent.ingestion.service import IngestionService
from agent.storage import initialize_db


class FakeAppStoreSource:
    def fetch(
        self,
        product_key: str,
        appstore_id: str,
        country: str,
        weeks: int,
    ) -> list[RawReview]:
        return [
            RawReview(
                id=RawReview.make_id("appstore", "a1"),
                product_key=product_key,
                source="appstore",
                external_id="a1",
                rating=4,
                title="Good app",
                body="Great experience and easy navigation",
                posted_at=datetime(2026, 4, 20, 10, 0, 0),
                version="1.0.0",
                language="en",
                country=country,
                raw_json='{"id":"a1"}',
            ),
            RawReview(
                id=RawReview.make_id("appstore", "a2"),
                product_key=product_key,
                source="appstore",
                external_id="a2",
                rating=1,
                title="emoji",
                body="Bad app 😡 crashes often",
                posted_at=datetime(2026, 4, 20, 10, 0, 0),
                version="1.0.0",
                language="en",
                country=country,
                raw_json='{"id":"a2"}',
            ),
        ]


class FakePlayStoreSource:
    def fetch(
        self,
        product_key: str,
        play_package: str,
        country: str,
        weeks: int,
    ) -> list[RawReview]:
        return [
            RawReview(
                id=RawReview.make_id("playstore", "p1"),
                product_key=product_key,
                source="playstore",
                external_id="p1",
                rating=5,
                title=None,
                body="my email is test@example.com and number is 9876543210",
                posted_at=datetime(2026, 4, 20, 10, 0, 0),
                version="2.0.0",
                language="en",
                country=country,
                raw_json='{"reviewId":"p1"}',
            ),
            RawReview(
                id=RawReview.make_id("playstore", "p2"),
                product_key=product_key,
                source="playstore",
                external_id="p2",
                rating=2,
                title=None,
                body="Muy buena app para inversion",
                posted_at=datetime(2026, 4, 20, 10, 0, 0),
                version="2.0.0",
                language="es",
                country=country,
                raw_json='{"reviewId":"p2"}',
            ),
            RawReview(
                id=RawReview.make_id("playstore", "p3"),
                product_key=product_key,
                source="playstore",
                external_id="p3",
                rating=3,
                title=None,
                body="Too bad",
                posted_at=datetime(2026, 4, 20, 10, 0, 0),
                version="2.0.0",
                language="en",
                country=country,
                raw_json='{"reviewId":"p3"}',
            ),
        ]


def test_phase1_ingestion_filters_and_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "pulse.db"
    raw_dir = tmp_path / "raw"
    initialize_db(db_path)
    service = IngestionService(
        db_path=db_path,
        raw_dir=raw_dir,
        appstore_source=FakeAppStoreSource(),
        playstore_source=FakePlayStoreSource(),
    )

    run_id = "run123"
    metrics = service.ingest(
        run_id=run_id,
        product_key="groww",
        iso_week="2026-W16",
        weeks=10,
        appstore_id="fake",
        play_package="fake.package",
        country="in",
    )
    assert metrics == {
        "fetched": 5,
        "kept": 2,
        "inserted": 2,
        "updated": 0,
        "at": metrics["at"],
    }

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT body FROM reviews ORDER BY id").fetchall()
    bodies = [body for (body,) in rows]
    assert len(bodies) == 2
    assert any("[redacted-email]" in body for body in bodies)
    assert any("[redacted-phone]" in body for body in bodies)

    snapshot = raw_dir / "groww" / f"{run_id}.jsonl"
    assert snapshot.exists()
    lines = [line for line in snapshot.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2


def test_phase1_ingestion_rerun_updates_not_inserts(tmp_path: Path) -> None:
    db_path = tmp_path / "pulse.db"
    raw_dir = tmp_path / "raw"
    initialize_db(db_path)
    service = IngestionService(
        db_path=db_path,
        raw_dir=raw_dir,
        appstore_source=FakeAppStoreSource(),
        playstore_source=FakePlayStoreSource(),
    )
    kwargs = {
        "run_id": "run123",
        "product_key": "groww",
        "iso_week": "2026-W16",
        "weeks": 10,
        "appstore_id": "fake",
        "play_package": "fake.package",
        "country": "in",
    }
    first = service.ingest(**kwargs)
    second = service.ingest(**kwargs)
    assert first["inserted"] == 2
    assert second["inserted"] == 0
    assert second["updated"] == 2
