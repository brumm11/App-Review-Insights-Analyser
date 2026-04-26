from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any

import streamlit as st

from agent.types import current_iso_week


def inject_groww_styles() -> None:
    st.markdown(
        """
        <style>
          @import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap");
          html, body, [data-testid="stAppViewContainer"] {
            font-family: "Inter", ui-sans-serif, system-ui, sans-serif;
          }
          .block-container {
            padding-top: 1.5rem;
            padding-bottom: 3rem;
            max-width: 880px;
          }
          .groww-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 1.5rem;
          }
          .groww-title {
            margin: 0;
            font-size: 1.65rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            color: #E6EAF2;
          }
          .groww-sub {
            margin: 0.35rem 0 0;
            font-size: 0.9rem;
            color: #8A93A6;
            max-width: 28rem;
            line-height: 1.45;
          }
          .groww-status {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            font-size: 0.8rem;
            font-weight: 500;
            color: #8A93A6;
            white-space: nowrap;
          }
          .groww-dot {
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: #8A93A6;
          }
          .groww-dot-ready { background: #00D09C; box-shadow: 0 0 12px rgba(0, 208, 156, 0.45); }
          .groww-dot-run { background: #38bdf8; animation: pulse 1.2s ease-in-out infinite; }
          .groww-dot-fail { background: #f87171; }
          @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.45} }
          .groww-hero {
            background: #121826;
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            padding: 1.75rem 1.75rem 1.5rem;
            margin-bottom: 1.5rem;
          }
          .groww-hero h2 {
            margin: 0 0 0.35rem;
            font-size: 1.25rem;
            font-weight: 600;
            color: #E6EAF2;
          }
          .groww-hero p {
            margin: 0 0 1.25rem;
            font-size: 0.88rem;
            color: #8A93A6;
            line-height: 1.5;
          }
          .groww-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 1.25rem;
            font-size: 0.78rem;
            color: #8A93A6;
            border-top: 1px solid rgba(255,255,255,0.06);
            padding-top: 1rem;
            margin-top: 0.25rem;
          }
          .groww-meta strong { color: #E6EAF2; font-weight: 500; }
          div[data-testid="stMetric"] {
            background: #121826 !important;
            border: 1px solid rgba(255,255,255,0.06) !important;
            border-radius: 14px !important;
            padding: 0.55rem 0.65rem !important;
          }
          div[data-testid="stMetric"] label { color: #8A93A6 !important; }
          div[data-testid="stMetric"] [data-testid="stMetricValue"] { color: #E6EAF2 !important; }
          div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stMarkdown"]):has(.groww-hero) {
            margin-bottom: 0;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_session() -> None:
    defaults: dict[str, Any] = {
        "latest_run_id": None,
        "report_ready": False,
        "pipeline_ui_state": "idle",
        "last_run_at": None,
        "last_sent_at": None,
        "last_cli": None,
        "last_error": None,
        "dev_run_id_override": "",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


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
        with st.expander(f"{label} — details"):
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


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


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


def status_emoji(status: str) -> str:
    if status in {"published", "published_docs"}:
        return "🟢"
    if status in {"failed", "error"}:
        return "🔴"
    return "🟡"


def effective_run_id() -> str | None:
    override = (st.session_state.get("dev_run_id_override") or "").strip()
    if override and is_valid_run_id(override):
        return override.lower()
    rid = st.session_state.get("latest_run_id")
    if rid and is_valid_run_id(str(rid)):
        return str(rid).strip().lower()
    return None


def run_report_pipeline(
    *,
    product: str,
    iso_week: str,
    weeks: int,
) -> tuple[bool, str, str, str]:
    """Ingest → cluster → summarize → render. Returns (ok, run_id, combined_stdout, stderr)."""
    run_id = build_run_id(product, iso_week)
    chunks: list[str] = []
    all_err: list[str] = []
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
        ("Cluster", [sys.executable, "-m", "agent.__main__", "cluster", "--run", run_id]),
        ("Summarize", [sys.executable, "-m", "agent.__main__", "summarize", "--run", run_id]),
        ("Render", [sys.executable, "-m", "agent.__main__", "render", "--run", run_id]),
    ]
    for name, cmd in steps:
        code, out, err = run_command(cmd)
        chunks.append(f"== {name} ==\n{(out or '').strip() or '(no stdout)'}")
        if err.strip():
            all_err.append(err)
        if code != 0:
            return False, run_id, "\n\n".join(chunks), "\n".join(all_err) + f"\n[{name}] exit {code}"
    return True, run_id, "\n\n".join(chunks), "\n".join(all_err)


# --- Page ---
st.set_page_config(
    page_title="Reports Control Center",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="collapsed",
)
inject_groww_styles()
init_session()

cli_available, cli_error = check_pipeline_cli()
email_provider = (os.getenv("PULSE_EMAIL_PROVIDER", "gmail") or "gmail").strip().lower()
use_real_google = is_truthy(os.getenv("PULSE_USE_REAL_GOOGLE"))
resend_configured = bool((os.getenv("PULSE_RESEND_API_KEY") or "").strip())
runs = load_recent_runs(30)
latest = runs[0] if runs else None

ui_state = str(st.session_state.get("pipeline_ui_state") or "idle")
dot_class = "groww-dot-ready"
status_label = "Ready"
if ui_state == "running":
    dot_class = "groww-dot-run"
    status_label = "Running"
elif ui_state == "failed":
    dot_class = "groww-dot-fail"
    status_label = "Failed"

st.markdown(
    f"""
    <div class="groww-header">
      <div>
        <h1 class="groww-title">Reports Control Center</h1>
        <p class="groww-sub">Generate and send weekly insights — no run id copy/paste.</p>
      </div>
      <div class="groww-status">
        <span class="groww-dot {dot_class}"></span>
        <span>{status_label}</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if not cli_available:
    st.error("CLI is not available in this environment.")
    with st.expander("Details"):
        st.code(cli_error, language="text")
    st.stop()

if email_provider == "gmail" and not use_real_google:
    st.info("Gmail MCP is in mock mode. Use Resend in secrets for real delivery (`PULSE_EMAIL_PROVIDER=resend`).")
if email_provider == "resend" and not resend_configured:
    st.warning("`PULSE_RESEND_API_KEY` is not set — Send report will fail until you add it.")

with st.expander("Advanced (optional)", expanded=False):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        product = st.selectbox("Product", ["groww", "indmoney"], index=0)
    with col_b:
        iso_week = st.text_input("ISO week", value=current_iso_week())
    with col_c:
        weeks = st.number_input("Ingestion window (weeks)", min_value=1, max_value=20, value=10, step=1)
    dry_run = st.toggle("Dry-run send (no email)", value=True)
    st.text_input(
        "Dev override: run id (40 hex, optional)",
        key="dev_run_id_override",
        help="Leave empty to use the run id from your last successful Run report.",
    )
    st.caption(f"Database: `{get_db_path()}`")

hero = st.container()
with hero:
    st.markdown(
        """
        <div class="groww-hero">
          <h2>Weekly report</h2>
          <p>Run analysis and render artifacts, then send the delivery email when you are ready.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns([1.1, 1.1, 1])
    run_clicked = c1.button(
        "Run report",
        type="primary",
        use_container_width=True,
        disabled=ui_state == "running",
    )
    send_clicked = c2.button(
        "Send report",
        use_container_width=True,
        disabled=ui_state == "running" or not st.session_state.get("report_ready"),
    )
    regen_clicked = c3.button(
        "Regenerate",
        use_container_width=True,
        disabled=ui_state == "running",
        help="Re-run ingest → render for the same product and week.",
    )

    lr = st.session_state.get("last_run_at")
    ls = st.session_state.get("last_sent_at")
    rid_show = effective_run_id() or "—"
    st.markdown(
        f"""
        <div class="groww-meta">
          <div><strong>Last run</strong><br/>{lr or "—"}</div>
          <div><strong>Last send</strong><br/>{ls or "—"}</div>
          <div><strong>Bound run id</strong><br/><code style="color:#00D09C;font-size:0.72rem;">{rid_show}</code></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

if run_clicked or regen_clicked:
    st.session_state["pipeline_ui_state"] = "running"
    st.session_state["last_error"] = None
    st.toast("Started — running analysis…", icon="⏳")
    with st.status("Running analysis…", expanded=True) as status:
        status.write("Running pipeline (ingest → cluster → summarize → render)…")
        ok, run_id, stdout, stderr = run_report_pipeline(product=product, iso_week=iso_week, weeks=weeks)
        status.write("Generating report artifacts…")
        if ok:
            status.update(label="Report ready", state="complete")
            st.session_state["latest_run_id"] = run_id
            st.session_state["report_ready"] = True
            st.session_state["last_run_at"] = now_iso()
            st.session_state["pipeline_ui_state"] = "idle"
            st.session_state["last_cli"] = {
                "title": "Run report — log",
                "stdout": stdout,
                "stderr": stderr,
                "return_code": 0,
            }
            st.cache_data.clear()
            st.toast("Report generated", icon="✅")
        else:
            status.update(label="Failed", state="error")
            st.session_state["report_ready"] = False
            st.session_state["pipeline_ui_state"] = "failed"
            st.session_state["last_error"] = stderr or "Unknown error"
            st.session_state["last_cli"] = {
                "title": "Run report — log",
                "stdout": stdout,
                "stderr": stderr,
                "return_code": 1,
            }
            st.error("Report run failed. Expand log below.")

if send_clicked:
    rid = effective_run_id()
    if not rid:
        st.error("No run id available. Run report first (or set a valid dev override).")
    else:
        st.toast("Sending…", icon="✉️")
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
        code, out, err = run_command(cmd, env_overrides={"PULSE_CONFIRM_SEND": env_flag})
        st.session_state["last_cli"] = {
            "title": "Send report — log",
            "stdout": out,
            "stderr": err,
            "return_code": code,
        }
        if code == 0:
            st.session_state["last_sent_at"] = now_iso()
            st.cache_data.clear()
            st.toast("Email send completed", icon="✅")
            if "skipped" in (out or "").lower():
                st.info("Provider may have skipped duplicate send; check log output.")
        else:
            st.error(f"Send failed (exit {code}).")
        render_stderr(code, err, "Send report")

with st.container(border=True):
    st.markdown("#### Snapshot")
    m1, m2, m3 = st.columns(3)
    m1.metric("Runs", str(len(runs)))
    erid = effective_run_id()
    m2.metric("Bound run id", (erid[:14] + "…") if erid and len(erid) > 14 else (erid or "—"))
    m3.metric("Latest week", latest["iso_week"] if latest else "—")

last = st.session_state.get("last_cli")
if isinstance(last, dict) and last.get("stdout") is not None:
    with st.expander(last.get("title", "Activity log"), expanded=bool(st.session_state.get("last_error"))):
        st.code(str(last.get("stdout") or "(no stdout)"), language="bash")
        if last.get("stderr"):
            st.code(str(last.get("stderr")), language="text")
        if last.get("return_code") not in (None, 0):
            st.caption(f"Exit code: {last.get('return_code')}")

with st.expander("Power tools", expanded=False):
    st.caption("Same CLI as before — optional full pipeline or docs + email.")
    p1, p2 = st.columns(2)
    if p1.button("Run full pipeline (includes publish)", use_container_width=True):
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
        code, out, err = run_command(cmd, env_overrides={"PULSE_CONFIRM_SEND": env_flag})
        st.session_state["last_cli"] = {"title": "Full pipeline", "stdout": out, "stderr": err, "return_code": code}
        if code == 0:
            rid = build_run_id(product, iso_week)
            st.session_state["latest_run_id"] = rid
            st.session_state["report_ready"] = True
            st.session_state["last_run_at"] = now_iso()
            st.cache_data.clear()
            st.success("Full pipeline finished.")
        else:
            st.error(f"Failed (exit {code}).")
        render_stderr(code, err, "Full pipeline")
    rid_pub = effective_run_id()
    if p2.button("Publish docs + email", use_container_width=True, disabled=not rid_pub):
        env_flag = "false" if dry_run else "true"
        cmd = [
            sys.executable,
            "-m",
            "agent.__main__",
            "publish",
            "--run",
            str(rid_pub),
            "--target",
            "both",
        ]
        code, out, err = run_command(cmd, env_overrides={"PULSE_CONFIRM_SEND": env_flag})
        st.session_state["last_cli"] = {"title": "Publish docs + email", "stdout": out, "stderr": err, "return_code": code}
        if code == 0:
            st.session_state["last_sent_at"] = now_iso()
            st.cache_data.clear()
            st.success("Publish completed.")
        else:
            st.error(f"Publish failed (exit {code}).")
        render_stderr(code, err, "Publish")

st.markdown("#### Preview")
_rid = effective_run_id()
if _rid and st.session_state.get("report_ready"):
    art = get_artifacts_dir() / _rid
    wn, et, eh = art / "weekly_note.md", art / "email.txt", art / "email.html"
    if wn.exists():
        st.markdown(wn.read_text(encoding="utf-8"))
    else:
        st.info("Weekly note not found yet for this run.")
    if et.exists():
        with st.expander("Email (plain text)"):
            st.code(et.read_text(encoding="utf-8"), language="text")
    if eh.exists():
        with st.expander("Email (HTML source)"):
            st.code(eh.read_text(encoding="utf-8"), language="html")
else:
    st.caption("Run a report to see the weekly note and email drafts here.")

left, right = st.columns([1, 1.2])
with left:
    with st.expander("Recent runs", expanded=False):
        if runs:
            for item in runs[:8]:
                label = f"{status_emoji(item['status'])} {item['iso_week']} · {item['product']}"
                with st.expander(label):
                    st.code(item["run_id"], language="text")
                    if item["gdoc_heading_id"]:
                        link = build_doc_link(item)
                        if link:
                            st.markdown(f"[Doc link]({link})")
                    metrics = parse_metrics(item["metrics_json"])
                    if metrics:
                        st.json(metrics)
        else:
            st.caption("No runs yet.")

with right:
    with st.expander("Run table", expanded=False):
        if runs:
            st.dataframe(runs, use_container_width=True, hide_index=True)
        else:
            st.caption("No data.")
