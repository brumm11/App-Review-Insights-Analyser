from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from google_play_scraper import Sort, reviews  # type: ignore[import-untyped]

from agent.ingestion.models import RawReview


class PlayStoreSource:
    def fetch(
        self,
        product_key: str,
        play_package: str,
        country: str,
        weeks: int,
    ) -> list[RawReview]:
        if not play_package:
            return []

        cutoff = datetime.utcnow() - timedelta(weeks=weeks)
        cursor: str | None = None
        results: list[RawReview] = []
        max_batches = 25
        for _ in range(max_batches):
            batch, cursor = reviews(
                play_package,
                lang="en",
                country=country,
                sort=Sort.NEWEST,
                count=200,
                continuation_token=cursor,
            )
            if not batch:
                break

            any_recent = False
            for item in batch:
                posted_at = item["at"].replace(tzinfo=None)
                if posted_at < cutoff:
                    continue
                any_recent = True

                external_id = str(
                    item.get("reviewId") or item.get("userName") or posted_at.isoformat()
                )
                text = str(item.get("content") or "").strip()
                record = RawReview(
                    id=RawReview.make_id("playstore", external_id),
                    product_key=product_key,
                    source="playstore",
                    external_id=external_id,
                    rating=int(item.get("score") or 0),
                    title=None,
                    body=text,
                    posted_at=posted_at,
                    version=item.get("reviewCreatedVersion"),
                    language=str(item.get("reviewLanguage") or "en"),
                    country=country,
                    raw_json=json.dumps(_jsonable(item), ensure_ascii=False),
                )
                results.append(record)

            if cursor is None or not any_recent:
                break

        return results


def _jsonable(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in item.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out
