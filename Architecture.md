Weekly Product Review Pulse — Detailed Architecture

An AI Agent that ingests App Store / Play Store reviews for a selected fintech product (INDMoney, Groww, PowerUp Money, Wealth Monitor, Kuvera), uses LLMs to detect themes and produce a one-page weekly insight report, and then delivers that report to stakeholders using MCP (Model Context Protocol) for Google Workspace — specifically the Google Docs MCP server (to append the report to a running Google Doc) and the Gmail MCP server (to send the stakeholder email).


1. Goals & Non-Goals

Goals

Automated weekly pulse: zero-touch generation of a 1-page product review report every week.
MCP-based delivery: the agent talks to Google Docs and Gmail only through MCP servers. No direct Google API calls from the agent code.
Google Doc as the system of record: every weekly report is appended as a dated section to a single running Google Doc per product (e.g., "Weekly Review Pulse — Groww"), so history is preserved and linkable.
Email with a link to the doc: the Gmail MCP is used to send a short email that links directly to the newly added section in the Google Doc.
Re-runnable & idempotent: re-running the same ISO week does not create duplicate Doc sections or duplicate emails.
Auditable: every run records which MCP tool calls were made, with what arguments, and what Google resource IDs (docId, messageId) resulted.
Non-Goals

Building a generic Google Workspace integration — we use only the MCP tools we need (append to Doc, send Gmail).
Real-time streaming analytics (this is a weekly batch).
A BI dashboard — the Google Doc is the dashboard.
Social media ingestion (Twitter/Reddit) — out of scope.
3. MCP Integration (the Google Workspace surface)

The agent acts as an MCP Host and Client. It connects to two MCP servers, each wrapping a Google Workspace product.

3.1 Google Docs MCP Server

Purpose: append the rendered weekly pulse as a new dated section to a running Google Doc (one doc per product).

Transport: stdio (local dev) or SSE (containerised).

Tools used by the agent (typical surface exposed by a Google Docs MCP server; exact tool names will match the chosen server implementation):

MCP tool

Agent usage

docs.search_documents

Look up the per-product Doc by title if the docId isn't cached

docs.get_document

Read the current structure to find the end-of-body index for appending

docs.create_document

First-run only — create "Weekly Review Pulse — {Product}" if it doesn't exist

docs.batch_update

Primary tool. Append a new H1 section (YYYY-WW — <window>), the report body, and a horizontal rule. Also used to insert a bookmark/heading we can deep-link to.

docs.get_document (again)

Retrieve the new heading's headingId so we can build a deep-link URL for the email

Appending strategy (idempotent):

Compute section_anchor = "pulse-{product}-{iso_week}" (e.g., pulse-groww-2026-W16).
Call docs.get_document and search its body for that anchor string.
If found → skip (run already appended; re-render email only if requested).
If not found → docs.batch_update with a single batched request that:
Inserts a page break at endIndex - 1.
Inserts a Heading 1 containing the anchor text (e.g., "Weekly Pulse — Groww — 2026-W16 (Apr 13 → Apr 19)").
Inserts the rendered report content (converted from Markdown to Docs batchUpdate requests: headings, bullets, bold/italic, quotes as indented text).
Inserts an insertSectionBreak / horizontal rule at the end.
Re-read the doc and capture the new heading's headingId; persist {run_id → { docId, headingId }} in local state.
Build the shareable link: https://docs.google.com/document/d/{docId}/edit#heading={headingId}.
Markdown → Google Docs conversion: the agent renders the pulse to a structured in-memory tree (not raw Markdown), then maps that tree to the batchUpdate request shape. This avoids Markdown-to-Docs ambiguity. The mapping is:

Pulse element

Docs request

Section title

insertText + updateParagraphStyle: HEADING_1

Theme title

HEADING_2

Bullet (theme detail / action idea)

insertText + createParagraphBullets: BULLET_DISC_CIRCLE_SQUARE

Verbatim quote

insertText + updateParagraphStyle: indentFirstLine + italic

"What this solves" table

insertTable (2 columns: Audience, Value)

3.2 Gmail MCP Server

Purpose: draft and send the stakeholder email with a deep link to the Google Doc section just created.

Tools used by the agent:

MCP tool

Agent usage

gmail.create_draft

Build the email from the templated body + deep link; always called first (dry-run friendly)

gmail.send_message

Send the draft. Gated behind CONFIRM_SEND=true to avoid accidental sends in dev

gmail.list_labels / gmail.modify_labels

Tag outgoing message with a Pulse/<product> label for auditability

gmail.get_message

Post-send, fetch messageId and threadId to persist in run metadata

Email content (HTML + plain-text multipart):

Subject: [Weekly Pulse] {Product} — {ISO week} — {Top theme}
Body (short): 3–5 bullet "top themes" teaser + a prominent "Read full report →" link pointing at the Google Doc #heading= deep link from §3.1.
Footer: run_id, ingestion window, "Generated by Pulse Agent", unsubscribe/opt-out note.
Idempotency: the agent includes a custom header X-Pulse-Run-Id: {run_id} in gmail.create_draft. Before sending, it uses gmail.search_messages (query: from:me X-Pulse-Run-Id:{run_id}) to confirm no prior send exists; if one does, the new draft is discarded.

3.3 Authentication

Authentication is handled inside each MCP server, not in the agent. The agent only needs to know how to reach the server (stdio command or SSE URL). Typical setups:

