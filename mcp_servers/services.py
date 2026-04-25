from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4


class MCPStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.state = {"docs": {"documents": {}}, "gmail": {"messages": [], "drafts": []}}
            self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")


class DocsService:
    def __init__(self, store: MCPStateStore) -> None:
        self.store = store

    def search_documents(self, title: str) -> dict[str, Any]:
        docs = self.store.state["docs"]["documents"]
        for doc_id, doc in docs.items():
            if doc["title"] == title:
                return {"documents": [{"id": doc_id, "title": title}]}
        return {"documents": []}

    def create_document(self, title: str) -> dict[str, Any]:
        docs = self.store.state["docs"]["documents"]
        doc_id = f"doc_{uuid4().hex[:10]}"
        docs[doc_id] = {"title": title, "content": "", "headings": {}}
        self.store.save()
        return {"id": doc_id}

    def get_document(self, document_id: str) -> dict[str, Any]:
        docs = self.store.state["docs"]["documents"]
        doc = docs[document_id]
        return {
            "id": document_id,
            "title": doc["title"],
            "content": doc["content"],
            "headings": doc["headings"],
        }

    def batch_update(self, document_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
        docs = self.store.state["docs"]["documents"]
        doc = docs[document_id]
        for req in requests:
            if req.get("kind") == "heading1" and req.get("anchor"):
                heading_id = f"h_{uuid4().hex[:8]}"
                doc["headings"][req["anchor"]] = heading_id
            doc["content"] += json.dumps(req, ensure_ascii=False) + "\n"
        self.store.save()
        return {"ok": True}


class GmailService:
    def __init__(self, store: MCPStateStore) -> None:
        self.store = store

    def search_messages(self, run_id: str) -> dict[str, Any]:
        gmail = self.store.state["gmail"]
        matches = [m for m in gmail["messages"] if m.get("run_id") == run_id]
        return {"messages": matches}

    def create_draft(
        self,
        run_id: str,
        to: str,
        subject: str,
        html: str,
        text: str,
        label: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        gmail = self.store.state["gmail"]
        draft_id = f"draft_{uuid4().hex[:10]}"
        draft = {
            "id": draft_id,
            "run_id": run_id,
            "to": to,
            "subject": subject,
            "html": html,
            "text": text,
            "label": label,
            "headers": headers,
        }
        gmail["drafts"].append(draft)
        self.store.save()
        return {"id": draft_id}

    def send_message(self, draft_id: str) -> dict[str, Any]:
        gmail = self.store.state["gmail"]
        draft = next((d for d in gmail["drafts"] if d["id"] == draft_id), None)
        if draft is None:
            raise ValueError(f"Unknown draft_id={draft_id}")
        message_id = f"msg_{uuid4().hex[:10]}"
        thread_id = f"thr_{uuid4().hex[:8]}"
        message = {"id": message_id, "thread_id": thread_id, **draft}
        gmail["messages"].append(message)
        self.store.save()
        return {"id": message_id, "thread_id": thread_id}

    def get_message(self, message_id: str) -> dict[str, Any]:
        gmail = self.store.state["gmail"]
        message = next((m for m in gmail["messages"] if m["id"] == message_id), None)
        if message is None:
            raise ValueError(f"Unknown message_id={message_id}")
        return message
