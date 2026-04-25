# Phase 2 Edge Cases

- Empty or missing run window should fail fast with a clear error.
- If no reviews pass language/length filter, no clusters are written.
- Existing cluster rows for the run are replaced atomically on rerun.
- Cache file corruption should be handled by regenerating the missing embeddings.
