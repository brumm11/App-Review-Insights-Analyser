from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Annotated

import typer
from rich import print

from agent.config import ProductConfig, load_products, load_settings
from agent.ingestion.service import IngestionService
from agent.logging import bind_run_id, configure_logging
from agent.storage import (
    initialize_db,
    load_clusters_for_run,
    load_reviews_for_csv,
    load_reviews_for_run,
    load_reviews_map,
    load_run_context,
    load_run_window,
    mark_run_status,
    replace_clusters_for_run,
    update_run_metrics,
    upsert_review_embeddings,
)
from agent.types import build_run_id, current_iso_week

app = typer.Typer(help="Weekly product review pulse agent.")


def _phase_placeholder(command_name: str) -> None:
    raise typer.Exit(
        code=0,
    )


@app.callback()
def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)


@app.command("init-db")
def init_db() -> None:
    settings = load_settings()
    initialize_db(settings.db_path)
    print(f"Initialized database at [bold]{settings.db_path}[/bold]")


@app.command()
def ingest(
    product: Annotated[str, typer.Option("--product", help="Product key from products config.")],
    weeks: Annotated[int, typer.Option("--weeks", help="How many weeks to ingest")] = 10,
    week: Annotated[
        str,
        typer.Option("--week", help="ISO week like 2026-W16"),
    ] = current_iso_week(),
) -> None:
    settings = load_settings()
    initialize_db(settings.db_path)
    run_id = build_run_id(product, week)
    bind_run_id(run_id)

    products = {item.key: item for item in load_products(settings.products_path)}
    product_cfg = products.get(product, ProductConfig(key=product, display=product))

    service = IngestionService(
        db_path=settings.db_path,
        raw_dir=settings.raw_reviews_dir,
    )
    metrics = service.ingest(
        run_id=run_id,
        product_key=product,
        iso_week=week,
        weeks=weeks,
        appstore_id=product_cfg.appstore_id,
        play_package=product_cfg.play_package,
        country=settings.default_country,
    )
    print(
        "Ingestion complete: "
        f"fetched={metrics['fetched']} kept={metrics['kept']} "
        f"inserted={metrics['inserted']} updated={metrics['updated']}"
    )


@app.command()
def cluster(
    run: Annotated[str, typer.Option("--run", help="Run id to process.")],
) -> None:
    from agent.cluster_settings import from_settings
    from agent.clustering.service import ClusteringService

    settings = load_settings()
    initialize_db(settings.db_path)
    bind_run_id(run)
    run_window = load_run_window(settings.db_path, run)
    if run_window is None:
        raise typer.BadParameter(f"Unknown run id: {run}")

    product_key, start, end = run_window
    mark_run_status(
        settings.db_path,
        run_id=run,
        product_key=product_key,
        iso_week="unknown",
        window_start=start,
        window_end=end,
        status="clustering",
    )
    cluster_settings = from_settings(settings)
    reviews = load_reviews_for_run(
        settings.db_path,
        run_id=run,
        language=cluster_settings.language,
        min_chars=cluster_settings.min_chars,
    )
    result, metrics = ClusteringService(cluster_settings).cluster(run_id=run, reviews=reviews)
    upsert_review_embeddings(settings.db_path, result.embeddings)
    replace_clusters_for_run(settings.db_path, run, result.clusters)
    mark_run_status(
        settings.db_path,
        run_id=run,
        product_key=product_key,
        iso_week="unknown",
        window_start=start,
        window_end=end,
        status="clustered",
        metrics_json=(
            f'{{"input_reviews":{metrics["input_reviews"]},'
            f'"embedded_reviews":{metrics["embedded_reviews"]},'
            f'"cache_hits":{metrics["cache_hits"]},'
            f'"clusters":{len(result.clusters)}}}'
        ),
    )
    print(
        "Clustering complete: "
        f"input={metrics['input_reviews']} embedded={metrics['embedded_reviews']} "
        f"clusters={len(result.clusters)} cache_hits={metrics['cache_hits']}"
    )


