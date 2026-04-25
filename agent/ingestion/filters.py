from __future__ import annotations

import re

from agent.ingestion.models import RawReview

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+91[- ]?)?[6-9]\d{9}\b")
AADHAAR_RE = re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}\b")
WORD_RE = re.compile(r"\b[\w']+\b")

# Broad emoji/symbol ranges.
EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001F6FF\U0001F700-\U0001F77F\U0001F900-\U0001F9FF"
    r"\U0001FA70-\U0001FAFF\U00002700-\U000027BF]"
)


def scrub_pii(text: str) -> str:
    value = EMAIL_RE.sub("[redacted-email]", text)
    value = PHONE_RE.sub("[redacted-phone]", value)
    value = AADHAAR_RE.sub("[redacted-id]", value)
    return value


def contains_emoji(text: str) -> bool:
    return EMOJI_RE.search(text) is not None


def is_english(language: str, text: str) -> bool:
    lang = language.lower().strip()
    if lang in {"en", "en-us", "en-gb"}:
        return True
    if lang and lang not in {"unknown", "und"}:
        return False
    letters = re.findall(r"[A-Za-z]", text)
    non_ascii_letters = re.findall(r"[^\x00-\x7F]", text)
    return len(letters) >= max(4, len(non_ascii_letters) * 2)


def has_min_words(text: str, minimum: int = 4) -> bool:
    return len(WORD_RE.findall(text)) >= minimum


def clean_and_validate(review: RawReview) -> RawReview | None:
    if contains_emoji(review.body):
        return None
    if not is_english(review.language, review.body):
        return None
    if not has_min_words(review.body, 4):
        return None
    return review.model_copy(update={"body": scrub_pii(review.body)})
