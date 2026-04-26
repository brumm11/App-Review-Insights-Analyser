from __future__ import annotations

import base64
import json
import os
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from uuid import uuid4

ALL_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


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
        payload = json.dumps(self.state, ensure_ascii=False, indent=2)
        self.path.write_text(payload, encoding="utf-8")


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


class RealGoogleDocsService:
    def __init__(self) -> None:
        credentials = _load_google_credentials(
            scopes=[
                "https://www.googleapis.com/auth/documents",
                "https://www.googleapis.com/auth/drive.metadata.readonly",
            ]
        )
        from googleapiclient.discovery import build

        self.docs = build("docs", "v1", credentials=credentials)
        self.drive = build("drive", "v3", credentials=credentials)

    def search_documents(self, title: str) -> dict[str, Any]:
        escaped_title = title.replace("'", "\\'")
        query = (
            "mimeType='application/vnd.google-apps.document' "
            f"and name='{escaped_title}' and trashed=false"
        )
        result = self.drive.files().list(q=query, fields="files(id,name)", pageSize=5).execute()
        files = result.get("files", [])
        documents = [{"id": str(item["id"]), "title": str(item["name"])} for item in files]
        return {"documents": documents}

    def create_document(self, title: str) -> dict[str, Any]:
        created = self.docs.documents().create(body={"title": title}).execute()
        return {"id": str(created["documentId"])}

    def get_document(self, document_id: str) -> dict[str, Any]:
        payload = self.docs.documents().get(documentId=document_id).execute()
        body = payload.get("body", {}).get("content", [])
        text_parts: list[str] = []
        headings: dict[str, str] = {}
        for block in body:
            paragraph = block.get("paragraph")
            if not paragraph:
                continue
            line = "".join(
                str(el.get("textRun", {}).get("content", ""))
                for el in paragraph.get("elements", [])
            )
            if line:
                text_parts.append(line)
            match = re.search(r"pulse-[a-z0-9_-]+-\d{4}-W\d{2}", line)
            if match:
                style = paragraph.get("paragraphStyle", {})
                heading_id = str(style.get("headingId") or "")
                if heading_id:
                    headings[match.group(0)] = heading_id
        return {
            "id": document_id,
            "title": str(payload.get("title", "")),
            "content": "".join(text_parts),
            "headings": headings,
        }

    def batch_update(self, document_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
        document = self.docs.documents().get(documentId=document_id).execute()
        body = document.get("body", {}).get("content", [])
        end_index = int(body[-1].get("endIndex", 1)) if body else 1
        index = max(1, end_index - 1)
        api_requests: list[dict[str, Any]] = []

        def insert_line(text: str, style: str | None = None, bullet: bool = False) -> None:
            nonlocal index
            line = text.rstrip() + "\n"
            start = index
            end = index + len(line)
            api_requests.append({"insertText": {"location": {"index": start}, "text": line}})
            if style:
                api_requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": {"startIndex": start, "endIndex": end},
                            "paragraphStyle": {"namedStyleType": style},
                            "fields": "namedStyleType",
                        }
                    }
                )
            if bullet:
                api_requests.append(
                    {
                        "createParagraphBullets": {
                            "range": {"startIndex": start, "endIndex": end},
                            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                        }
                    }
                )
            index = end

        for item in requests:
            kind = str(item.get("kind", ""))
            if kind == "heading1":
                insert_line(str(item.get("text", "")), style="HEADING_1")
            elif kind == "heading2":
                insert_line(str(item.get("text", "")), style="HEADING_2")
            elif kind == "paragraph":
                insert_line(str(item.get("text", "")))
            elif kind in {"bullets", "quotes"}:
                values = item.get("items", [])
                if isinstance(values, list):
                    for line in values:
                        insert_line(str(line), bullet=(kind == "bullets"))
            elif kind == "separator":
                insert_line("---")
            elif kind == "stats":
                values = item.get("items", {})
                if isinstance(values, dict):
                    for key, value in values.items():
                        insert_line(f"{key}: {value}")
            elif kind == "table":
                rows = item.get("rows", [])
                if isinstance(rows, list):
                    insert_line(str(item.get("title", "What This Solves")), style="HEADING_2")
                    for row in rows:
                        if isinstance(row, list) and len(row) >= 2:
                            insert_line(f"{row[0]}: {row[1]}")
            else:
                insert_line(json.dumps(item, ensure_ascii=False))

        if api_requests:
            self.docs.documents().batchUpdate(
                documentId=document_id,
                body={"requests": api_requests},
            ).execute()
        return {"ok": True}


