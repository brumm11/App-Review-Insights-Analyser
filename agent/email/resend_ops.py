from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from agent.storage import get_run_delivery, set_run_delivery


@dataclass(frozen=True)
class EmailPublishResult:
    message_id: str | None
    skipped: bool
    sent: bool


class ResendEmailOps:
    def __init__(self, db_path: Path, api_key: str, sender: str) -> None:
        self.db_path = db_path
        self.api_key = api_key
        self.sender = sender

    def send_pulse_email(
        self,
        *,
        run_id: str,
        to: str,
        subject_path: Path,
        email_html_path: Path,
        email_text_path: Path,
        deep_link: str,
        confirm_send: bool,
        allow_resend: bool = False,
    ) -> EmailPublishResult:
        _, existing_message_id = get_run_delivery(self.db_path, run_id)
        # Ignore mock Gmail IDs from earlier runs so Resend can send for real.
        if (
            not allow_resend
            and existing_message_id
            and not str(existing_message_id).startswith("msg_")
        ):
            return EmailPublishResult(message_id=existing_message_id, skipped=True, sent=True)
        if not confirm_send:
            return EmailPublishResult(message_id=None, skipped=False, sent=False)
        if not self.api_key.strip():
            raise RuntimeError("PULSE_RESEND_API_KEY is required when PULSE_EMAIL_PROVIDER=resend")

        subject = subject_path.read_text(encoding="utf-8").strip()
        html = email_html_path.read_text(encoding="utf-8").replace("{DOC_DEEP_LINK}", deep_link)
        text = email_text_path.read_text(encoding="utf-8").replace("{DOC_DEEP_LINK}", deep_link)
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": self.sender,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
                "headers": {"X-Pulse-Run-Id": run_id},
            },
            timeout=30.0,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Resend send failed: {response.status_code} {response.text}")
        payload = response.json()
        message_id = str(payload.get("id", ""))
        if not message_id:
            raise RuntimeError(f"Resend send succeeded without message id: {payload}")
        set_run_delivery(self.db_path, run_id=run_id, gmail_message_id=message_id)
        return EmailPublishResult(message_id=message_id, skipped=False, sent=True)
