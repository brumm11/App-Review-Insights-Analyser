from __future__ import annotations

import json
from pathlib import Path

from agent.mcp_client.docs_ops import DocsOps
from agent.mcp_client.gmail_ops import GmailOps
from agent.mcp_client.session import build_sessions
from agent.storage import (
    initialize_db,
    mark_run_status,
    set_product_gdoc_id,
)


def _seed_run(db_path: Path, run_id: str) -> None:
    mark_run_status(
        db_path,
        run_id=run_id,
        product_key="groww",
        iso_week="2026-W16",
        window_start="2026-04-13",
        window_end="2026-04-19",
        status="rendered",
    )


def test_docs_publish_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "pulse.db"
    initialize_db(db_path)
    run_id = "r1"
    _seed_run(db_path, run_id)
    state = tmp_path / "mcp.json"
    docs_session, _ = build_sessions(state)
    docs = DocsOps(docs_session, db_path)
    set_product_gdoc_id(db_path, "groww", "")
    req_path = tmp_path / "doc_requests.json"
    payload = {
        "requests": [{"kind": "heading1", "text": "x", "anchor": "pulse-groww-2026-W16"}],
    }
    req_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    first = docs.append_pulse_section(
        run_id=run_id,
        product="groww",
        iso_week="2026-W16",
        doc_requests_path=req_path,
    )
    second = docs.append_pulse_section(
        run_id=run_id,
        product="groww",
        iso_week="2026-W16",
        doc_requests_path=req_path,
    )
    assert first.skipped is False
    assert second.skipped is True
    assert first.heading_id == second.heading_id


def test_gmail_publish_header_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "pulse.db"
    initialize_db(db_path)
    run_id = "r2"
    _seed_run(db_path, run_id)
    state = tmp_path / "mcp.json"
    _, gmail_session = build_sessions(state)
    gmail = GmailOps(gmail_session, db_path)
    subject = tmp_path / "subject.txt"
    html = tmp_path / "email.html"
    text = tmp_path / "email.txt"
    subject.write_text("Subject", encoding="utf-8")
    html.write_text("<a href='{DOC_DEEP_LINK}'>link</a>", encoding="utf-8")
    text.write_text("link {DOC_DEEP_LINK}", encoding="utf-8")
    first = gmail.send_pulse_email(
        run_id=run_id,
        product="groww",
        to="a@example.com",
        subject_path=subject,
        email_html_path=html,
        email_text_path=text,
        deep_link="https://example.com",
        confirm_send=True,
    )
    second = gmail.send_pulse_email(
        run_id=run_id,
        product="groww",
        to="a@example.com",
        subject_path=subject,
        email_html_path=html,
        email_text_path=text,
        deep_link="https://example.com",
        confirm_send=True,
    )
    assert first.sent is True
    assert second.skipped is True
