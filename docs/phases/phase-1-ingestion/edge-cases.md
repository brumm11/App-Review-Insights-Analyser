# Phase 1 Edge Cases

- Reviews containing emojis are dropped.
- Reviews marked as non-English are dropped.
- Reviews with fewer than 4 words are dropped.
- PII (email, phone, Aadhaar-like numbers) is scrubbed before persistence.
- Missing App Store or Play Store identifiers should not crash ingestion.