@app.command()
def summarize(
    run: Annotated[str, typer.Option("--run", help="Run id to process.")],
) -> None:
    from agent.summarization.service import SummarizationService, write_summary

    settings = load_settings()
    initialize_db(settings.db_path)
    bind_run_id(run)
    os.environ["PULSE_USE_REAL_GOOGLE"] = str(settings.use_real_google).lower()
    os.environ["PULSE_GOOGLE_OAUTH_CLIENT_JSON_PATH"] = str(settings.google_oauth_client_json_path)
    os.environ["PULSE_GOOGLE_OAUTH_TOKEN_PATH"] = str(settings.google_oauth_token_path)
    if settings.gdoc_id:
        os.environ["PULSE_GDOC_ID"] = settings.gdoc_id
    context = load_run_context(settings.db_path, run)
    if context is None:
        raise typer.BadParameter(f"Unknown run id: {run}")
    product, iso_week, start, end = context
    clusters = load_clusters_for_run(settings.db_path, run)
    review_ids: set[str] = set()
    for cluster in clusters:
        ids = cluster.get("review_ids")
        if isinstance(ids, list):
            review_ids.update(str(value) for value in ids)
    reviews_by_id = load_reviews_map(settings.db_path, sorted(review_ids))
    mark_run_status(
        settings.db_path,
        run_id=run,
        product_key=product,
        iso_week=iso_week,
        window_start=start,
        window_end=end,
        status="summarizing",
    )
    service = SummarizationService(
        provider=settings.llm_provider,
        model=settings.llm_model,
        groq_api_key=settings.groq_api_key,
        max_retries=settings.llm_max_retries,
        timeout_seconds=settings.llm_timeout_seconds,
        token_cap=settings.llm_token_cap_per_run,
        cost_cap_usd=settings.llm_cost_cap_usd_per_run,
    )
    summary, metrics = service.summarize_pulse(
        product=product,
        iso_week=iso_week,
        window_start=start,
        window_end=end,
        clusters=clusters,
        reviews_by_id=reviews_by_id,
    )
    summary_path = settings.summaries_dir / f"{run}.json"
    write_summary(summary_path, summary)
    update_run_metrics(settings.db_path, run, metrics)
    mark_run_status(
        settings.db_path,
        run_id=run,
        product_key=product,
        iso_week=iso_week,
        window_start=start,
        window_end=end,
        status="summarized",
    )
    print(f"Summarization complete: wrote {summary_path}")


@app.command()
def render(
    run: Annotated[str, typer.Option("--run", help="Run id to process.")],
) -> None:
    import json

    from agent.renderer.service import load_schema, render_artifacts
    from agent.summarization.models import PulseSummary

    settings = load_settings()
    initialize_db(settings.db_path)
    bind_run_id(run)
    context = load_run_context(settings.db_path, run)
    if context is None:
        raise typer.BadParameter(f"Unknown run id: {run}")
    product, iso_week, start, end = context
    mark_run_status(
        settings.db_path,
        run_id=run,
        product_key=product,
        iso_week=iso_week,
        window_start=start,
        window_end=end,
        status="rendering",
    )
    summary_path = settings.summaries_dir / f"{run}.json"
    if not summary_path.exists():
        raise typer.BadParameter(f"Missing summary JSON: {summary_path}")
    summary = PulseSummary.model_validate(json.loads(summary_path.read_text(encoding="utf-8")))
    schema = load_schema(Path("templates/doc_section.schema.json"))
    outputs = render_artifacts(
        run_id=run,
        summary=summary,
        artifacts_dir=settings.artifacts_dir,
        schema=schema,
    )
    mark_run_status(
        settings.db_path,
        run_id=run,
        product_key=product,
        iso_week=iso_week,
        window_start=start,
        window_end=end,
        status="rendered",
    )
    print(
        "Rendering complete: wrote "
        f"{outputs['doc_requests']}, {outputs['email_html']}, "
        f"{outputs['email_text']}, {outputs['weekly_note']}"
    )


