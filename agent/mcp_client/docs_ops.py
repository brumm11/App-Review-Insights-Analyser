from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from agent.mcp_client.session import MCPSession
from agent.renderer.docs_tree import build_anchor
from agent.storage import get_product_gdoc_id, set_product_gdoc_id, set_run_delivery


@dataclass(frozen=True)
class DocsPublishResult:
    doc_id: str
    heading_id: str
    deep_link: str
    skipped: bool


class DocsOps:
    def __init__(self, session: MCPSession, db_path: Path) -> None:
        self.session = session
        self.db_path = db_path

    def resolve_document(self, product: str) -> str:
        env_specific = os.getenv(f"PULSE_GDOC_ID_{product.upper()}")
        env_default = os.getenv("PULSE_GDOC_ID")
        env_doc_id = env_specific or env_default
        if env_doc_id:
            set_product_gdoc_id(self.db_path, product, env_doc_id)
            return env_doc_id
        cached = get_product_gdoc_id(self.db_path, product)
        if cached:
            return cached
        title = f"Weekly Review Pulse — {product.title()}"
        search = self.session.call("docs.search_documents", title=title)
        documents = search.get("documents", [])
        if documents:
            doc_id = str(documents[0]["id"])
        else:
            created = self.session.call("docs.create_document", title=title)
            doc_id = str(created["id"])
        set_product_gdoc_id(self.db_path, product, doc_id)
        return doc_id

    def append_pulse_section(
        self,
        *,
        run_id: str,
        product: str,
        iso_week: str,
        doc_requests_path: Path,
    ) -> DocsPublishResult:
        doc_id = self.resolve_document(product)
        anchor = build_anchor(product, iso_week)
        current = self.session.call("docs.get_document", document_id=doc_id)
        content = str(current.get("content", ""))
        headings = dict(current.get("headings", {}))
        if anchor in content and anchor in headings:
            heading_id = str(headings[anchor])
            deep_link = self._build_deep_link(doc_id, heading_id)
            set_run_delivery(self.db_path, run_id=run_id, gdoc_heading_id=heading_id)
            return DocsPublishResult(
                doc_id=doc_id,
                heading_id=heading_id,
                deep_link=deep_link,
                skipped=True,
            )

        payload = json.loads(doc_requests_path.read_text(encoding="utf-8"))
        requests = payload["requests"]
        self.session.call("docs.batch_update", document_id=doc_id, requests=requests)
        refreshed = self.session.call("docs.get_document", document_id=doc_id)
        heading_id = str(refreshed.get("headings", {}).get(anchor, ""))
        if heading_id:
            deep_link = self._build_deep_link(doc_id, heading_id)
            set_run_delivery(self.db_path, run_id=run_id, gdoc_heading_id=heading_id)
        else:
            deep_link = f"https://docs.google.com/document/d/{doc_id}/edit"
            set_run_delivery(self.db_path, run_id=run_id, gdoc_heading_id="document")
            heading_id = "document"
        return DocsPublishResult(
            doc_id=doc_id,
            heading_id=heading_id,
            deep_link=deep_link,
            skipped=False,
        )

    @staticmethod
    def _build_deep_link(doc_id: str, heading_id: str) -> str:
        return f"https://docs.google.com/document/d/{doc_id}/edit#heading={heading_id}"
