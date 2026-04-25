# Phase 1 Evaluations

- `pulse ingest --product groww --weeks 10` writes rows into `reviews` and updates `runs.status` to `ingested`.
- Fixture replay test verifies deterministic filtered output and JSONL snapshot.
- Re-running same week updates existing rows (no duplicate inserts).
