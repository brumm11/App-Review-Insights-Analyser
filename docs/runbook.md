# Weekly Pulse Runbook

## Email not sent
- Verify `PULSE_CONFIRM_SEND=true`.
- Run `pulse publish --run <id> --target gmail`.
- Check `runs.gmail_message_id` for persistence.

## Duplicate section in Doc
- Confirm anchor format `pulse-{product}-{iso_week}`.
- Re-run publish docs; idempotency should skip when anchor exists.

## Ingestion empty
- Confirm `appstore_id` and `play_package` in `data/products.yaml`.
- Re-run with explicit weeks: `pulse ingest --product <key> --weeks 10`.

## LLM cost spike
- Lower `PULSE_LLM_TOKEN_CAP_PER_RUN`.
- Inspect `runs.metrics_json` for `llm_tokens` and `llm_cost_usd`.

## MCP server crash
- Use mock transport fallback (`PULSE_DOCS_MCP_TRANSPORT=mock`, `PULSE_GMAIL_MCP_TRANSPORT=mock`) for local verification.
- Retry `pulse publish`.

## Token revoked
- Re-authenticate within the MCP server process.
- Retry publish for same run id; idempotency keeps operations safe.
