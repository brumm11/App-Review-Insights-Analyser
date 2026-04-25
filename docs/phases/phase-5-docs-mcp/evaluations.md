# Phase 5 Evaluations

- `pulse publish --run <id> --target docs` resolves/creates product doc via MCP.
- First run appends section and stores `runs.gdoc_heading_id`.
- Re-run for same run id detects anchor and skips duplicate append.
