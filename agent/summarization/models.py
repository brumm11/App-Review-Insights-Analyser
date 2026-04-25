from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class WindowModel(BaseModel):
    start: date
    end: date
    weeks: int
    iso_week: str


class PulseStats(BaseModel):
    total_reviews: int
    avg_rating: float
    rating_delta_vs_prev: float


class Theme(BaseModel):
    id: str
    rank: int
    label: str
    description: str
    sentiment: Literal["negative", "mixed", "positive"]
    review_count: int
    representative_review_ids: list[str]


class Quote(BaseModel):
    theme_id: str
    text: str
    review_id: str


class ActionIdea(BaseModel):
    theme_id: str
    title: str
    detail: str


class AudienceValue(BaseModel):
    audience: str
    value: str


class PulseSummary(BaseModel):
    product: str
    window: WindowModel
    stats: PulseStats
    top_themes: list[Theme] = Field(default_factory=list)
    quotes: list[Quote] = Field(default_factory=list)
    action_ideas: list[ActionIdea] = Field(default_factory=list)
    what_this_solves: list[AudienceValue] = Field(default_factory=list)
