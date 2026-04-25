# Phase 0 Edge Cases

- Missing `.env` should still run with defaults.
- Invalid `PULSE_DB_PATH` parent directory should be auto-created on `init-db`.
- Running `init-db` repeatedly should be idempotent and not error.
- Non-existent `data/products.yaml` should not crash config loading.
