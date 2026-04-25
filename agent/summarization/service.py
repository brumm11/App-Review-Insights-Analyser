from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

from agent.ingestion.filters import scrub_pii
from agent.summarization.llm import BudgetedLLM, GroqLLMClient, MockLLMClient
from agent.summarization.models import (
    ActionIdea,
    AudienceValue,
    PulseStats,
    PulseSummary,
    Quote,
    Theme,
    WindowModel,
)

NORM_SPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    return NORM_SPACE.sub(" ", value.strip().lower())


class SummarizationService:
    def __init__(
        self,
        *,
        provider: str = "mock",
        model: str = "mock-v1",
        groq_api_key: str | None = None,
        max_retries: int,
        timeout_seconds: int,
        token_cap: int,
        cost_cap_usd: float,
    ) -> None:
        llm_client = (
            GroqLLMClient(model=model, api_key=groq_api_key)
            if provider.lower() == "groq"
            else MockLLMClient()
        )
        self.llm = BudgetedLLM(
            llm_client,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            token_cap=token_cap,
            cost_cap_usd=cost_cap_usd,
        )

    def summarize_pulse(
        self,
        *,
        product: str,
        iso_week: str,
        window_start: str,
        window_end: str,
        clusters: list[dict[str, Any]],
        reviews_by_id: dict[str, dict[str, Any]],
    ) -> tuple[PulseSummary, dict[str, Any]]:
        themes: list[Theme] = []
        for cluster in clusters:
            payload = self.label_theme(
                keyphrases=cluster["keyphrases"],
                medoid_reviews=[reviews_by_id.get(cluster["medoid_review_id"], {}).get("body", "")],
            )
            _ = self.llm.call_json("label_theme", payload)

            review_ids = cluster["review_ids"]
            ratings = [
                int(reviews_by_id[x]["rating"])
                for x in review_ids
                if x in reviews_by_id
            ]
            sentiment = self._infer_sentiment(ratings)
            themes.append(
                Theme(
                    id=cluster["id"],
                    rank=0,
                    label=payload["label"],
                    description=payload["description"],
                    sentiment=sentiment,
                    review_count=len(review_ids),
                    representative_review_ids=review_ids[:3],
                )
            )

        ranked = sorted(
            themes,
            key=lambda t: t.review_count * abs(self._sentiment_weight(t.sentiment)),
            reverse=True,
        )[:3]
        ranked = [
            theme.model_copy(update={"rank": idx})
            for idx, theme in enumerate(ranked, start=1)
        ]

        quotes = self.select_quotes(ranked, reviews_by_id)
        ideas = self.generate_action_ideas(ranked)

        all_ratings = [int(item["rating"]) for item in reviews_by_id.values()]
        summary = PulseSummary(
            product=product,
            window=WindowModel(
                start=date.fromisoformat(window_start),
                end=date.fromisoformat(window_end),
                weeks=1,
                iso_week=iso_week,
            ),
            stats=PulseStats(
                total_reviews=len(reviews_by_id),
                avg_rating=(sum(all_ratings) / len(all_ratings)) if all_ratings else 0.0,
                rating_delta_vs_prev=0.0,
            ),
            top_themes=ranked,
            quotes=quotes,
            action_ideas=ideas,
            what_this_solves=self.build_what_this_solves(),
        )
        metrics = {
            "llm_tokens": self.llm.total_tokens,
            "llm_cost_usd": self.llm.total_cost,
        }
        return summary, metrics

    def label_theme(self, *, keyphrases: list[str], medoid_reviews: list[str]) -> dict[str, str]:
        keyword = keyphrases[0] if keyphrases else "experience"
        return {
            "label": keyword.replace("_", " ").title(),
            "description": f"Users consistently discuss {keyword} in recent reviews.",
            "sample": scrub_pii(medoid_reviews[0] if medoid_reviews else ""),
        }

    def select_quotes(
        self,
        themes: list[Theme],
        reviews_by_id: dict[str, dict[str, Any]],
    ) -> list[Quote]:
        out: list[Quote] = []
        for theme in themes:
            candidates = [
                reviews_by_id[rid]
                for rid in theme.representative_review_ids
                if rid in reviews_by_id
            ]
            if not candidates:
                continue
            selected = scrub_pii(str(candidates[0]["body"]))
            quote = Quote(theme_id=theme.id, text=selected, review_id=str(candidates[0]["id"]))
            if self._is_verbatim_quote(quote.text, [str(c["body"]) for c in candidates]):
                out.append(quote)
            else:
                repaired = self._repair_quote([str(c["body"]) for c in candidates])
                if repaired is not None:
                    out.append(
                        Quote(
                            theme_id=theme.id,
                            text=repaired,
                            review_id=str(candidates[0]["id"]),
                        )
                    )
        return out

    def generate_action_ideas(self, themes: list[Theme]) -> list[ActionIdea]:
        ideas: list[ActionIdea] = []
        for theme in themes:
            ideas.append(
                ActionIdea(
                    theme_id=theme.id,
                    title=f"Improve {theme.label}",
                    detail=(
                        "Prioritize fixes and experiments around "
                        f"{theme.label.lower()} pain points."
                    ),
                )
            )
        return ideas

    @staticmethod
    def build_what_this_solves() -> list[AudienceValue]:
        return [
            AudienceValue(audience="Product", value="Highlights top user pain points by volume"),
            AudienceValue(audience="Support", value="Provides grounded quotes for triage context"),
        ]

    @staticmethod
    def _infer_sentiment(
        ratings: list[int],
    ) -> Literal["negative", "mixed", "positive"]:
        if not ratings:
            return "mixed"
        avg = sum(ratings) / len(ratings)
        if avg <= 2.4:
            return "negative"
        if avg >= 3.8:
            return "positive"
        return "mixed"

    @staticmethod
    def _sentiment_weight(value: str) -> int:
        return {"negative": -2, "mixed": 1, "positive": 1}.get(value, 1)

    @staticmethod
    def _is_verbatim_quote(candidate: str, review_bodies: list[str]) -> bool:
        norm = normalize_text(candidate)
        return any(norm in normalize_text(body) for body in review_bodies)

    @staticmethod
    def _repair_quote(review_bodies: list[str]) -> str | None:
        if not review_bodies:
            return None
        return scrub_pii(review_bodies[0]).strip()


def write_summary(path: Path, summary: PulseSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2)
    path.write_text(payload, encoding="utf-8")
