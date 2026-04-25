from __future__ import annotations

from jsonschema import Draft202012Validator

from agent.summarization.models import PulseSummary


def build_anchor(product: str, iso_week: str) -> str:
    return f"pulse-{product.lower()}-{iso_week}"


def build_doc_requests(summary: PulseSummary) -> list[dict[str, object]]:
    anchor = build_anchor(summary.product, summary.window.iso_week)
    heading = (
        f"Weekly Pulse — {summary.product} — {summary.window.iso_week} "
        f"({summary.window.start} → {summary.window.end}) [{anchor}]"
    )
    requests: list[dict[str, object]] = [
        {"kind": "heading1", "text": heading, "anchor": anchor},
        {
            "kind": "paragraph",
            "text": (
                "Executive snapshot of customer feedback trends from public app-store reviews. "
                "Focus on high-impact friction themes and immediate product actions."
            ),
        },
        {
            "kind": "stats",
            "items": {
                "Total reviews": summary.stats.total_reviews,
                "Average rating": round(summary.stats.avg_rating, 2),
                "Rating delta vs previous window": round(summary.stats.rating_delta_vs_prev, 2),
            },
        },
        {"kind": "heading2", "text": "Top 3 Themes"},
    ]
    for theme in summary.top_themes[:3]:
        requests.append({"kind": "heading2", "text": f"{theme.rank}. {theme.label}"})
        requests.append({"kind": "paragraph", "text": theme.description})
        requests.append(
            {
                "kind": "bullets",
                "items": [
                    f"Sentiment: {theme.sentiment}",
                    f"Review count: {theme.review_count}",
                    "Representative examples selected from review set.",
                ],
            }
        )
    if summary.quotes:
        requests.append({"kind": "heading2", "text": "Verbatim Quotes"})
        requests.append({"kind": "quotes", "items": [quote.text for quote in summary.quotes[:3]]})
    if summary.action_ideas:
        requests.append({"kind": "heading2", "text": "Action Ideas"})
        requests.append(
            {
                "kind": "bullets",
                "items": [f"{idea.title}: {idea.detail}" for idea in summary.action_ideas[:3]],
            }
        )
    requests.append(
        {
            "kind": "table",
            "title": "What This Solves",
            "columns": ["Audience", "Value"],
            "rows": [[item.audience, item.value] for item in summary.what_this_solves],
        }
    )
    requests.append({"kind": "separator"})
    return requests


def validate_doc_requests(requests: list[dict[str, object]], schema: dict[str, object]) -> None:
    Draft202012Validator(schema).validate({"requests": requests})
