from __future__ import annotations

import pytest

from agent.summarization.llm import PulseCostExceeded
from agent.summarization.service import SummarizationService


def _sample_inputs() -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    clusters = [
        {
            "id": "c1",
            "review_ids": ["r1", "r2"],
            "keyphrases": ["crash", "payment"],
            "medoid_review_id": "r1",
        },
        {
            "id": "c2",
            "review_ids": ["r3", "r4"],
            "keyphrases": ["onboarding", "smooth"],
            "medoid_review_id": "r3",
        },
    ]
    reviews = {
        "r1": {"id": "r1", "body": "App crashes while payment flow", "rating": 1},
        "r2": {"id": "r2", "body": "Payment fails and app hangs", "rating": 2},
        "r3": {"id": "r3", "body": "Onboarding is smooth and easy", "rating": 5},
        "r4": {"id": "r4", "body": "Great app for investing journey", "rating": 5},
    }
    return clusters, reviews


def _many_clusters() -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    clusters: list[dict[str, object]] = []
    reviews: dict[str, dict[str, object]] = {}
    for idx in range(7):
        rid = f"r{idx+1}"
        cid = f"c{idx+1}"
        reviews[rid] = {"id": rid, "body": f"Issue {idx} in payments and onboarding", "rating": 2}
        clusters.append(
            {
                "id": cid,
                "review_ids": [rid],
                "keyphrases": [f"theme_{idx}"],
                "medoid_review_id": rid,
            }
        )
    return clusters, reviews


def test_phase3_summary_deterministic_and_grounded() -> None:
    clusters, reviews = _sample_inputs()
    service = SummarizationService(
        max_retries=1,
        timeout_seconds=5,
        token_cap=10000,
        cost_cap_usd=1.0,
    )
    first, _ = service.summarize_pulse(
        product="groww",
        iso_week="2026-W16",
        window_start="2026-04-13",
        window_end="2026-04-19",
        clusters=clusters,
        reviews_by_id=reviews,
    )
    second, _ = service.summarize_pulse(
        product="groww",
        iso_week="2026-W16",
        window_start="2026-04-13",
        window_end="2026-04-19",
        clusters=clusters,
        reviews_by_id=reviews,
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    normalized_review_text = " ".join(value["body"].lower() for value in reviews.values())
    for quote in first.quotes:
        assert quote.text.lower() in normalized_review_text


def test_phase3_theme_cap_is_max_five() -> None:
    clusters, reviews = _many_clusters()
    service = SummarizationService(
        max_retries=1,
        timeout_seconds=5,
        token_cap=10000,
        cost_cap_usd=1.0,
    )
    summary, _ = service.summarize_pulse(
        product="groww",
        iso_week="2026-W16",
        window_start="2026-04-13",
        window_end="2026-04-19",
        clusters=clusters,
        reviews_by_id=reviews,
    )
    assert len(summary.top_themes) == 5


def test_phase3_cost_cap_raises() -> None:
    clusters, reviews = _sample_inputs()
    service = SummarizationService(
        max_retries=1,
        timeout_seconds=5,
        token_cap=5,
        cost_cap_usd=1.0,
    )
    with pytest.raises(PulseCostExceeded):
        service.summarize_pulse(
            product="groww",
            iso_week="2026-W16",
            window_start="2026-04-13",
            window_end="2026-04-19",
            clusters=clusters,
            reviews_by_id=reviews,
        )
