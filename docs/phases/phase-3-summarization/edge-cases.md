# Phase 3 Edge Cases

- Missing run or missing clusters should fail fast with actionable error text.
- Non-grounded quotes are dropped; a single repair attempt picks a grounded quote.
- PII is scrubbed before quote/theme text is emitted.
- LLM retry exhaustion surfaces the final exception (no silent fallback).
