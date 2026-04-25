# Phase 2 Evaluations

- `pulse cluster --run <run_id>` creates/updates `review_embeddings` and `clusters`.
- Re-running the same command yields embedding cache hits from `data/cache/embeddings.json`.
- Cluster persistence is deterministic for a fixed run and fixed random seed.
