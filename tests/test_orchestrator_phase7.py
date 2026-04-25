from __future__ import annotations

from agent.orchestrator import run_pipeline


def test_orchestrator_calls_steps_in_order() -> None:
    calls: list[str] = []

    def do_ingest(product: str, weeks: int, week: str) -> None:
        calls.append(f"ingest:{product}:{weeks}:{week}")

    def do_cluster(run_id: str) -> None:
        calls.append(f"cluster:{run_id}")

    def do_summarize(run_id: str) -> None:
        calls.append(f"summarize:{run_id}")

    def do_render(run_id: str) -> None:
        calls.append(f"render:{run_id}")

    def do_publish(run_id: str, target: str) -> None:
        calls.append(f"publish:{run_id}:{target}")

    result = run_pipeline(
        product="groww",
        week="2026-W16",
        weeks=10,
        do_ingest=do_ingest,
        do_cluster=do_cluster,
        do_summarize=do_summarize,
        do_render=do_render,
        do_publish=do_publish,
    )
    assert result.completed is True
    assert calls[0].startswith("ingest:")
    assert calls[-1].endswith(":both")
