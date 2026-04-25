# Phase 6 Evaluations

- `pulse publish --run <id> --target gmail` creates draft with `X-Pulse-Run-Id`.
- If `PULSE_CONFIRM_SEND=true`, draft is sent and `runs.gmail_message_id` is stored.
- Re-run checks existing message by run id and skips duplicate sends.
