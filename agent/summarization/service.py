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
MAX_THEMES = 5
NOTE_THEMES = 3
NOTE_QUOTES = 3
NOTE_ACTIONS = 3
GENERIC_KEYWORDS = {
    "and",
    "this",
    "that",
    "with",
    "from",
    "have",
    "very",
    "good",
    "great",
    "easy",
    "nice",
    "groww",
    "application",
    "time",
    "app",
}
THEME_RULES: list[tuple[str, set[str], str]] = [
    (
        "Onboarding",
        {"signup", "onboard", "onboarding", "register", "kycstart"},
        "Account setup and first-use journey friction.",
    ),
    (
        "KYC & Verification",
        {"kyc", "verify", "verification", "pan", "aadhaar", "document", "documents"},
        "Identity verification and compliance flow issues.",
    ),
    (
        "Payments & Transactions",
        {
            "payment",
            "payments",
            "upi",
            "transfer",
            "deposit",
            "withdraw",
            "withdrawal",
            "failed",
            "transaction",
        },
        "Money movement reliability and transaction completion issues.",
    ),
    (
        "Portfolio & Statements",
        {"statement", "statements", "portfolio", "holdings", "report", "reports", "tax", "pnl"},
        "Portfolio visibility, reports, and statement clarity gaps.",
    ),
    (
        "Performance & Reliability",
        {"crash", "slow", "hang", "loading", "lag", "bug", "issue", "error"},
        "App responsiveness, crashes, and reliability concerns.",
    ),
]


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

        deduped = self._merge_themes_by_label(themes)
        ranked = sorted(
            deduped,
            key=lambda t: t.review_count * abs(self._sentiment_weight(t.sentiment)),
            reverse=True,
        )[:MAX_THEMES]
        ranked = [
            theme.model_copy(update={"rank": idx})
            for idx, theme in enumerate(ranked, start=1)
        ]
        note_themes = ranked[:NOTE_THEMES]
        quotes = self.select_quotes(note_themes, reviews_by_id)[:NOTE_QUOTES]
        ideas = self.generate_action_ideas(note_themes)[:NOTE_ACTIONS]

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
        candidates = [phrase.lower() for phrase in keyphrases]
        candidate_text = " ".join(candidates)
        sample_text = (medoid_reviews[0] if medoid_reviews else "").lower()
        for label, keywords, description in THEME_RULES:
            has_keyword = any(term in candidate_text for term in keywords)
            has_text_match = any(term in sample_text for term in keywords)
            if has_keyword or has_text_match:
                return {
                    "label": label,
                    "description": description,
                    "sample": scrub_pii(medoid_reviews[0] if medoid_reviews else ""),
                }

        return {
            "label": "Overall Experience",
            "description": "General usability and trust feedback that does not fit a single flow.",
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
    def _merge_themes_by_label(themes: list[Theme]) -> list[Theme]:
        merged: dict[str, Theme] = {}
        for theme in themes:
            key = theme.label.lower().strip()
            existing = merged.get(key)
            if existing is None:
                merged[key] = theme
                continue
            sentiments = [existing.sentiment, theme.sentiment]
            if "negative" in sentiments:
                sentiment = "negative"
            elif "mixed" in sentiments:
                sentiment = "mixed"
            else:
                sentiment = "positive"
            reps = list(
                dict.fromkeys(
                    existing.representative_review_ids + theme.representative_review_ids
                )
            )
            merged[key] = existing.model_copy(
                update={
                    "review_count": existing.review_count + theme.review_count,
                    "representative_review_ids": reps[:3],
                    "sentiment": sentiment,
                }
            )
        return list(merged.values())

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
