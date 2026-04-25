from __future__ import annotations

import json
from datetime import datetime, timedelta
from xml.etree import ElementTree

import httpx

from agent.ingestion.models import RawReview


class AppStoreSource:
    def fetch(
        self,
        product_key: str,
        appstore_id: str,
        country: str,
        weeks: int,
    ) -> list[RawReview]:
        if not appstore_id:
            return []
        cutoff = datetime.utcnow() - timedelta(weeks=weeks)
        reviews: list[RawReview] = []

        for page in range(1, 11):
            url = (
                f"https://itunes.apple.com/{country}/rss/customerreviews/"
                f"page={page}/id={appstore_id}/sortby=mostrecent/xml"
            )
            response = httpx.get(url, timeout=20.0)
            response.raise_for_status()
            root = ElementTree.fromstring(response.text.encode("utf-8"))
            entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
            if len(entries) <= 1:
                break
            for entry in entries[1:]:
                body = entry.findtext(".//{http://www.w3.org/2005/Atom}content") or ""
                title = entry.findtext(".//{http://www.w3.org/2005/Atom}title")
                rating_text = entry.findtext(".//{http://itunes.apple.com/rss}rating") or "0"
                updated = entry.findtext(".//{http://www.w3.org/2005/Atom}updated") or ""
                author_id = entry.findtext(".//{http://www.w3.org/2005/Atom}id") or ""
                version = entry.findtext(".//{http://itunes.apple.com/rss}version")

                posted_at = datetime.fromisoformat(
                    updated.replace("Z", "+00:00")
                ).replace(tzinfo=None)
                if posted_at < cutoff:
                    continue

                review = RawReview(
                    id=RawReview.make_id("appstore", author_id),
                    product_key=product_key,
                    source="appstore",
                    external_id=author_id,
                    rating=int(rating_text),
                    title=title,
                    body=body.strip(),
                    posted_at=posted_at,
                    version=version,
                    language="en",
                    country=country,
                    raw_json=json.dumps(
                        {
                            "id": author_id,
                            "title": title,
                            "body": body,
                            "rating": rating_text,
                            "updated": updated,
                            "version": version,
                        },
                        ensure_ascii=False,
                    ),
                )
                reviews.append(review)

        return reviews