class RealGoogleGmailService:
    def __init__(self) -> None:
        credentials = _load_google_credentials(
            scopes=[
                "https://www.googleapis.com/auth/gmail.compose",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.readonly",
            ]
        )
        from googleapiclient.discovery import build

        self.gmail = build("gmail", "v1", credentials=credentials)

    def search_messages(self, run_id: str) -> dict[str, Any]:
        response = self.gmail.users().messages().list(
            userId="me",
            q=f"X-Pulse-Run-Id:{run_id}",
        ).execute()
        messages = response.get("messages", [])
        return {"messages": [{"id": str(item["id"])} for item in messages]}

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
        _ = label
        message = MIMEMultipart("alternative")
        message["To"] = to
        message["Subject"] = subject
        message["X-Pulse-Run-Id"] = run_id
        for key, value in headers.items():
            if key.lower() != "x-pulse-run-id":
                message[key] = value
        message.attach(MIMEText(text, "plain", "utf-8"))
        message.attach(MIMEText(html, "html", "utf-8"))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        draft = self.gmail.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()
        return {"id": str(draft["id"])}

    def send_message(self, draft_id: str) -> dict[str, Any]:
        sent = self.gmail.users().drafts().send(userId="me", body={"id": draft_id}).execute()
        return {"id": str(sent["id"]), "thread_id": str(sent.get("threadId", ""))}

    def get_message(self, message_id: str) -> dict[str, Any]:
        message = self.gmail.users().messages().get(userId="me", id=message_id).execute()
        return {"id": str(message.get("id", "")), "thread_id": str(message.get("threadId", ""))}


def _load_google_credentials(*, scopes: list[str]) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_json_inline = os.getenv("PULSE_GOOGLE_OAUTH_CLIENT_JSON", "").strip()
    token_json_inline = os.getenv("PULSE_GOOGLE_OAUTH_TOKEN_JSON", "").strip()
    client_json_path = Path(
        os.getenv("PULSE_GOOGLE_OAUTH_CLIENT_JSON_PATH", "credentials/google_oauth_client.json")
    )
    token_path = Path(
        os.getenv("PULSE_GOOGLE_OAUTH_TOKEN_PATH", "credentials/google_oauth_token.json")
    )
    requested_scopes = sorted(set(scopes) | set(ALL_GOOGLE_SCOPES))
    creds: Credentials | None = None
    if token_json_inline:
        token_info = json.loads(token_json_inline)
        creds = Credentials.from_authorized_user_info(token_info, scopes=requested_scopes)
    elif token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes=requested_scopes)
        current_scopes = set(creds.scopes or [])
        if not set(requested_scopes).issubset(current_scopes):
            creds = None
    if creds is None or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if client_json_inline:
                client_config = json.loads(client_json_inline)
                flow = InstalledAppFlow.from_client_config(
                    client_config,
                    scopes=requested_scopes,
                )
                creds = flow.run_local_server(port=0)
            elif client_json_path.exists():
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(client_json_path),
                    scopes=requested_scopes,
                )
                creds = flow.run_local_server(port=0)
            else:
                raise RuntimeError(
                    "Missing Google OAuth credentials. Set either "
                    "PULSE_GOOGLE_OAUTH_CLIENT_JSON/PULSE_GOOGLE_OAUTH_TOKEN_JSON secrets "
                    "or provide files at configured *_PATH locations."
                )
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def build_docs_service(store: MCPStateStore) -> Any:
    if os.getenv("PULSE_USE_REAL_GOOGLE", "false").lower() == "true":
        return RealGoogleDocsService()
    return DocsService(store)


def build_gmail_service(store: MCPStateStore) -> Any:
    if os.getenv("PULSE_USE_REAL_GOOGLE", "false").lower() == "true":
        return RealGoogleGmailService()
    return GmailService(store)
