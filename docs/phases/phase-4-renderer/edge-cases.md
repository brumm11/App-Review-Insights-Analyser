# Phase 4 Edge Cases

- Missing summary JSON for run should fail before writing artifacts.
- Invalid doc request shapes fail JSON Schema validation.
- Empty themes still render a valid doc/email artifact structure.
- Output paths are created if absent and safely overwritten on rerun.
