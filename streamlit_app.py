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


st.set_page_config(page_title="Weekly Pulse Control Panel", layout="wide")
st.title("Weekly Pulse Control Center")
st.caption("Operator UI: run pipeline, publish outputs, and monitor delivery.")
st.caption(f"DB path: `{get_db_path()}`")

if "last_cli" not in st.session_state:
    st.session_state["last_cli"] = None

last = st.session_state.get("last_cli")
if isinstance(last, dict) and last.get("stdout") is not None:
    st.subheader(last.get("title", "Last command output"))
    st.code(str(last.get("stdout") or "(no stdout)"), language="bash")
    if last.get("stderr"):
        with st.expander("Stderr"):
            st.code(str(last.get("stderr")), language="text")
    if last.get("return_code") not in (None, 0):
        st.error(f"Exit code: {last.get('return_code')}")

email_provider = (os.getenv("PULSE_EMAIL_PROVIDER", "gmail") or "gmail").strip().lower()
use_real_google = is_truthy(os.getenv("PULSE_USE_REAL_GOOGLE"))
resend_configured = bool((os.getenv("PULSE_RESEND_API_KEY") or "").strip())
with st.expander("Runtime email / Google (read-only)", expanded=False):
    st.write(f"- `PULSE_EMAIL_PROVIDER` → **{email_provider}**")
    st.write(f"- `PULSE_USE_REAL_GOOGLE` → **{use_real_google}**")
    st.write(f"- `PULSE_RESEND_API_KEY` set → **{resend_configured}**")
    st.write(f"- `PULSE_CONFIRM_SEND` → **{os.getenv('PULSE_CONFIRM_SEND', '')}**")

if email_provider == "gmail" and not use_real_google:
    st.warning(
        "Real Google mode is OFF (`PULSE_USE_REAL_GOOGLE=false`). "
        "Publish can complete in mock mode without delivering a real inbox email."
    )
if email_provider == "resend" and not resend_configured:
    st.error("Resend is selected but `PULSE_RESEND_API_KEY` is missing in this deployment.")

with st.sidebar:
    st.subheader("Pipeline Run")
    product = st.selectbox("Product", ["groww", "indmoney"], index=0)
    iso_week = st.text_input("ISO week", value="2026-W18")
    weeks = st.number_input("Ingestion window weeks", min_value=1, max_value=20, value=10, step=1)
    dry_run = st.toggle("Dry-run publish (no send)", value=True)
    st.divider()
    st.subheader("Publish Existing Run")
    if "publish_run_id" not in st.session_state:
        st.session_state["publish_run_id"] = ""
    run_id_to_publish = st.text_area(
        "Run ID (40 hex chars — paste full id)",
        key="publish_run_id",
        height=90,
        help="Must be exactly 40 characters. A truncated id will not find artifacts or send email.",
    )

cli_available, cli_error = check_pipeline_cli()
if not cli_available:
    st.warning(
        "Pipeline CLI is unavailable in this Streamlit environment. "
        "Use this app for run visibility, or install full project dependencies "
        "to enable Run/Publish actions."
    )
    with st.expander("CLI error details"):
        st.code(cli_error, language="text")

runs = load_recent_runs(30)
latest = runs[0] if runs else None

top1, top2, top3, top4 = st.columns(4)
top1.metric("Runs visible", str(len(runs)))
latest_status = (
    f"{status_color(latest['status'])} {latest['status']}"
    if latest
    else "—"
)
top2.metric("Latest status", latest_status)
top3.metric("Latest run", latest["run_id"][:10] + "..." if latest else "—")
top4.metric("Latest week", latest["iso_week"] if latest else "—")

st.divider()
run_col, report_col, email_col, pub_col, ref_col = st.columns([2, 2, 2, 2, 1])

if run_col.button("▶ Run Full Pipeline", use_container_width=True, disabled=not cli_available):
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
    st.subheader("Run Output")
    st.code(stdout or "(no stdout)", language="bash")
    render_stderr(return_code, stderr, "Pipeline run")
    st.session_state["last_cli"] = {
        "title": "Run Full Pipeline output",
        "stdout": stdout,
        "stderr": stderr,
        "return_code": return_code,
    }
    if return_code == 0:
        st.success(
            "Pipeline finished successfully "
            f"(PULSE_CONFIRM_SEND={env_flag} for this run)."
        )
        st.cache_data.clear()
    else:
        st.error(f"Pipeline failed with exit code {return_code}")

