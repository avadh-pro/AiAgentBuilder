"""CLI surface for carousel-agent.

All subcommands are wired so argument parsing is correct from day 1. Pipeline
stages (Phase 3+) raise NotImplementedError until implemented; commands that
only touch state/store (init, pending, status) are functional now.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from carousel_agent import __version__, config, logging_setup, paths, store

NOT_IMPLEMENTED_EXIT = 64


def _load_cfg(config_path: Path | None) -> config.Config:
    return config.load_config_or_defaults(config_path)


def _bootstrap(ctx: click.Context) -> config.Config:
    cfg: config.Config = ctx.obj["config"]
    paths.ensure_runtime_dirs()
    logging_setup.setup_logging(level=cfg.logging.level, file_path=cfg.absolute_log_file())
    logging_setup.quiet_noisy_loggers()
    return cfg


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="carousel-agent")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
    default=None,
    help="Path to a YAML config file. Defaults to ./.config/carousel.yaml or packaged defaults.",
)
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None) -> None:
    """Health-news -> Instagram carousel pipeline for @amarolabs."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = _load_cfg(config_path)


# ---------- init ----------

@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize the local state directory and SQLite DB. Idempotent."""
    cfg = _bootstrap(ctx)
    paths.ensure_runtime_dirs()
    db = store.init_db(cfg.absolute_db_path())
    click.echo(f"State directory: {paths.state_dir()}")
    click.echo(f"Database:        {db}")
    click.echo(f"Logs:            {cfg.absolute_log_file()}")
    click.echo("OK")


# ---------- config ----------

@cli.group()
def config_cmd() -> None:
    """Inspect or validate the active configuration."""


cli.add_command(config_cmd, name="config")


@config_cmd.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    cfg: config.Config = ctx.obj["config"]
    click.echo(json.dumps(cfg.model_dump(), indent=2, sort_keys=True))


@config_cmd.command("path")
@click.pass_context
def config_path_cmd(ctx: click.Context) -> None:
    """Show which config file is being used."""
    explicit = ctx.parent.params.get("config_path") if ctx.parent else None  # type: ignore[union-attr]
    target = config.resolve_config_path(explicit)
    click.echo(str(target))


# ---------- run ----------

@cli.command("run")
@click.option("--top-n", "top_n", type=int, default=None, help="Override config triage.top_n.")
@click.pass_context
def run_cmd(ctx: click.Context, top_n: int | None) -> None:
    """Run the collection -> approval-gate pipeline (Phase A)."""
    cfg = _bootstrap(ctx)
    from carousel_agent.pipeline import manager

    outcomes = manager.run_pipeline_sync(cfg, top_n=top_n)
    if not outcomes:
        click.echo("no items selected for rendering this run.")
        return
    click.echo(f"created {len(outcomes)} run(s) awaiting approval:\n")
    for o in outcomes:
        click.echo(f"  run_id      {o.run_id}")
        click.echo(f"  geo         {o.geo}")
        click.echo(f"  score       {o.score:.3f}")
        click.echo(f"  first slide {o.first_slide}")
        click.echo(f"  approve via 'carousel-agent approve {o.run_id}'\n")


# ---------- pending / status ----------

def _print_run_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        click.echo("(no runs)")
        return
    click.echo(f"{'RUN_ID':<28} {'STATUS':<20} {'GEO':<8} {'CREATED':<32}")
    for r in rows:
        click.echo(
            f"{r['run_id']:<28} {r['status']:<20} {(r['geo'] or '-'):<8} {r['created_at']:<32}"
        )


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Emit JSON for scripting.")
@click.pass_context
def pending(ctx: click.Context, as_json: bool) -> None:
    """List runs awaiting approval."""
    cfg = _bootstrap(ctx)
    with store.open_store(cfg.absolute_db_path()) as conn:
        rows = store.list_runs_by_status(conn, "awaiting_approval")
    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
    else:
        _print_run_table(rows)


@cli.command()
@click.argument("run_id")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON for scripting.")
@click.pass_context
def status(ctx: click.Context, run_id: str, as_json: bool) -> None:
    """Show details for a specific run."""
    cfg = _bootstrap(ctx)
    with store.open_store(cfg.absolute_db_path()) as conn:
        run = store.get_run(conn, run_id)
        approval = store.get_approval(conn, run_id)
    if run is None:
        click.echo(f"run not found: {run_id}", err=True)
        sys.exit(2)
    payload = {"run": run, "approval": approval}
    if as_json:
        click.echo(json.dumps(payload, indent=2, default=str))
    else:
        click.echo(f"run_id     {run['run_id']}")
        click.echo(f"status     {run['status']}")
        click.echo(f"item_url   {run['item_url']}")
        click.echo(f"geo        {run['geo'] or '-'}")
        click.echo(f"score      {run['score']}")
        click.echo(f"created    {run['created_at']}")
        click.echo(f"updated    {run['updated_at']}")
        if approval is not None:
            click.echo(f"decision   {approval['decision']}")
            click.echo(f"decided_by {approval['decided_by'] or '-'}")
            click.echo(f"decided_at {approval['decided_at']}")
            if approval["feedback"]:
                click.echo(f"feedback   {approval['feedback']}")


# ---------- approve / reject / revise ----------

def _record_decision(
    cfg: config.Config,
    run_id: str,
    decision: str,
    feedback: str | None = None,
) -> None:
    db = cfg.absolute_db_path()
    with store.open_store(db) as conn:
        run = store.get_run(conn, run_id)
        if run is None:
            click.echo(f"run not found: {run_id}", err=True)
            sys.exit(2)
        if run["status"] != "awaiting_approval":
            click.echo(
                f"run {run_id} is in status {run['status']!r}, not awaiting_approval",
                err=True,
            )
            sys.exit(2)
        store.record_approval(conn, run_id, decision, feedback=feedback, decided_by="cli")
        # NOTE: we record the decision; actually resuming the SDK pipeline is Phase 4.
        click.echo(f"decision recorded: {decision} for {run_id}")
        click.echo("(pipeline resume on approve/revise lands in Phase 4.)")


@cli.command()
@click.argument("run_id")
@click.pass_context
def approve(ctx: click.Context, run_id: str) -> None:
    """Approve the first slide and render the remaining slides."""
    cfg = _bootstrap(ctx)
    _record_decision(cfg, run_id, "approve")
    from carousel_agent.pipeline import manager

    paths_rendered = manager.resume_on_approve(cfg, run_id)
    click.echo(f"rendered {len(paths_rendered)} total slides for run {run_id}")
    for p in paths_rendered:
        click.echo(f"  {p}")


@cli.command()
@click.argument("run_id")
@click.option(
    "--unconsume",
    is_flag=True,
    help="Remove the dedup record so this item can be considered again later (per CTO MAJ-002).",
)
@click.pass_context
def reject(ctx: click.Context, run_id: str, unconsume: bool) -> None:
    """Reject the first slide; carousel is dropped."""
    cfg = _bootstrap(ctx)
    _record_decision(cfg, run_id, "reject")
    from carousel_agent.pipeline import manager

    manager.resume_on_reject(cfg, run_id, mark_dedup=not unconsume)
    if unconsume:
        click.echo("rejected; item NOT marked dedup-consumed (will be re-considered later)")
    else:
        click.echo("rejected; item marked dedup-consumed")


@cli.command()
@click.argument("run_id")
@click.option("--feedback", required=True, help="Feedback to pass to the writer for the rerun.")
@click.pass_context
def revise(ctx: click.Context, run_id: str, feedback: str) -> None:
    """Send feedback and re-render the first slide (Phase 4)."""
    if len(feedback) > 2000:
        click.echo("feedback exceeds 2000 chars (CTO MIN-002)", err=True)
        sys.exit(2)
    cfg = _bootstrap(ctx)
    _record_decision(cfg, run_id, "revise", feedback=feedback)
    from carousel_agent.pipeline import manager

    new_first = manager.resume_on_revise_sync(cfg, run_id, feedback)
    click.echo(f"new slide-01 rendered: {new_first}")
    click.echo(f"approve via 'carousel-agent approve {run_id}' or revise again")


# ---------- retry ----------

@cli.command()
@click.argument("run_id")
@click.pass_context
def retry(ctx: click.Context, run_id: str) -> None:
    """Retry an errored run (Phase 5)."""
    _bootstrap(ctx)
    click.echo(f"retry not yet implemented (Phase 5). run_id={run_id}")
    sys.exit(NOT_IMPLEMENTED_EXIT)


if __name__ == "__main__":
    cli()
