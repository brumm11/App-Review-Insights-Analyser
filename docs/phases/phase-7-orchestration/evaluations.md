# Phase 7 Evaluations

- `pulse run --product groww --week 2026-W16 --weeks 10` chains ingest→cluster→summarize→render→publish.
- Pipeline returns deterministic run id from product/week.
- Orchestrator unit test verifies step order and completion semantics.
