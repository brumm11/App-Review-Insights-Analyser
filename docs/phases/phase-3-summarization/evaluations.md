# Phase 3 Evaluations

- `pulse summarize --run <run_id>` writes `data/summaries/{run_id}.json`.
- Quote validator keeps only grounded verbatim quotes (normalized-substring check).
- Snapshot test verifies deterministic `PulseSummary` JSON with mock LLM client.
- Cost cap raises `PulseCostExceeded` when token budget is exceeded.
