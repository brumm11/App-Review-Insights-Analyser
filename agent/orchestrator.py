from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent.types import build_run_id


@dataclass(frozen=True)
class OrchestratorResult:
    run_id: str
    completed: bool


def run_pipeline(
    *,
    product: str,
    week: str,
    weeks: int,
    do_ingest: Callable[[str, int, str], None],
    do_cluster: Callable[[str], None],
    do_summarize: Callable[[str], None],
    do_render: Callable[[str], None],
    do_publish: Callable[[str, str], None],
) -> OrchestratorResult:
    run_id = build_run_id(product, week)
    do_ingest(product, weeks, week)
    do_cluster(run_id)
    do_summarize(run_id)
    do_render(run_id)
    do_publish(run_id, "both")
    return OrchestratorResult(run_id=run_id, completed=True)
