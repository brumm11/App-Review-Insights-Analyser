Implementation Plan
Weekly Product Review Pulse — Phase-wise Implementation Plan

Derived from docs/architecture.md. The build is split into 8 incremental phases. Each phase produces something independently testable and, from Phase 1 onward, demoable via the CLI. Each phase has a dedicated evaluations.md (how we prove it works) and edge-cases.md (what we must survive) under docs/phases/<phase>/.


Guiding Principles

Vertical slices, not horizontal layers. Every phase ends with a runnable command that exercises the new capability end-to-end (mocked where needed).
MCP boundary is sacred. Only Phase 5 and Phase 6 introduce MCP calls. Everything before is pure local code.
Idempotency from day one. Deterministic run_id = sha1(product_key + iso_week) is wired in Phase 0 and reused by every later phase.
Golden fixtures. Canonical raw reviews and a canonical PulseSummary live in tests/fixtures/ starting Phase 1 so later phases can test without network or LLM calls.
Fail loud, degrade never silently. Every phase defines its failure modes and treats "partially succeeded" as a red test.

Phase Summary

Phase

Name

Duration (rough)

Key deliverable

Blocks

0

Foundations & Scaffolding

1–2 days

Repo, config, SQLite schema, CLI skeleton, CI

All

1

Review Ingestion

2–3 days

pulse ingest --product groww fills reviews table

2

2

Embeddings & Clustering

2–3 days

pulse cluster --run <id> produces cluster assignments

3

3

LLM Summarization

3–4 days

pulse summarize --run <id> produces validated PulseSummary JSON

4

4

Report & Email Rendering

2 days

Doc-tree + HTML email artifacts on disk

5, 6

5

Google Docs MCP — Append

3–4 days

Weekly section appended to running Google Doc, idempotent

6

6

Gmail MCP — Deliver

2–3 days

Stakeholder email sent with deep link, idempotent

7

7

Orchestration, Scheduling & Hardening

3 days

Weekly cron, OTel traces, cost caps, runbook

—

Total: ~18–24 working days for a single engineer to reach production.


Phase 0 — Foundations & Scaffolding

Goal: everything except business logic. Any later phase should only need to add files, not fight the skeleton.

Scope

Repo layout per architecture.md §11.
pyproject.toml with uv; pinned deps for pydantic, sqlite-vec, jinja2, pytest, ruff, mypy.
agent/config.py loading products.yaml via pydantic-settings; env via .env.
agent/storage.py — create all tables (products, reviews, review_embeddings, runs, themes) from architecture.md §5.
agent/__main__.py — Typer CLI with subcommands: ingest, cluster, summarize, render, publish, run.
run_id helper + Window helper (ISO-week math, IST-aware).
Dockerfile, docker-compose.yml (agent-only for now), GitHub Actions CI running lint + tests.
Structured logging (structlog) with run_id context var.
Exit criteria

uv run pulse --help prints all subcommands.
uv run pulse init-db creates a fresh SQLite file with all tables.
CI is green on an empty repo with two smoke tests.
Evaluations: docs/phases/phase-0-foundations/evaluations.md Edge cases: docs/phases/phase-0-foundations/edge-cases.md


Phase 1 — Review Ingestion

Goal: reliably pull and store 8–12 weeks of reviews for any supported product.

Scope

agent/ingestion/appstore.py — iTunes RSS customerreviews feed, paginated (1..10), country-configurable.
agent/ingestion/playstore.py — google-play-scraper wrapper with time-bounded pagination.
Unified RawReview pydantic model; stable id = sha1(source + external_id).
Dedup-upsert into reviews table.
Regex PII scrubber (emails, phone numbers, Aadhaar-like) applied to body before persistence.
Raw JSON snapshot written to data/raw/{product}/{run_id}.jsonl for audit.
CLI: pulse ingest --product groww --weeks 10.
Exit criteria

Fixture-replay test: feeding canned App Store + Play Store HTTP responses produces a deterministic reviews snapshot.
Running the real command for groww returns ≥ 200 reviews (smoke test; gated behind a live-network flag).
Re-running the same command within a minute is a no-op (0 inserts, some updates).
Evaluations: docs/phases/phase-1-ingestion/evaluations.md Edge cases: docs/phases/phase-1-ingestion/edge-cases.md