@app.command()
def publish(
    run: Annotated[str, typer.Option("--run", help="Run id to process.")],
    target: Annotated[str, typer.Option("--target", help="docs, gmail or both")] = "both",
) -> None:
    from agent.email.resend_ops import ResendEmailOps
    from agent.mcp_client.docs_ops import DocsOps
    from agent.mcp_client.gmail_ops import GmailOps
    from agent.mcp_client.session import build_sessions_with_transport
    from agent.storage import get_run_delivery

    settings = load_settings()
    initialize_db(settings.db_path)
    bind_run_id(run)
    context = load_run_context(settings.db_path, run)
    if context is None:
        raise typer.BadParameter(f"Unknown run id: {run}")
    product, iso_week, start, end = context
    docs_session, gmail_session = build_sessions_with_transport(
        docs_transport=settings.docs_mcp_transport,
        gmail_transport=settings.gmail_mcp_transport,
        state_path=settings.mcp_mock_state_path,
    )
    docs_ops = DocsOps(docs_session, settings.db_path)
    email_provider = settings.email_provider.strip().lower()
    gmail_ops = GmailOps(gmail_session, settings.db_path)
    resend_ops = ResendEmailOps(
        settings.db_path,
        api_key=settings.resend_api_key or "",
        sender=settings.resend_from,
    )

    artifacts_dir = settings.artifacts_dir / run
    doc_path = artifacts_dir / "doc_requests.json"
    html_path = artifacts_dir / "email.html"
    text_path = artifacts_dir / "email.txt"
    subject_path = artifacts_dir / "subject.txt"
    if not doc_path.exists():
        raise typer.BadParameter(f"Missing Phase 4 artifact: {doc_path}")

    deep_link = ""
    if target in {"docs", "both"}:
        mark_run_status(
            settings.db_path,
            run_id=run,
            product_key=product,
            iso_week=iso_week,
            window_start=start,
            window_end=end,
            status="publishing_docs",
        )
        docs_result = docs_ops.append_pulse_section(
            run_id=run,
            product=product,
            iso_week=iso_week,
            doc_requests_path=doc_path,
        )
        deep_link = docs_result.deep_link
        mark_run_status(
            settings.db_path,
            run_id=run,
            product_key=product,
            iso_week=iso_week,
            window_start=start,
            window_end=end,
            status="published_docs",
        )
    else:
        heading_id, _ = get_run_delivery(settings.db_path, run)
        if heading_id:
            doc_id = docs_ops.resolve_document(product)
            deep_link = f"https://docs.google.com/document/d/{doc_id}/edit#heading={heading_id}"

    if target in {"gmail", "both"}:
        products = {item.key: item for item in load_products(settings.products_path)}
        product_cfg = products.get(product)
        to = (
            product_cfg.gmail_to
            if product_cfg is not None and product_cfg.gmail_to
            else "stakeholders@example.com"
        )
        mark_run_status(
            settings.db_path,
            run_id=run,
            product_key=product,
            iso_week=iso_week,
            window_start=start,
            window_end=end,
            status="publishing_gmail",
        )
        if email_provider == "resend":
            gmail_result = resend_ops.send_pulse_email(
                run_id=run,
                to=to,
                subject_path=subject_path,
                email_html_path=html_path,
                email_text_path=text_path,
                deep_link=deep_link or "{DOC_DEEP_LINK}",
                confirm_send=settings.confirm_send,
            )
            gmail_mode = "resend"
        else:
            gmail_result = gmail_ops.send_pulse_email(
                run_id=run,
                product=product,
                to=to,
                subject_path=subject_path,
                email_html_path=html_path,
                email_text_path=text_path,
                deep_link=deep_link or "{DOC_DEEP_LINK}",
                confirm_send=settings.confirm_send,
            )
            gmail_mode = "real_google" if settings.use_real_google else "mock"
        update_run_metrics(
            settings.db_path,
            run,
            {
                "publish_target": target,
                "gmail_sent": gmail_result.sent,
                "gmail_skipped": gmail_result.skipped,
                "gmail_mode": gmail_mode,
                "gmail_to": to,
            },
        )
        mark_run_status(
            settings.db_path,
            run_id=run,
            product_key=product,
            iso_week=iso_week,
            window_start=start,
            window_end=end,
            status="published",
        )
        if gmail_result.skipped:
            print(f"Gmail publish skipped: already sent earlier for run_id={run}")
        elif gmail_result.sent:
            print(
                "Gmail publish sent: "
                f"mode={gmail_mode} to={to} message_id={gmail_result.message_id}"
            )
            if gmail_mode != "resend" and not settings.use_real_google:
                print(
                    "NOTE: This send used mock Gmail transport. "
                    "No real inbox email is delivered unless PULSE_USE_REAL_GOOGLE=true."
                )
        else:
            print(
                "Gmail publish draft-only: "
                f"mode={gmail_mode} to={to} draft_id={gmail_result.draft_id}"
            )
    print(f"Publish complete: target={target}")


@app.command("export-csv")
def export_csv(
    run: Annotated[str, typer.Option("--run", help="Run id to export.")],
    out: Annotated[
        str | None,
        typer.Option("--out", help="Output CSV path. Defaults to data/artifacts/<run>/reviews.csv"),
    ] = None,
) -> None:
    settings = load_settings()
    initialize_db(settings.db_path)
    bind_run_id(run)
    rows = load_reviews_for_csv(settings.db_path, run)
    if not rows:
        raise typer.BadParameter(f"No reviews found for run id: {run}")

    output_path = Path(out) if out else settings.artifacts_dir / run / "reviews.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "source", "rating", "title", "body", "posted_at", "language", "country"]
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV export complete: wrote {output_path}")


@app.command()
def run(
    product: Annotated[str, typer.Option("--product", help="Product key from products config.")],
    weeks: Annotated[int, typer.Option("--weeks", help="How many weeks to ingest")] = 10,
    week: Annotated[
        str,
        typer.Option("--week", help="ISO week like 2026-W16"),
    ] = current_iso_week(),
) -> None:
    from agent.orchestrator import run_pipeline

    run_id = build_run_id(product, week)
    bind_run_id(run_id)
    result = run_pipeline(
        product=product,
        week=week,
        weeks=weeks,
        do_ingest=lambda p, wks, wk: ingest(product=p, weeks=wks, week=wk),
        do_cluster=lambda rid: cluster(run=rid),
        do_summarize=lambda rid: summarize(run=rid),
        do_render=lambda rid: render(run=rid),
        do_publish=lambda rid, tgt: publish(run=rid, target=tgt),
    )
    print(f"Run complete: run_id={result.run_id} completed={result.completed}")


if __name__ == "__main__":
    app()
