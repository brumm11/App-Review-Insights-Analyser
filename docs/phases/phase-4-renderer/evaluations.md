# Phase 4 Evaluations

- `pulse render --run <run_id>` writes:
  - `data/artifacts/{run_id}/doc_requests.json`
  - `data/artifacts/{run_id}/email.html`
  - `data/artifacts/{run_id}/email.txt`
- Anchor `pulse-{product}-{iso_week}` is present in the doc heading request.
- Golden output tests assert deterministic JSON/HTML artifacts for fixed summary input.
- JSON Schema validation rejects malformed doc request structures.