Phase 2 — Embeddings & Clustering

Goal: turn a pile of reviews into a small set of coherent clusters with representative members.

Scope

phases/phase-2-clustering (pulse_clustering package); the agent CLI maps env settings via agent/cluster_settings.py (see docs/rules.md for layout rules).
Language filter (keep en), length filter (≥ 20 chars).
Embedding provider interface with two implementations: OpenAI text-embedding-3-small and local bge-small-en-v1.5 (sentence-transformers).
Batch embed with on-disk cache keyed by sha1(text).
UMAP (n_components=15, metric=cosine), HDBSCAN (min_cluster_size=8, configurable).
Medoid selection per cluster (closest vector to centroid) + 2 extra picks with rating variance.
KeyBERT keyphrases per cluster (top 8).
Persist review_embeddings + a new clusters table (id, run_id, review_ids_json, keyphrases_json, medoid_review_id).
CLI: pulse cluster --run <id>.
Exit criteria

On the golden fixture (~400 reviews), HDBSCAN returns between 4 and 12 clusters; noise ratio < 35%.
Determinism: fixed random seeds → same cluster assignments across runs (byte-identical).
Embedding cache hit rate on a re-run is 100%.
Evaluations: docs/phases/phase-2-clustering/evaluations.md Edge cases: docs/phases/phase-2-clustering/edge-cases.md


Phase 3 — LLM Summarization

Goal: convert numeric clusters into named themes, verbatim quotes, and action ideas — with strong grounding guarantees.

Scope

agent/summarization.py:
Pydantic response models for every LLM call; Groq (OpenAI-compatible chat.completions + json_object) or Anthropic structured JSON.
label_theme(keyphrases, medoid_reviews) -> Theme.
select_quotes(cluster_reviews) -> list[Quote] with verbatim validator: every returned string must be a normalized-whitespace substring of some review.body; non-matching quotes dropped, re-prompted once.
generate_action_ideas(themes) -> list[ActionIdea].
summarize_pulse(...) -> PulseSummary (final assembly, ranks top 3 themes by review_count × |sentiment weight|).
LLM client wrapper with: retries, timeout, token/cost accounting (persisted to runs.metrics_json), per-run hard cap.
PII re-scrub before any LLM call.
CLI: pulse summarize --run <id> writes PulseSummary JSON to data/summaries/{run_id}.json.
Exit criteria

On the golden fixture, 3 themes are produced; every quote passes the verbatim validator.
Deterministic snapshot test using a mocked LLM (vcr.py-style) — PulseSummary JSON is byte-stable.
Cost cap triggers a controlled PulseCostExceeded error, not a silent truncation.
Evaluations: docs/phases/phase-3-summarization/evaluations.md Edge cases: docs/phases/phase-3-summarization/edge-cases.md


Phase 4 — Report & Email Rendering

Goal: deterministic conversion of PulseSummary into (a) a Google Docs batchUpdate request tree and (b) an HTML+text email body.

Scope

agent/renderer/docs_tree.py:
PulseSummary → list of batchUpdate requests matching the mapping table in architecture.md §3.1.
Anchor string pulse-{product}-{iso_week} embedded in the Heading 1 text.
Validates against templates/doc_section.schema.json.
agent/renderer/email_html.py:
Jinja2 template → HTML + plain-text; includes placeholder {DOC_DEEP_LINK} to be filled after Phase 5.
Subject: [Weekly Pulse] {Product} — {ISO week} — {Top theme}.
CLI: pulse render --run <id> writes data/artifacts/{run_id}/doc_requests.json + email.html + email.txt.
No MCP calls here — pure local rendering.
Exit criteria

Golden-image test: doc-request JSON and email HTML are byte-stable on fixture input.
Schema validator rejects malformed summaries (missing themes, wrong sentiment enum).
Evaluations: docs/phases/phase-4-renderer/evaluations.md Edge cases: docs/phases/phase-4-renderer/edge-cases.md


Phase 5 — Google Docs MCP — Append Report

Goal: append the rendered report as a new dated section to a running Google Doc, idempotently, using only MCP.

Scope

