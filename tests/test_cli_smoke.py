from __future__ import annotations

from pathlib import Path
from sqlite3 import connect

from typer.testing import CliRunner

from agent.__main__ import app

runner = CliRunner()


def test_cli_help_lists_expected_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("init-db", "ingest", "cluster", "summarize", "render", "publish", "run"):
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
