from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.mcp_client.session import MCPSession
from agent.storage import set_run_delivery


@dataclass(frozen=True)
class GmailPublishResult:
    message_id: str | None
    draft_id: str
    skipped: bool
    sent: bool


class GmailOps:
    def __init__(self, session: MCPSession, db_path: Path) -> None:
        self.session = session
        self.db_path = db_path

    def send_pulse_email(
        self,
        *,
        run_id: str,
        product: str,
        to: str,
        subject_path: Path,
        email_html_path: Path,
        email_text_path: Path,
        deep_link: str,
        confirm_send: bool,
        allow_resend: bool = False,
    ) -> GmailPublishResult:
        found = self.session.call("gmail.search_messages", run_id=run_id)
        if found.get("messages") and not allow_resend:
            msg = found["messages"][0]
            message_id = str(msg["id"])
            set_run_delivery(self.db_path, run_id=run_id, gmail_message_id=message_id)
            return GmailPublishResult(message_id=message_id, draft_id="", skipped=True, sent=True)

        subject = subject_path.read_text(encoding="utf-8").strip()
        html = email_html_path.read_text(encoding="utf-8").replace("{DOC_DEEP_LINK}", deep_link)
        text = email_text_path.read_text(encoding="utf-8").replace("{DOC_DEEP_LINK}", deep_link)
        draft = self.session.call(
            "gmail.create_draft",
            run_id=run_id,
            to=to,
            subject=subject,
            html=html,
            text=text,
            label=f"Pulse/{product}",
            headers={"X-Pulse-Run-Id": run_id},
        )
        draft_id = str(draft["id"])
        if not confirm_send:
            return GmailPublishResult(message_id=None, draft_id=draft_id, skipped=False, sent=False)

        sent = self.session.call("gmail.send_message", draft_id=draft_id)
        message_id = str(sent["id"])
        set_run_delivery(self.db_path, run_id=run_id, gmail_message_id=message_id)
        return GmailPublishResult(
            message_id=message_id,
            draft_id=draft_id,
            skipped=False,
            sent=True,
        )
