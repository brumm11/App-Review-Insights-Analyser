from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from mcp_servers.services import GmailService, MCPStateStore


def _state_path() -> Path:
    raw = os.getenv("PULSE_MCP_MOCK_STATE_PATH", "data/mcp/mock_state.json")
    return Path(raw)


store = MCPStateStore(_state_path())
service = GmailService(store)
mcp = FastMCP("gmail-mcp")


@mcp.tool(name="gmail.search_messages")
def search_messages(run_id: str) -> dict[str, Any]:
    return service.search_messages(run_id)


@mcp.tool(name="gmail.create_draft")
def create_draft(
    run_id: str,
    to: str,
    subject: str,
    html: str,
    text: str,
    label: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    return service.create_draft(run_id, to, subject, html, text, label, headers)


@mcp.tool(name="gmail.send_message")
def send_message(draft_id: str) -> dict[str, Any]:
    return service.send_message(draft_id)


@mcp.tool(name="gmail.get_message")
def get_message(message_id: str) -> dict[str, Any]:
    return service.get_message(message_id)


if __name__ == "__main__":
    mcp.run()
