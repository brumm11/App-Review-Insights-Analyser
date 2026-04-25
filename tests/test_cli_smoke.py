from __future__ import annotations

from pathlib import Path
from sqlite3 import connect

from typer.testing import CliRunner

from agent.__main__ import app
from agent.storage import mark_run_status

runner = CliRunner()


def test_cli_help_lists_expected_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "init-db",
        "ingest",
        "cluster",
        "summarize",
        "render",
        "publish",
        "export-csv",
        "run",
    ):
        assert command in result.stdout


def test_init_db_creates_all_phase0_tables(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "pulse.db"
    monkeypatch.setenv("PULSE_DB_PATH", str(db_path))

    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 0
    assert db_path.exists()

    with connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {name for (name,) in rows}

    assert {"products", "reviews", "review_embeddings", "runs", "themes"} <= table_names


def test_export_csv_writes_file_for_run(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "pulse.db"
    monkeypatch.setenv("PULSE_DB_PATH", str(db_path))
    monkeypatch.setenv("PULSE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    init_result = runner.invoke(app, ["init-db"])
    assert init_result.exit_code == 0

    mark_run_status(
        db_path,
        run_id="run1",
        product_key="groww",
        iso_week="2026-W16",
        window_start="2026-04-13",
        window_end="2026-04-19",
        status="ingested",
    )
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO reviews (
                id, product_key, source, rating, title, body,
                posted_at, version, language, country, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "r1",
                "groww",
                "playstore",
                4,
                "Useful app",
                "Good investing experience overall",
                "2026-04-15T10:00:00",
                "1.0.0",
                "en",
                "IN",
                "{}",
            ),
        )
        conn.commit()

    result = runner.invoke(app, ["export-csv", "--run", "run1"])
    assert result.exit_code == 0
    output = tmp_path / "artifacts" / "run1" / "reviews.csv"
    assert output.exists()
