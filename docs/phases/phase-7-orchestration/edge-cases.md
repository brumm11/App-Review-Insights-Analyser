# Phase 7 Edge Cases

- Partial failure can be resumed by re-running same week (idempotent publish paths).
- Missing product IDs or artifacts fail at the corresponding stage with clear errors.
- Publish target `both` should maintain docs-first then gmail ordering.
