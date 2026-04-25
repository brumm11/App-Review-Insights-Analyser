from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import streamlit as st

DB_PATH = Path("data/pulse.db")


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


@st.cache_data(show_spinner=False)
def check_pipeline_cli() -> tuple[bool, str]:
    return_code, _, stderr = run_command([sys.executable, "-m", "agent.__main__", "--help"])
    if return_code == 0:
        return True, ""
    detail = stderr.strip() or "Missing runtime dependencies in this deployment."
    return False, detail


def load_recent_runs(limit: int = 10) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as conn:
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

with st.sidebar:
    st.subheader("Pipeline Run")
    product = st.selectbox("Product", ["groww", "indmoney"], index=0)
    iso_week = st.text_input("ISO week", value="2026-W18")
    weeks = st.number_input("Ingestion window weeks", min_value=1, max_value=20, value=10, step=1)
    dry_run = st.toggle("Dry-run publish (no send)", value=True)
    st.divider()
    st.subheader("Publish Existing Run")
    run_id_to_publish = st.text_input("Run ID", value="")

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
run_col, pub_col, ref_col = st.columns([2, 2, 1])

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
    if stderr:
        st.error(stderr)
    if return_code == 0:
        st.success(
            "Pipeline finished successfully "
            f"(PULSE_CONFIRM_SEND={env_flag} for this run)."
        )
        st.cache_data.clear()
    else:
        st.error(f"Pipeline failed with exit code {return_code}")

if pub_col.button("📤 Publish Docs + Gmail", use_container_width=True, disabled=not cli_available):
    if run_id_to_publish.strip():
        cmd = [
            sys.executable,
            "-m",
            "agent.__main__",
            "publish",
            "--run",
            run_id_to_publish.strip(),
            "--target",
            "both",
        ]
        return_code, stdout, stderr = run_command(cmd)
        st.subheader("Publish Output")
        st.code(stdout or "(no stdout)", language="bash")
        if stderr:
            st.error(stderr)
        if return_code == 0:
            st.success("Publish completed.")
            st.cache_data.clear()
        else:
            st.error(f"Publish failed with exit code {return_code}")
    else:
        st.warning("Enter a run_id first.")

if ref_col.button("↻ Refresh", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

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
