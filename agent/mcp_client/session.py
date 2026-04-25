from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from mcp_servers.services import DocsService, GmailService, MCPStateStore


class MCPTransport(Protocol):
    def call_tool(self, server: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class MCPSession:
    transport: MCPTransport
    server: str

    def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        return self.transport.call_tool(self.server, tool, arguments)


class MockMCPTransport:
    """File-backed MCP mock transport for local development/tests."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self.state = {"docs": {"documents": {}}, "gmail": {"messages": [], "drafts": []}}
            self._save()

    def call_tool(self, server: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if server == "docs":
            result = self._docs_tool(tool, arguments)
        elif server == "gmail":
            result = self._gmail_tool(tool, arguments)
        else:
            raise ValueError(f"Unknown server={server}")
        self._save()
        return result

    def _docs_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        docs = self.state["docs"]["documents"]
        if tool == "docs.search_documents":
            title = str(arguments["title"])
            for doc_id, doc in docs.items():
                if doc["title"] == title:
                    return {"documents": [{"id": doc_id, "title": title}]}
            return {"documents": []}
        if tool == "docs.create_document":
            title = str(arguments["title"])
            doc_id = f"doc_{uuid4().hex[:10]}"
            docs[doc_id] = {"title": title, "content": "", "headings": {}}
            return {"id": doc_id}
        if tool == "docs.get_document":
            doc_id = str(arguments["document_id"])
            doc = docs[doc_id]
            return {
                "id": doc_id,
                "title": doc["title"],
                "content": doc["content"],
                "headings": doc["headings"],
            }
        if tool == "docs.batch_update":
            doc_id = str(arguments["document_id"])
            requests = arguments["requests"]
            doc = docs[doc_id]
            for req in requests:
                if req.get("kind") == "heading1" and req.get("anchor"):
                    heading_id = f"h_{uuid4().hex[:8]}"
                    doc["headings"][req["anchor"]] = heading_id
                doc["content"] += json.dumps(req, ensure_ascii=False) + "\n"
            return {"ok": True}
        raise ValueError(f"Unsupported docs tool={tool}")

    def _gmail_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        gmail = self.state["gmail"]
        if tool == "gmail.search_messages":
            run_id = str(arguments.get("run_id") or "")
            matches = [m for m in gmail["messages"] if m.get("run_id") == run_id]
            return {"messages": matches}
        if tool == "gmail.create_draft":
            draft_id = f"draft_{uuid4().hex[:10]}"
            draft = {"id": draft_id, **arguments}
            gmail["drafts"].append(draft)
            return {"id": draft_id}
        if tool == "gmail.send_message":
            draft_id = str(arguments["draft_id"])
            selected_draft: dict[str, Any] | None = None
            for item in gmail["drafts"]:
                if item["id"] == draft_id:
                    selected_draft = item
                    break
            if selected_draft is None:
                raise ValueError(f"Unknown draft_id={draft_id}")
            message_id = f"msg_{uuid4().hex[:10]}"
            message = {"id": message_id, "thread_id": f"thr_{uuid4().hex[:8]}", **selected_draft}
            gmail["messages"].append(message)
            return {"id": message_id, "thread_id": message["thread_id"]}
        if tool == "gmail.get_message":
            message_id = str(arguments["message_id"])
            selected_message: dict[str, Any] | None = None
            for item in gmail["messages"]:
                if item["id"] == message_id:
                    selected_message = item
                    break
            if selected_message is None:
                raise ValueError(f"Unknown message_id={message_id}")
            return selected_message
        raise ValueError(f"Unsupported gmail tool={tool}")

    def _save(self) -> None:
        payload = json.dumps(self.state, ensure_ascii=False, indent=2)
        self.state_path.write_text(payload, encoding="utf-8")


def build_sessions(mock_state_path: Path) -> tuple[MCPSession, MCPSession]:
    transport = MockMCPTransport(mock_state_path)
    return (
        MCPSession(transport=transport, server="docs"),
        MCPSession(transport=transport, server="gmail"),
    )


class FastMCPInProcessTransport:
    """In-process bridge to FastMCP service implementations."""

    def __init__(self, state_path: Path) -> None:
        store = MCPStateStore(state_path)
        self.docs = DocsService(store)
        self.gmail = GmailService(store)

    def call_tool(self, server: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if server == "docs":
            if tool == "docs.search_documents":
                return self.docs.search_documents(str(arguments["title"]))
            if tool == "docs.create_document":
                return self.docs.create_document(str(arguments["title"]))
            if tool == "docs.get_document":
                return self.docs.get_document(str(arguments["document_id"]))
            if tool == "docs.batch_update":
                requests = list(arguments["requests"])
                return self.docs.batch_update(str(arguments["document_id"]), requests)
        if server == "gmail":
            if tool == "gmail.search_messages":
                return self.gmail.search_messages(str(arguments["run_id"]))
            if tool == "gmail.create_draft":
                return self.gmail.create_draft(
                    run_id=str(arguments["run_id"]),
                    to=str(arguments["to"]),
                    subject=str(arguments["subject"]),
                    html=str(arguments["html"]),
                    text=str(arguments["text"]),
                    label=str(arguments["label"]),
                    headers=dict(arguments["headers"]),
                )
            if tool == "gmail.send_message":
                return self.gmail.send_message(str(arguments["draft_id"]))
            if tool == "gmail.get_message":
                return self.gmail.get_message(str(arguments["message_id"]))
        raise ValueError(f"Unsupported server/tool: {server}/{tool}")


def build_sessions_with_transport(
    *,
    docs_transport: str,
    gmail_transport: str,
    state_path: Path,
) -> tuple[MCPSession, MCPSession]:
    if docs_transport == "fastmcp" or gmail_transport == "fastmcp":
        transport: MCPTransport = FastMCPInProcessTransport(state_path)
    else:
        transport = MockMCPTransport(state_path)
    return (
        MCPSession(transport=transport, server="docs"),
        MCPSession(transport=transport, server="gmail"),
    )
