from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from mcp_servers.services import DocsService, MCPStateStore


def _state_path() -> Path:
    raw = os.getenv("PULSE_MCP_MOCK_STATE_PATH", "data/mcp/mock_state.json")
    return Path(raw)


store = MCPStateStore(_state_path())
service = DocsService(store)
mcp = FastMCP("docs-mcp")


@mcp.tool(name="docs.search_documents")
def search_documents(title: str) -> dict[str, Any]:
    return service.search_documents(title)


@mcp.tool(name="docs.create_document")
def create_document(title: str) -> dict[str, Any]:
    return service.create_document(title)


@mcp.tool(name="docs.get_document")
def get_document(document_id: str) -> dict[str, Any]:
    return service.get_document(document_id)


@mcp.tool(name="docs.batch_update")
def batch_update(document_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
    return service.batch_update(document_id, requests)


if __name__ == "__main__":
    mcp.run()
