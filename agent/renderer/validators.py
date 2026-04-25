from __future__ import annotations

import re

from agent.ingestion.filters import AADHAAR_RE, EMAIL_RE, PHONE_RE

ID_RE = re.compile(
    r"\b(?:user\s*id|account\s*id|customer\s*id|pan|aadhaar)\s*[:#-]?\s*[A-Za-z0-9_-]{6,}\b",
    re.I,
)


def assert_no_pii(text: str, *, artifact_name: str) -> None:
    checks = {
        "email": EMAIL_RE,
        "phone": PHONE_RE,
        "id": AADHAAR_RE,
        "named-id": ID_RE,
    }
    for label, pattern in checks.items():
        if pattern.search(text):
            raise ValueError(f"PII validation failed ({label}) in artifact: {artifact_name}")