if report_col.button("🧾 Generate Report Only", use_container_width=True, disabled=not cli_available):
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
            st.error(f"{step_name} failed with exit code {return_code}")
            render_stderr(return_code, stderr, f"{step_name} step")
            failed = True
            break
        render_stderr(return_code, stderr, f"{step_name} step")
    st.subheader("Report Generation Output")
    st.code("\n\n".join(full_stdout), language="bash")
    if not failed:
        st.success("Report generated successfully. No email was sent.")
        st.session_state["publish_run_id"] = run_id
        st.info(f"Run ID pre-filled for publish: `{run_id}`")
        report_dir = get_artifacts_dir() / run_id
        weekly_note = report_dir / "weekly_note.md"
        email_text = report_dir / "email.txt"
        if weekly_note.exists():
            st.subheader("Weekly Note Preview")
            st.markdown(weekly_note.read_text(encoding="utf-8"))
        if email_text.exists():
            with st.expander("Email Text Preview"):
                st.code(email_text.read_text(encoding="utf-8"), language="text")
        st.cache_data.clear()

if email_col.button("📧 Send email only", use_container_width=True, disabled=not cli_available):
    rid = run_id_to_publish.strip()
    if not rid:
        st.warning("Enter a run_id first.")
    elif not is_valid_run_id(rid):
        st.error("Run ID must be exactly 40 hex characters (full SHA1). Your id looks truncated.")
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
            "title": "Send email only output",
            "stdout": stdout,
            "stderr": stderr,
            "return_code": return_code,
        }
        st.subheader("Send email output")
        st.code(stdout or "(no stdout)", language="bash")
        render_stderr(return_code, stderr, "Send email")
        if return_code == 0:
            st.success(f"Command finished (PULSE_CONFIRM_SEND={env_flag}).")
            st.cache_data.clear()
        else:
            st.error(f"Send failed with exit code {return_code}")

if pub_col.button("📤 Publish Docs + Email", use_container_width=True, disabled=not cli_available):
    rid = run_id_to_publish.strip()
    if not rid:
        st.warning("Enter a run_id first.")
    elif not is_valid_run_id(rid):
        st.error("Run ID must be exactly 40 hex characters (full SHA1). Your id looks truncated.")
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
            "title": "Publish output",
            "stdout": stdout,
            "stderr": stderr,
            "return_code": return_code,
        }
        st.subheader("Publish Output")
        st.code(stdout or "(no stdout)", language="bash")
        render_stderr(return_code, stderr, "Publish")
        if return_code == 0:
            st.success(
                "Publish completed "
                f"(PULSE_CONFIRM_SEND={env_flag} for this action)."
            )
            st.cache_data.clear()
        else:
            st.error(f"Publish failed with exit code {return_code}")

if ref_col.button("↻ Refresh", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.divider()
st.subheader("Report preview (from disk)")
_preview_rid = run_id_to_publish.strip() if run_id_to_publish else ""
if _preview_rid and not is_valid_run_id(_preview_rid):
    st.warning("Run ID is not 40 hex characters — preview and publish will not match a real run.")
elif _preview_rid:
    _art = get_artifacts_dir() / _preview_rid
    _wn = _art / "weekly_note.md"
    _et = _art / "email.txt"
    _eh = _art / "email.html"
    st.caption(f"Artifacts dir: `{_art}`")
    if _wn.exists():
        st.markdown(_wn.read_text(encoding="utf-8"))
    else:
        st.info(f"No `weekly_note.md` at `{_wn}`. Generate a report for this run first.")
    if _et.exists():
        with st.expander("Email text"):
            st.code(_et.read_text(encoding="utf-8"), language="text")
    if _eh.exists():
        with st.expander("Email HTML (source)"):
            st.code(_eh.read_text(encoding="utf-8"), language="html")
else:
    st.info("Enter a Run ID above to preview the generated report.")

st.divider()
left, right = st.columns([1.3, 1.7])

with left:
    st.subheader("Recent Runs")
    if runs:
        for item in runs[:10]:
            label = f"{status_color(item['status'])} {item['iso_week']} • {item['product']}"
            with st.expander(label):
                st.text(f"run_id: {item['run_id']}")
                st.text(f"status: {item['status']}")
                if item["gdoc_heading_id"]:
                    link = build_doc_link(item)
                    if link:
                        st.markdown(f"[Open Doc Section]({link})")
                    else:
                        st.text(f"gdoc_heading_id: {item['gdoc_heading_id']}")
                if item["gmail_message_id"]:
                    st.text(f"gmail_message_id: {item['gmail_message_id']}")
                metrics = parse_metrics(item["metrics_json"])
                if metrics:
                    st.json(metrics)
    else:
        st.info("No runs found yet.")

with right:
    st.subheader("Run Table")
if runs:
    st.dataframe(runs, use_container_width=True)
else:
    st.info("No runs found yet. Execute a pipeline run first.")
