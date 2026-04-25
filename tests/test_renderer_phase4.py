from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from agent.renderer.docs_tree import validate_doc_requests
from agent.renderer.service import load_schema, render_artifacts
from agent.summarization.models import (
    ActionIdea,
    AudienceValue,
    PulseStats,
    PulseSummary,
    Quote,
    Theme,
    WindowModel,
)


def _summary() -> PulseSummary:
    return PulseSummary(
        product="groww",
        window=WindowModel(start="2026-04-13", end="2026-04-19", weeks=1, iso_week="2026-W16"),
        stats=PulseStats(total_reviews=10, avg_rating=4.1, rating_delta_vs_prev=0.1),
        top_themes=[
            Theme(
                id="t1",
                rank=1,
                label="Payment Failures",
                description="Users report frequent payment failures.",
                sentiment="negative",
                review_count=5,
                representative_review_ids=["r1", "r2"],
            )
        ],
        quotes=[Quote(theme_id="t1", text="Payment fails every time", review_id="r1")],
        action_ideas=[
            ActionIdea(
                theme_id="t1",
                title="Fix payments",
                detail="Audit gateway retries.",
            )
        ],
        what_this_solves=[AudienceValue(audience="Product", value="Prioritizes top issue")],
    )


def test_phase4_render_outputs_are_deterministic(tmp_path: Path) -> None:
    schema = load_schema(Path("templates/doc_section.schema.json"))
    summary = _summary()
    first = render_artifacts(run_id="run1", summary=summary, artifacts_dir=tmp_path, schema=schema)
    second = render_artifacts(run_id="run1", summary=summary, artifacts_dir=tmp_path, schema=schema)
    assert first["doc_requests"].read_text(encoding="utf-8") == second["doc_requests"].read_text(
        encoding="utf-8"
    )
    assert first["email_html"].read_text(encoding="utf-8") == second["email_html"].read_text(
        encoding="utf-8"
    )
    payload = json.loads(first["doc_requests"].read_text(encoding="utf-8"))
    assert payload["requests"][0]["anchor"] == "pulse-groww-2026-W16"


def test_phase4_schema_rejects_malformed_doc_requests() -> None:
    schema = load_schema(Path("templates/doc_section.schema.json"))
    with pytest.raises(ValidationError):
        validate_doc_requests([{"text": "missing-kind"}], schema)
