from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from hashlib import sha1
from pathlib import Path
from typing import Any

import streamlit as st


def inject_pulse_styles() -> None:
    st.markdown(
        """
        <style>
          @import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap");
          html, body, [class*="css"]  {
            font-family: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
          }
          .block-container {
            padding-top: 1.25rem;
            padding-bottom: 3rem;
            max-width: 1200px;
          }
          .pulse-hero {
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 14px;
            padding: 1.35rem 1.5rem 1.25rem;
            margin-bottom: 1.25rem;
            background: linear-gradient(135deg, rgba(21, 29, 46, 0.95) 0%, rgba(12, 18, 34, 0.6) 100%);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
          }
          .pulse-kicker {
            margin: 0 0 0.35rem;
            font-size: 0.72rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: #7dd3fc;
            font-weight: 600;
          }
          .pulse-title {
            margin: 0 0 0.4rem;
            font-size: 1.85rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            line-height: 1.15;
            color: #f8fafc;
          }
          .pulse-sub {
            margin: 0;
            font-size: 0.95rem;
            color: #94a3b8;
            max-width: 46rem;
            line-height: 1.45;
          }
          .pulse-meta {
            margin-top: 0.85rem;
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
          }
          .pulse-chip {
            display: inline-block;
            font-size: 0.72rem;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            border: 1px solid rgba(148, 163, 184, 0.35);
            color: #cbd5e1;
            background: rgba(15, 23, 42, 0.5);
          }
          .pulse-chip-ok { border-color: rgba(52, 211, 153, 0.45); color: #6ee7b7; }
          .pulse-chip-warn { border-color: rgba(251, 191, 36, 0.45); color: #fcd34d; }
          .pulse-chip-bad { border-color: rgba(248, 113, 113, 0.45); color: #fca5a5; }
          div[data-testid="stMetric"] {
            background: rgba(21, 29, 46, 0.65);
            border: 1px solid rgba(51, 65, 85, 0.55);
            border-radius: 12px;
            padding: 0.65rem 0.75rem;
          }
          div[data-testid="stMetric"] label {
            color: #94a3b8 !important;
          }
          div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: #f1f5f9 !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def pulse_hero(
    *,
    db_path: Path,
    email_provider: str,
    use_real_google: bool,
    resend_configured: bool,
    cli_available: bool,
) -> None:
    chips: list[str] = []
    if cli_available:
        chips.append('<span class="pulse-chip pulse-chip-ok">CLI ready</span>')
    else:
        chips.append('<span class="pulse-chip pulse-chip-bad">CLI unavailable</span>')
    if email_provider == "resend":
        chips.append('<span class="pulse-chip pulse-chip-ok">Email: Resend</span>')
    else:
        chips.append('<span class="pulse-chip">Email: Gmail MCP</span>')
    if email_provider == "gmail" and not use_real_google:
        chips.append('<span class="pulse-chip pulse-chip-warn">Google: mock</span>')
    elif use_real_google:
        chips.append('<span class="pulse-chip pulse-chip-ok">Google: live</span>')
    else:
        chips.append('<span class="pulse-chip">Google: off</span>')
    if email_provider == "resend":
        chips.append(
            '<span class="pulse-chip pulse-chip-ok">Resend key</span>'
            if resend_configured
            else '<span class="pulse-chip pulse-chip-bad">Resend key missing</span>'
        )
    st.markdown(
        f"""
        <div class="pulse-hero">
          <p class="pulse-kicker">Weekly product pulse</p>
          <h1 class="pulse-title">Control center</h1>
          <p class="pulse-sub">
            Generate the weekly note and artifacts, preview on this page, then publish to Docs and/or send the delivery email when you are ready.
          </p>
          <div class="pulse-meta">{"".join(chips)}</div>
          <p class="pulse-sub" style="margin-top:0.75rem;font-size:0.8rem;">
            Database: <code style="color:#7dd3fc;">{db_path}</code>
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_db_path() -> Path:
    raw = os.getenv("PULSE_DB_PATH", "data/pulse.db").strip() or "data/pulse.db"
    db_path = Path(raw).expanduser()
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    return db_path.resolve()


def run_command(
    args: list[str], env_overrides: dict[str, str] | None = None
) -> tuple[int, str, str]:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    process = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return process.returncode, process.stdout, process.stderr


def render_stderr(return_code: int, stderr: str, label: str) -> None:
    detail = stderr.strip()
    if not detail:
        return
    if return_code == 0:
        st.warning(f"{label} completed with warnings.")
        with st.expander(f"{label} warnings"):
            st.code(detail, language="text")
        return
    st.error(detail)


def is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def build_run_id(product: str, iso_week: str) -> str:
    return sha1(f"{product}:{iso_week}".encode()).hexdigest()


def is_valid_run_id(value: str) -> bool:
    text = value.strip().lower()
    if len(text) != 40:
        return False
    return all(ch in "0123456789abcdef" for ch in text)


def get_artifacts_dir() -> Path:
    raw = os.getenv("PULSE_ARTIFACTS_DIR", "data/artifacts").strip() or "data/artifacts"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


@st.cache_data(show_spinner=False)
def check_pipeline_cli() -> tuple[bool, str]:
    return_code, _, stderr = run_command([sys.executable, "-m", "agent.__main__", "--help"])
    if return_code == 0:
        return True, ""
    detail = stderr.strip() or "Missing runtime dependencies in this deployment."
    return False, detail


def load_recent_runs(limit: int = 10) -> list[dict[str, Any]]:
    db_path = get_db_path()
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, product_key, iso_week, status, metrics_json,
                       gdoc_heading_id, gmail_message_id
                FROM runs
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [
        {
            "run_id": str(row[0]),
            "product": str(row[1]),
            "iso_week": str(row[2]),
            "status": str(row[3]),
            "metrics_json": str(row[4]) if row[4] is not None else "",
            "gdoc_heading_id": str(row[5]) if row[5] is not None else "",
            "gmail_message_id": str(row[6]) if row[6] is not None else "",
        }
        for row in rows
    ]


def parse_metrics(metrics_json: str) -> dict[str, Any]:
    if not metrics_json.strip():
        return {}
    try:
        raw = json.loads(metrics_json)
        if isinstance(raw, dict):
            return raw
    except json.JSONDecodeError:
        return {}
    return {}


def build_doc_link(run: dict[str, Any]) -> str | None:
    heading = str(run.get("gdoc_heading_id", "")).strip()
    if not heading:
        return None
    if heading == "document":
        return None
    gdoc_id = os.getenv("PULSE_GDOC_ID", "").strip()
    if not gdoc_id:
        return None
    return f"https://docs.google.com/document/d/{gdoc_id}/edit#heading={heading}"


def status_color(status: str) -> str:
    if status in {"published", "published_docs"}:
        return "🟢"
    if status in {"failed", "error"}:
        return "🔴"
    return "🟡"


st.set_page_config(
    page_title="Weekly Pulse",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded",
)
inject_pulse_styles()

if "last_cli" not in st.session_state:
    st.session_state["last_cli"] = None

email_provider = (os.getenv("PULSE_EMAIL_PROVIDER", "gmail") or "gmail").strip().lower()
use_real_google = is_truthy(os.getenv("PULSE_USE_REAL_GOOGLE"))
resend_configured = bool((os.getenv("PULSE_RESEND_API_KEY") or "").strip())
db_path_resolved = get_db_path()

with st.sidebar:
    st.markdown("### Parameters")
    product = st.selectbox("Product", ["groww", "indmoney"], index=0)
    iso_week = st.text_input("ISO week", value="2026-W18")
    weeks = st.number_input("Ingestion window (weeks)", min_value=1, max_value=20, value=10, step=1)
    st.markdown("---")
    dry_run = st.toggle("Dry-run (no send)", value=True, help="When on, publish/send will not actually dispatch email.")
    st.markdown("---")
    st.markdown("### Run ID")
    if "publish_run_id" not in st.session_state:
        st.session_state["publish_run_id"] = ""
    run_id_to_publish = st.text_area(
        "Paste full run id (40 hex)",
        key="publish_run_id",
        height=100,
        label_visibility="visible",
        help="SHA1 of product:week. Must be 40 characters — truncated ids will fail.",
    )

cli_available, cli_error = check_pipeline_cli()
runs = load_recent_runs(30)
latest = runs[0] if runs else None

pulse_hero(
    db_path=db_path_resolved,
    email_provider=email_provider,
    use_real_google=use_real_google,
    resend_configured=resend_configured,
    cli_available=cli_available,
)

if not cli_available:
    with st.container(border=True):
        st.warning(
            "Pipeline CLI is unavailable in this environment. "
            "Install project dependencies for Run / Publish actions."
        )
        with st.expander("CLI error details"):
            st.code(cli_error, language="text")

if email_provider == "gmail" and not use_real_google:
    st.warning(
        "Gmail MCP is in mock mode (`PULSE_USE_REAL_GOOGLE=false`). "
        "No real inbox delivery until Google OAuth is configured."
    )
if email_provider == "resend" and not resend_configured:
    st.error("Resend is selected but `PULSE_RESEND_API_KEY` is missing.")

with st.expander("Environment (read-only)", expanded=False):
    st.code(
        "\n".join(
            [
                f"PULSE_EMAIL_PROVIDER={email_provider}",
                f"PULSE_USE_REAL_GOOGLE={use_real_google}",
                f"PULSE_RESEND_API_KEY set={resend_configured}",
                f"PULSE_CONFIRM_SEND={os.getenv('PULSE_CONFIRM_SEND', '')}",
            ]
        ),
        language="text",
    )

with st.container(border=True):
    st.markdown("#### Snapshot")
    top1, top2, top3, top4 = st.columns(4)
    top1.metric("Runs visible", str(len(runs)))
    latest_status = (
        f"{status_color(latest['status'])} {latest['status']}"
        if latest
        else "—"
    )
    top2.metric("Latest status", latest_status)
    top3.metric("Latest run", latest["run_id"][:10] + "…" if latest else "—")
    top4.metric("Latest week", latest["iso_week"] if latest else "—")

last = st.session_state.get("last_cli")
if isinstance(last, dict) and last.get("stdout") is not None:
    with st.container(border=True):
        st.markdown(f"#### {last.get('title', 'Last command output')}")
        st.code(str(last.get("stdout") or "(no stdout)"), language="bash")
        if last.get("stderr"):
            with st.expander("Stderr"):
                st.code(str(last.get("stderr")), language="text")
        if last.get("return_code") not in (None, 0):
            st.error(f"Exit code: {last.get('return_code')}")

with st.container(border=True):
    st.markdown("#### Actions")
    st.caption("Order: generate the report → review below → send email or full publish when ready.")
    run_col, report_col, email_col, pub_col, ref_col = st.columns([2, 2, 2, 2, 1])

    if run_col.button("Run full pipeline", type="primary", use_container_width=True, disabled=not cli_available):
        env_flag = "false" if dry_run else "true"
        cmd = [
            sys.executable,
            "-m",
            "agent.__main__",
            "run",
            "--product",
            product,
            "--week",
            iso_week,
            "--weeks",
            str(weeks),
        ]
        return_code, stdout, stderr = run_command(
            cmd,
            env_overrides={"PULSE_CONFIRM_SEND": "false" if dry_run else "true"},
        )
        st.session_state["last_cli"] = {
            "title": "Run full pipeline",
            "stdout": stdout,
            "stderr": stderr,
            "return_code": return_code,
        }
        st.markdown("##### Pipeline log")
        st.code(stdout or "(no stdout)", language="bash")
        render_stderr(return_code, stderr, "Pipeline run")
        if return_code == 0:
            st.success(f"Pipeline finished (PULSE_CONFIRM_SEND={env_flag}).")
            st.cache_data.clear()
        else:
            st.error(f"Pipeline failed (exit {return_code}).")

    if report_col.button("Generate report only", use_container_width=True, disabled=not cli_available):
        run_id = build_run_id(product, iso_week)
        steps: list[tuple[str, list[str]]] = [
            (
                "Ingest",
                [
                    sys.executable,
                    "-m",
                    "agent.__main__",
                    "ingest",
                    "--product",
                    product,
                    "--week",
                    iso_week,
                    "--weeks",
                    str(weeks),
                ],
            ),
            (
                "Cluster",
                [sys.executable, "-m", "agent.__main__", "cluster", "--run", run_id],
            ),
            (
                "Summarize",
                [sys.executable, "-m", "agent.__main__", "summarize", "--run", run_id],
            ),
            (
                "Render",
                [sys.executable, "-m", "agent.__main__", "render", "--run", run_id],
            ),
        ]
        full_stdout: list[str] = []
        failed = False
        for step_name, cmd in steps:
            return_code, stdout, stderr = run_command(cmd)
            full_stdout.append(f"== {step_name} ==\n{stdout.strip() or '(no stdout)'}")
            if return_code != 0:
                st.error(f"{step_name} failed (exit {return_code}).")
                render_stderr(return_code, stderr, f"{step_name} step")
                failed = True
                break
            render_stderr(return_code, stderr, f"{step_name} step")
        st.session_state["last_cli"] = {
            "title": "Generate report only",
            "stdout": "\n\n".join(full_stdout),
            "stderr": "",
            "return_code": 0 if not failed else 1,
        }
        st.markdown("##### Generation log")
        st.code("\n\n".join(full_stdout), language="bash")
        if not failed:
            st.success("Report generated. No email was sent.")
            st.session_state["publish_run_id"] = run_id
            st.info(f"Run id copied to sidebar: `{run_id}`")
            report_dir = get_artifacts_dir() / run_id
            weekly_note = report_dir / "weekly_note.md"
            email_text = report_dir / "email.txt"
            if weekly_note.exists():
                st.markdown("##### Weekly note (inline)")
                st.markdown(weekly_note.read_text(encoding="utf-8"))
            if email_text.exists():
                with st.expander("Email text preview"):
                    st.code(email_text.read_text(encoding="utf-8"), language="text")
            st.cache_data.clear()

    if email_col.button("Send email only", use_container_width=True, disabled=not cli_available):
        rid = run_id_to_publish.strip()
        if not rid:
            st.warning("Enter a run id in the sidebar.")
        elif not is_valid_run_id(rid):
            st.error("Run id must be exactly 40 hex characters (full SHA1).")
        else:
            env_flag = "false" if dry_run else "true"
            cmd = [
                sys.executable,
                "-m",
                "agent.__main__",
                "publish",
                "--run",
                rid,
                "--target",
                "gmail",
            ]
            return_code, stdout, stderr = run_command(
                cmd,
                env_overrides={"PULSE_CONFIRM_SEND": env_flag},
            )
            st.session_state["last_cli"] = {
                "title": "Send email only",
                "stdout": stdout,
                "stderr": stderr,
                "return_code": return_code,
            }
            st.markdown("##### Send email log")
            st.code(stdout or "(no stdout)", language="bash")
            render_stderr(return_code, stderr, "Send email")
            if return_code == 0:
                st.success(f"Finished (PULSE_CONFIRM_SEND={env_flag}).")
                st.cache_data.clear()
            else:
                st.error(f"Send failed (exit {return_code}).")

    if pub_col.button("Publish docs + email", use_container_width=True, disabled=not cli_available):
        rid = run_id_to_publish.strip()
        if not rid:
            st.warning("Enter a run id in the sidebar.")
        elif not is_valid_run_id(rid):
            st.error("Run id must be exactly 40 hex characters (full SHA1).")
        else:
            env_flag = "false" if dry_run else "true"
            cmd = [
                sys.executable,
                "-m",
                "agent.__main__",
                "publish",
                "--run",
                rid,
                "--target",
                "both",
            ]
            return_code, stdout, stderr = run_command(
                cmd,
                env_overrides={"PULSE_CONFIRM_SEND": env_flag},
            )
            st.session_state["last_cli"] = {
                "title": "Publish docs + email",
                "stdout": stdout,
                "stderr": stderr,
                "return_code": return_code,
            }
            st.markdown("##### Publish log")
            st.code(stdout or "(no stdout)", language="bash")
            render_stderr(return_code, stderr, "Publish")
            if return_code == 0:
                st.success(f"Publish completed (PULSE_CONFIRM_SEND={env_flag}).")
                st.cache_data.clear()
            else:
                st.error(f"Publish failed (exit {return_code}).")

    if ref_col.button("Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with st.container(border=True):
    st.markdown("#### Report preview")
    _preview_rid = run_id_to_publish.strip() if run_id_to_publish else ""
    if _preview_rid and not is_valid_run_id(_preview_rid):
        st.warning("Run id is not 40 hex characters — fix it in the sidebar to preview or publish.")
    elif _preview_rid:
        _art = get_artifacts_dir() / _preview_rid
        _wn = _art / "weekly_note.md"
        _et = _art / "email.txt"
        _eh = _art / "email.html"
        st.caption(f"Artifacts: `{_art}`")
        if _wn.exists():
            st.markdown(_wn.read_text(encoding="utf-8"))
        else:
            st.info(f"No `weekly_note.md` at `{_wn}`. Generate a report for this run first.")
        if _et.exists():
            with st.expander("Email body (plain text)"):
                st.code(_et.read_text(encoding="utf-8"), language="text")
        if _eh.exists():
            with st.expander("Email HTML (source)"):
                st.code(_eh.read_text(encoding="utf-8"), language="html")
    else:
        st.info("Enter a run id in the sidebar to load the weekly note and email drafts from disk.")

left, right = st.columns([1.15, 1.85])
with left:
    with st.container(border=True):
        st.markdown("#### Recent runs")
        if runs:
            for item in runs[:10]:
                label = f"{status_color(item['status'])} {item['iso_week']} · {item['product']}"
                with st.expander(label):
                    st.code(item["run_id"], language="text")
                    st.text(f"Status: {item['status']}")
                    if item["gdoc_heading_id"]:
                        link = build_doc_link(item)
                        if link:
                            st.markdown(f"[Open doc section]({link})")
                        else:
                            st.text(f"gdoc_heading_id: {item['gdoc_heading_id']}")
                    if item["gmail_message_id"]:
                        st.text(f"Delivery id: {item['gmail_message_id']}")
                    metrics = parse_metrics(item["metrics_json"])
                    if metrics:
                        st.json(metrics)
        else:
            st.info("No runs yet.")

with right:
    with st.container(border=True):
        st.markdown("#### Run table")
        if runs:
            st.dataframe(runs, use_container_width=True, hide_index=True)
        else:
            st.info("Run a pipeline to populate this table.")
