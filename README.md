# Weekly Product Review Pulse

Automated weekly review intelligence for fintech apps using public App Store / Play Store reviews.

## Quickstart

1. Install dependencies:
   - `uv sync --extra dev`
   - Optional (only for `local_bge` embeddings or `use_keybert=true`): `uv sync --extra nlp`
2. Initialize DB:
   - `uv run pulse init-db`
3. Explore CLI:
   - `uv run pulse --help`

## Re-run For A New Week

Run full pipeline for a product/week:
- `uv run pulse run --product groww --week 2026-W16 --weeks 10`

Run phases individually:
- `uv run pulse ingest --product groww --week 2026-W16 --weeks 10`
- `uv run pulse cluster --run <run_id>`
- `uv run pulse summarize --run <run_id>`
- `uv run pulse render --run <run_id>`
- `uv run pulse publish --run <run_id> --target both`

Export the source review CSV used for a run:
- `uv run pulse export-csv --run <run_id>`
- Optional custom output: `uv run pulse export-csv --run <run_id> --out data/artifacts/<run_id>/reviews.csv`

## Output Artifacts

For each run (`data/artifacts/<run_id>/`):
- `doc_requests.json` (Google Docs structured payload)
- `email.html` and `email.txt` (email draft content)
- `weekly_note.md` (scannable note guarded to <=250 words)
- `reviews.csv` (export via `export-csv`)

## Email Provider

- Default publish path uses Gmail MCP (`PULSE_EMAIL_PROVIDER=gmail`).
- For cloud-friendly sends without Google OAuth, use Resend:
  - `PULSE_EMAIL_PROVIDER=resend`
  - `PULSE_RESEND_API_KEY=<your_resend_api_key>`
  - `PULSE_RESEND_FROM=<verified_sender@yourdomain.com>` (or `onboarding@resend.dev` for quick testing)

## Theme Legend

- `negative`: average ratings in the theme are strongly low; users describe friction or failures.
- `mixed`: feedback is split; contains both pain points and positive mentions.
- `positive`: ratings and language indicate overall satisfaction.

Business constraints enforced:
- Hard cap of `5` themes in summary data.
- Weekly note renders top `3` themes, `3` user quotes, and `3` action ideas.
- Artifact PII validator blocks emails, phone numbers, and ID patterns before writing outputs.