OAuth user flow: the MCP server stores refreshable OAuth tokens locally (scopes: https://www.googleapis.com/auth/documents, https://www.googleapis.com/auth/gmail.compose, .../gmail.send, .../gmail.labels).
Service account with domain-wide delegation (for orgs): the MCP server impersonates a designated sender mailbox and a shared Docs owner.
The agent's config only stores: docs_mcp_command / docs_mcp_url, gmail_mcp_command / gmail_mcp_url, and the target Google Doc IDs per product (or a title pattern to look them up).

4. Internal Agent Pipeline (non-MCP)

Everything in this section is local code inside the agent; it is deliberately not an MCP server because the MCP boundary is reserved for Google Workspace per the problem statement.

4.1 Modules

Module

Responsibility

Key libs

ingestion

Pull App Store (iTunes RSS) + Play Store reviews for the product over 8–12 weeks; dedupe by stable id; PII-scrub (emails/phones)

google-play-scraper, itunes-app-scraper, httpx

storage

Local persistence of raw reviews, embeddings, clusters, runs

SQLite + sqlite-vec (or DuckDB + Parquet)

clustering

Embed → UMAP → HDBSCAN → medoid selection → keyphrase extraction (KeyBERT)

sentence-transformers, umap-learn, hdbscan, keybert

summarization

LLM calls to label each cluster as a theme, select verbatim quotes, and generate action ideas; strict JSON via function calling

OpenAI/Anthropic SDK

renderer

Convert the PulseSummary into (a) a structured Doc-request tree for the Google Docs MCP, and (b) an HTML+text email body for the Gmail MCP

jinja2, markdown-it-py

orchestrator

ReAct-style loop that decides: ingest → cluster → summarize → render → MCP-append → MCP-email

custom; optional langgraph

mcp_client

Thin wrapper around the official MCP SDK; holds sessions to the two Google servers

mcp (python-sdk)

4.2 Canonical Types

class RawReview(BaseModel):

    id: str                  # sha1(source + external_id)

    product_key: str

    source: Literal["appstore", "playstore"]

    rating: int

    title: str | None

    body: str

    posted_at: datetime

    version: str | None

    language: str

    country: str


class Theme(BaseModel):

    id: str

    rank: int

    label: str

    description: str

    sentiment: Literal["negative", "mixed", "positive"]

    review_count: int

    representative_review_ids: list[str]


class PulseSummary(BaseModel):

    product: str

    window: Window            # start, end, weeks

    stats: PulseStats         # total_reviews, avg_rating, rating_delta_vs_prev

    top_themes: list[Theme]   # typically 3

    quotes: list[Quote]       # verbatim, validated against raw bodies

    action_ideas: list[ActionIdea]

    what_this_solves: list[AudienceValue]


4.3 Guardrails

Reviews are treated as data, never instructions. They are passed to the LLM through structured message parts, never concatenated into system prompts.
Verbatim-quote validator: every quote the LLM proposes must match a substring of some review.body (case-insensitive, whitespace-normalised). Non-matching quotes are dropped.
PII scrub (regex: emails, phone numbers, Aadhaar-like numbers) happens before text reaches the LLM and before it reaches the Google Doc.
Cost cap per run: hard stop if llm_tokens > N for the run.

5. Data Model & Local Storage

A single SQLite file per deployment (lightweight — the Google Doc is the durable, human-facing store):

CREATE TABLE products (key TEXT PRIMARY KEY, display TEXT,

                       appstore_id TEXT, play_package TEXT,

                       gdoc_id TEXT,            -- once discovered/created

                       gmail_to TEXT);          -- csv distribution list


CREATE TABLE reviews (id TEXT PRIMARY KEY, product_key TEXT, source TEXT,

                      rating INT, title TEXT, body TEXT, posted_at DATETIME,

                      version TEXT, language TEXT, country TEXT,

                      ingested_at DATETIME, raw_json TEXT);


CREATE TABLE review_embeddings (review_id TEXT PRIMARY KEY,

                                embedding BLOB);   -- sqlite-vec


CREATE TABLE runs (id TEXT PRIMARY KEY, product_key TEXT,

                   iso_week TEXT, window_start DATE, window_end DATE,

                   status TEXT, metrics_json TEXT,

                   gdoc_heading_id TEXT,           -- from Docs MCP

                   gmail_message_id TEXT);         -- from Gmail MCP


CREATE TABLE themes (id TEXT PRIMARY KEY, run_id TEXT, rank INT,

                     label TEXT, description TEXT, sentiment TEXT,

                     review_count INT, representative_review_ids_json TEXT);


runs.gdoc_heading_id and runs.gmail_message_id are the proof of delivery — they only get written after the MCP tool call succeeds.


7. Idempotency & Re-runs

Run key: run_id = sha1(product_key + iso_week).
Doc-side idempotency: anchor string pulse-{product}-{iso_week} embedded in the Heading 1 text → a simple substring search on the Doc body decides whether to append.
Email-side idempotency: custom header X-Pulse-Run-Id: {run_id} + Gmail search before send.
Backfill CLI: pulse run --product groww --week 2026-W15 re-runs any past week; uses the same idempotency logic, so it's safe to re-run.
Partial failure: if the Docs append succeeds but the Gmail send fails, the next run detects the Doc section is already there and proceeds directly to the Gmail step.

8. Security, Privacy & Governance

Concern

Mitigation

Google credentials

Stored only inside the MCP servers (OAuth refresh token or service account JSON). The agent never sees them.

Minimal OAuth scopes

Docs: documents (no Drive). Gmail: gmail.compose + gmail.send + gmail.labels. No mail.google.com full scope.

PII in reviews

Regex scrub before LLM and before Google Doc.

Prompt injection via review body

Reviews passed as structured data parts; strict JSON response schemas; verbatim-quote validator.

Accidental email blast in dev

CONFIRM_SEND=true gate on gmail.send_message; default is create draft only.

Auditability

runs table stores gdoc_heading_id and gmail_message_id; the Google Doc itself is the long-term audit log.

MCP transport

stdio locally; SSE/HTTPS in deployment with mTLS or a private network.