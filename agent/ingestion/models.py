from __future__ import annotations

from datetime import datetime
from hashlib import sha1
from typing import Literal

from pydantic import BaseModel


class RawReview(BaseModel):
    id: str
    product_key: str
    source: Literal["appstore", "playstore"]
    external_id: str
    rating: int
    title: str | None
    body: str
    posted_at: datetime
    version: str | None
    language: str
    country: str
    raw_json: str

    @staticmethod
    def make_id(source: str, external_id: str) -> str:
        return sha1(f"{source}:{external_id}".encode()).hexdigest()