Choose and pin a Google Docs MCP server (community or official); add it to docker-compose.yml and infra/k8s/ manifests.
agent/mcp_client/session.py — connect/close both MCP sessions (stdio locally, SSE in prod); validate tool schemas at handshake.
agent/mcp_client/docs_ops.py:
resolve_document(product) -> docId — uses docs.search_documents / cache / docs.create_document on first run.
append_pulse_section(docId, doc_requests, anchor) -> {headingId, deep_link}:
docs.get_document → check anchor substring in body → skip if present.
docs.batch_update with the Phase-4 request tree.
docs.get_document again → locate the new heading by anchor, return its headingId.
Persist runs.gdoc_heading_id + gdoc_id.
CLI: pulse publish --run <id> --target docs.
Integration tests use a mock MCP server that speaks real JSON-RPC and records requests.
Exit criteria

Against the mock MCP server: first run creates a new section; second run is a no-op (anchor detected).
Against a real Google Doc in a test Workspace: the report renders correctly (headings, bullets, italic quotes, "What This Solves" table).
gdoc_heading_id is persisted and builds a working deep link.
Evaluations: docs/phases/phase-5-docs-mcp/evaluations.md Edge cases: docs/phases/phase-5-docs-mcp/edge-cases.md


Phase 6 — Gmail MCP — Deliver Email

Goal: send the stakeholder email with the Doc deep link, once per run, via the Gmail MCP server.

Scope

Pin a Gmail MCP server; add to compose/k8s.
agent/mcp_client/gmail_ops.py:
send_pulse_email(run_id, to, cc, bcc, html, text, deep_link):
gmail.search_messages for X-Pulse-Run-Id:{run_id} — if found, skip.
gmail.create_draft with custom header X-Pulse-Run-Id and label Pulse/{product}.
If CONFIRM_SEND=true, gmail.send_message(draftId); otherwise stop at draft.
Persist runs.gmail_message_id.
Email body gets the real {DOC_DEEP_LINK} from Phase 5 substituted in.
CLI: pulse publish --run <id> --target gmail and a combined --target both.
Exit criteria

Mock MCP integration test: first run sends (draft→send); second run detects header and skips; runs.gmail_message_id populated exactly once.
Dry-run default: without CONFIRM_SEND, a draft exists but no send occurs.
Real Workspace smoke test: email arrives in a test inbox, deep link jumps to the new heading in the Doc.
Evaluations: docs/phases/phase-6-gmail-mcp/evaluations.md Edge cases: docs/phases/phase-6-gmail-mcp/edge-cases.md


Phase 7 — Orchestration, Scheduling & Hardening

Goal: the whole pipeline runs weekly, unattended, with observability, cost controls, and a written runbook.

Scope

agent/orchestrator.py — top-level pulse run --product groww --weeks 10 chaining all phases with resumable checkpoints driven by runs.status.
Scheduling: GitHub Actions workflow .github/workflows/weekly-pulse.yml (cron Mon 07:00 IST) running once per product in a matrix.
Observability: OpenTelemetry spans around every module and every MCP tool call; run_id as a span attribute; export to OTLP.
Metrics: pulse.reviews_ingested, pulse.clusters_formed, pulse.llm_tokens, pulse.llm_cost_usd, pulse.mcp_call_latency{tool}, pulse.publish_status.
Alerts: ingestion drop > 50% WoW; avg rating delta > 1.0; LLM schema-validation failure rate > 2%; MCP call error rate > 1%.
Runbook: docs/runbook.md covering: "email not sent", "duplicate section in Doc", "ingestion empty", "LLM cost spike", "MCP server crash", "token revoked".
Backfill CLI: pulse run --product groww --week 2026-W15 re-runs any past week safely.
Exit criteria

Dry-run weekly workflow passes in CI using mocked MCP servers.
On a staging Workspace, one full unattended run end-to-end in < 5 minutes; total LLM cost tracked in runs.metrics_json and under the per-run cap.
Kill the MCP server mid-run → orchestrator retries; second run completes and is still idempotent.
Evaluations: docs/phases/phase-7-orchestration/evaluations.md Edge cases: docs/phases/phase-7-orchestration/edge-cases.md

