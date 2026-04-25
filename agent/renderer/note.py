from __future__ import annotations

from agent.summarization.models import PulseSummary

MAX_NOTE_WORDS = 250


def _word_count(text: str) -> int:
    return len([token for token in text.split() if token.strip()])


def _trim_to_words(text: str, max_words: int) -> str:
    words = [token for token in text.split() if token.strip()]
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(".,;:") + "..."


def build_weekly_note(summary: PulseSummary, max_words: int = MAX_NOTE_WORDS) -> str:
    themes = summary.top_themes[:3]
    quotes = summary.quotes[:3]
    actions = summary.action_ideas[:3]

    lines = [
        f"# Weekly Product Pulse - {summary.product} ({summary.window.iso_week})",
        "",
        f"_Window: {summary.window.start} to {summary.window.end}_",
        "",
        "## Top 3 themes",
    ]
    for idx, theme in enumerate(themes, start=1):
        lines.append(f"{idx}. **{theme.label}** - {theme.description}")

    lines.extend(["", "## 3 user quotes"])
    for idx, quote in enumerate(quotes, start=1):
        lines.append(f"{idx}. > \"{quote.text}\"")

    lines.extend(["", "## 3 action ideas"])
    for idx, action in enumerate(actions, start=1):
        lines.append(f"{idx}. **{action.title}**: {action.detail}")

    note = "\n".join(lines).strip()
    if _word_count(note) <= max_words:
        return note

    lines = [
        f"# Weekly Product Pulse - {summary.product} ({summary.window.iso_week})",
        "",
        f"_Window: {summary.window.start} to {summary.window.end}_",
        "",
        "## Top 3 themes",
    ]
    for idx, theme in enumerate(themes, start=1):
        short_desc = _trim_to_words(theme.description, 12)
        lines.append(f"{idx}. **{theme.label}** - {short_desc}")
    lines.extend(["", "## 3 user quotes"])
    for idx, quote in enumerate(quotes, start=1):
        lines.append(f"{idx}. > \"{_trim_to_words(quote.text, 12)}\"")
    lines.extend(["", "## 3 action ideas"])
    for idx, action in enumerate(actions, start=1):
        lines.append(f"{idx}. **{action.title}**: {_trim_to_words(action.detail, 10)}")

    compressed = "\n".join(lines).strip()
    if _word_count(compressed) <= max_words:
        return compressed
    return _trim_to_words(compressed, max_words)
