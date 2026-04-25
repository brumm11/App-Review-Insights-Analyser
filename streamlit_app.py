from __future__ import annotations

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


st.set_page_config(page_title="Weekly Pulse Control Panel", layout="wide")
st.title("Weekly Product Review Pulse")
st.caption("Run and monitor pipeline jobs from Streamlit.")

with st.sidebar:
    st.subheader("Run Controls")
    product = st.selectbox("Product", ["groww", "indmoney"], index=0)
    iso_week = st.text_input("ISO week", value="2026-W16")
    weeks = st.number_input("Ingestion window weeks", min_value=1, max_value=20, value=10, step=1)
    dry_run = st.toggle("Dry-run publish (no send)", value=True)

col1, col2, col3 = st.columns(3)

if col1.button("Run Full Pipeline", use_container_width=True):
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
    st.subheader("Pipeline Output")
    st.code(stdout or "(no stdout)", language="text")
    if stderr:
        st.error(stderr)
    if return_code == 0:
        st.success(
            "Pipeline finished successfully "
            f"(PULSE_CONFIRM_SEND={env_flag} for this run)."
        )
    else:
        st.error(f"Pipeline failed with exit code {return_code}")

if col2.button("Publish Docs+Gmail", use_container_width=True):
    run_id = st.text_input("Run ID to publish", value="")
    if run_id.strip():
        cmd = [
            sys.executable,
            "-m",
            "agent.__main__",
            "publish",
            "--run",
            run_id.strip(),
            "--target",
            "both",
        ]
        return_code, stdout, stderr = run_command(cmd)
        st.subheader("Publish Output")
        st.code(stdout or "(no stdout)", language="text")
        if stderr:
            st.error(stderr)
        if return_code == 0:
            st.success("Publish completed.")
        else:
            st.error(f"Publish failed with exit code {return_code}")
    else:
        st.warning("Enter a run_id first.")

if col3.button("Refresh Run Table", use_container_width=True):
    st.rerun()

st.subheader("Recent Runs")
runs = load_recent_runs(20)
if runs:
    st.dataframe(runs, use_container_width=True)
else:
    st.info("No runs found yet. Execute a pipeline run first.")
