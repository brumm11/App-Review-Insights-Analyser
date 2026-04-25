from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypedDict

from agent.ingestion.appstore import AppStoreSource
from agent.ingestion.filters import clean_and_validate
from agent.ingestion.models import RawReview
from agent.ingestion.playstore import PlayStoreSource
from agent.storage import (
    ensure_product_row,
    mark_run_status,
    upsert_reviews,
)
from agent.types import week_window


class ReviewSource(Protocol):
    def fetch(self, product_key: str, source_id: str, country: str, weeks: int) -> list[RawReview]:
        ...


class IngestionMetrics(TypedDict):
    fetched: int
    kept: int
    inserted: int
    updated: int
    at: str


class IngestionService:
    def __init__(
        self,
        db_path: Path,
        raw_dir: Path,
        appstore_source: AppStoreSource | None = None,
        playstore_source: PlayStoreSource | None = None,
    ) -> None:
        self.db_path = db_path
        self.raw_dir = raw_dir
        self.appstore_source = appstore_source or AppStoreSource()
        self.playstore_source = playstore_source or PlayStoreSource()

    def ingest(
        self,
        *,
        run_id: str,
        product_key: str,
        iso_week: str,
        weeks: int,
        appstore_id: str | None,
        play_package: str | None,
        country: str,
    ) -> IngestionMetrics:
        window = week_window(iso_week, weeks)
        ensure_product_row(self.db_path, product_key)
        mark_run_status(
            self.db_path,
            run_id=run_id,
            product_key=product_key,
            iso_week=iso_week,
            window_start=window.start.isoformat(),
            window_end=window.end.isoformat(),
            status="ingesting",
        )

        collected: list[RawReview] = []
        if appstore_id:
            collected.extend(
                self.appstore_source.fetch(
                    product_key=product_key,
                    appstore_id=appstore_id,
                    country=country,
                    weeks=weeks,
                )
            )
        if play_package:
            collected.extend(
                self.playstore_source.fetch(
                    product_key=product_key,
                    play_package=play_package,
                    country=country,
                    weeks=weeks,
                )
            )

        filtered = [item for item in (clean_and_validate(r) for r in collected) if item is not None]
        inserted, updated = upsert_reviews(self.db_path, filtered)
        self._write_snapshot(run_id=run_id, product_key=product_key, reviews=filtered)

        metrics: IngestionMetrics = {
            "fetched": len(collected),
            "kept": len(filtered),
            "inserted": inserted,
            "updated": updated,
            "at": datetime.utcnow().isoformat(),
        }
        mark_run_status(
            self.db_path,
            run_id=run_id,
            product_key=product_key,
            iso_week=iso_week,
            window_start=window.start.isoformat(),
            window_end=window.end.isoformat(),
            status="ingested",
            metrics_json=json.dumps(metrics),
        )
        return metrics

    def _write_snapshot(self, *, run_id: str, product_key: str, reviews: list[RawReview]) -> None:
        target = self.raw_dir / product_key
        target.mkdir(parents=True, exist_ok=True)
        file_path = target / f"{run_id}.jsonl"
        lines = [item.model_dump_json() for item in reviews]
        file_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
