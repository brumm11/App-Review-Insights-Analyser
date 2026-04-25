from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from agent.renderer.docs_tree import build_doc_requests, validate_doc_requests
from agent.renderer.email_html import render_email
from agent.summarization.models import PulseSummary


def load_schema(schema_path: Path) -> dict[str, object]:
    loaded = json.loads(schema_path.read_text(encoding="utf-8"))
    return cast(dict[str, object], loaded)


def render_artifacts(
    *,
    run_id: str,
    summary: PulseSummary,
    artifacts_dir: Path,
    schema: dict[str, object],
) -> dict[str, Path]:
    target = artifacts_dir / run_id
    target.mkdir(parents=True, exist_ok=True)

    doc_requests = build_doc_requests(summary)
    validate_doc_requests(doc_requests, schema)
    subject, html, text = render_email(summary)

    doc_path = target / "doc_requests.json"
    html_path = target / "email.html"
    text_path = target / "email.txt"
    subject_path = target / "subject.txt"
    doc_payload = json.dumps({"requests": doc_requests}, ensure_ascii=False, indent=2)
    doc_path.write_text(doc_payload, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    text_path.write_text(text, encoding="utf-8")
    subject_path.write_text(subject, encoding="utf-8")
    return {
        "doc_requests": doc_path,
        "email_html": html_path,
        "email_text": text_path,
        "subject": subject_path,
    }
