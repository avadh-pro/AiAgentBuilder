"""Pipeline manager — orchestrates the full collect -> approval-gate flow.

The flow is split into two phases by the approval gate:

  Phase A (run_pipeline):
    collect -> filter -> classify -> triage -> for each picked item:
      write_script -> format_visuals -> render_first_slide -> persist preview
      -> mark run as `awaiting_approval`

  Phase B (resume_after_decision):
    on `approve`: render_remaining_slides -> write metadata.json -> mark dedup
                  -> mark run as `complete`
    on `reject`:  do nothing further; mark run as `rejected`; mark dedup
    on `revise`:  re-run write_script + format_visuals + render_first_slide with
                  the operator's feedback baked in; remain `awaiting_approval`

This deviates from the spec's SDK-native `needs_approval` interruption pattern in
favor of a simpler 2-phase split. Both achieve the same functional outcome:
durable, restart-safe, cost-gated rendering. SDK-native interruption is logged
as a v1.5 refactor candidate.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from carousel_agent import store
from carousel_agent.config import Config
from carousel_agent.logging_setup import get_logger, set_run_id
from carousel_agent.pipeline import collector, formatter, persister, renderer, scorer, writer
from carousel_agent.pipeline.schemas import (
    ClassifiedItem,
    SlideScript,
    VisualSpec,
)

log = get_logger(__name__)


def _new_run_id() -> str:
    return "r-" + secrets.token_hex(6)


@dataclass
class RunOutcome:
    run_id: str
    item_url: str
    geo: str
    score: float
    out_dir: Path
    first_slide: Path


# ---- Phase A: collect -> render slide 1 -> pause ----

async def _run_for_item(item: ClassifiedItem, cfg: Config, db_path: Path) -> RunOutcome:
    run_id = _new_run_id()
    set_run_id(run_id)

    out_dir = persister.run_dir(cfg.absolute_output_dir(), item)

    # Insert run record so CLI status/pending can find it.
    with store.open_store(db_path) as conn:
        store.insert_run(
            conn,
            run_id=run_id,
            status="pending",
            item_url=item.url,
            geo=item.geo,
            score=item.composite,
        )

    # Skip already-consumed items (defense-in-depth; collector already filters).
    with store.open_store(db_path) as conn:
        if store.is_consumed(conn, item.canonical_url):
            log.info("item already consumed, skipping: %s", item.headline)
            store.update_run_status(conn, run_id, "complete")  # treat as inert
            raise _AlreadyConsumed(item.canonical_url)

    log.info("writing script...")
    script = await writer.write_script(item)
    log.info("formatting visuals...")
    spec = await formatter.format_visuals(script, item)

    persister.write_preview(out_dir, item, script, spec, run_id)

    log.info("rendering first slide (gpt-image-2)...")
    first_slide = renderer.render_first_slide(spec, out_dir, cfg)

    with store.open_store(db_path) as conn:
        store.update_run_status(conn, run_id, "awaiting_approval")

    log.info("run %s awaiting approval; first slide at %s", run_id, first_slide)
    return RunOutcome(
        run_id=run_id,
        item_url=item.url,
        geo=item.geo,
        score=item.composite,
        out_dir=out_dir,
        first_slide=first_slide,
    )


class _AlreadyConsumed(RuntimeError):
    pass


async def run_pipeline(cfg: Config, *, top_n: int | None = None) -> list[RunOutcome]:
    n = top_n or cfg.triage.top_n
    db_path = cfg.absolute_db_path()

    raw_items = collector.collect(window_hours=cfg.collection.window_hours, limit=cfg.collection.limit)

    # Drop already-consumed up front (efficiency).
    fresh: list = []
    with store.open_store(db_path) as conn:
        for it in raw_items:
            if store.is_consumed(conn, it.canonical_url):
                log.info("dedup hit at collect-time: %s", it.headline[:60])
                continue
            fresh.append(it)

    scored = await scorer.score_and_filter(fresh, cfg)
    classified = [await scorer.classify(s) for s in scored]
    picked = scorer.triage(classified, n)
    log.info("triage picked %d/%d items", len(picked), len(classified))

    outcomes: list[RunOutcome] = []
    for item in picked:
        try:
            outcomes.append(await _run_for_item(item, cfg, db_path))
        except _AlreadyConsumed:
            continue
    return outcomes


# ---- Phase B: resume after decision ----

def _load_preview_artifacts(out_dir: Path) -> tuple[ClassifiedItem, SlideScript, VisualSpec]:
    raw = persister.load_preview(out_dir)
    item = ClassifiedItem.model_validate(raw["item"])
    script = SlideScript.model_validate(raw["script"])
    spec = VisualSpec.model_validate(raw["visual_spec"])
    return item, script, spec


def find_run_dir(cfg: Config, item_url: str) -> Path | None:
    """Locate the run dir for a given item_url by scanning today's outputs."""
    base = cfg.absolute_output_dir()
    if not base.exists():
        return None
    for date_dir in sorted(base.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for run_dir in date_dir.iterdir():
            if not run_dir.is_dir():
                continue
            preview = run_dir / "preview.json"
            if not preview.exists():
                continue
            try:
                data = persister.load_preview(run_dir)
            except Exception:  # noqa: BLE001
                continue
            if data.get("item", {}).get("url") == item_url:
                return run_dir
    return None


def resume_on_approve(cfg: Config, run_id: str) -> list[Path]:
    """Phase B for an approved run: render rest, write metadata, mark dedup, complete."""
    db_path = cfg.absolute_db_path()
    set_run_id(run_id)

    with store.open_store(db_path) as conn:
        run = store.get_run(conn, run_id)
    if run is None:
        raise RuntimeError(f"run {run_id} not found")
    out_dir = find_run_dir(cfg, run["item_url"])
    if out_dir is None:
        raise RuntimeError(f"could not locate run directory for {run_id}")

    item, script, spec = _load_preview_artifacts(out_dir)
    log.info("approved; rendering remaining %d slides", len(spec.slides) - 1)
    rest = renderer.render_remaining_slides(spec, out_dir, cfg)
    all_slides = [out_dir / "slide-01.png", *rest]

    persister.write_final_metadata(
        out_dir,
        run_id=run_id,
        item=item,
        script=script,
        slide_paths=all_slides,
        rendered_at=datetime.now(timezone.utc),
        approved_at=datetime.now(timezone.utc),
        model=cfg.rendering.image_model,
    )
    persister.mark_consumed(db_path, item, run_id)

    with store.open_store(db_path) as conn:
        store.update_run_status(conn, run_id, "complete")
    log.info("run %s complete (%d slides)", run_id, len(all_slides))
    return all_slides


def resume_on_reject(cfg: Config, run_id: str, *, mark_dedup: bool = True) -> None:
    """Phase B for a rejected run: keep slide-01 for archive, mark rejected/dedup.

    If `mark_dedup` is False, also remove any existing dedup record for the
    item (per CTO MAJ-002: --unconsume flag).
    """
    db_path = cfg.absolute_db_path()
    with store.open_store(db_path) as conn:
        run = store.get_run(conn, run_id)
    if run is None:
        raise RuntimeError(f"run {run_id} not found")
    if mark_dedup:
        out_dir = find_run_dir(cfg, run["item_url"])
        if out_dir is not None:
            item, *_ = _load_preview_artifacts(out_dir)
            persister.mark_consumed(db_path, item, run_id)
    else:
        with store.open_store(db_path) as conn:
            store.unmark_consumed(conn, run["item_url"])
    with store.open_store(db_path) as conn:
        store.update_run_status(conn, run_id, "rejected")


async def resume_on_revise(cfg: Config, run_id: str, feedback: str) -> Path:
    """Phase B for a revise: re-run writer (with feedback), formatter, render slide-1.

    Returns the path to the new slide-01.png.
    """
    db_path = cfg.absolute_db_path()
    set_run_id(run_id)

    with store.open_store(db_path) as conn:
        run = store.get_run(conn, run_id)
    if run is None:
        raise RuntimeError(f"run {run_id} not found")
    out_dir = find_run_dir(cfg, run["item_url"])
    if out_dir is None:
        raise RuntimeError(f"could not locate run directory for {run_id}")

    item, _old_script, _old_spec = _load_preview_artifacts(out_dir)

    # Re-write with feedback baked in.
    item_with_feedback = item.model_copy()
    augmented_summary = (
        f"{item.summary}\n\n[OPERATOR FEEDBACK ON LAST DRAFT — incorporate]: {feedback}"
    )
    item_with_feedback = ClassifiedItem.model_validate(
        {**item.model_dump(), "summary": augmented_summary}
    )

    script = await writer.write_script(item_with_feedback)
    spec = await formatter.format_visuals(script, item)
    persister.write_preview(out_dir, item, script, spec, run_id)
    new_first = renderer.render_first_slide(spec, out_dir, cfg)

    with store.open_store(db_path) as conn:
        store.update_run_status(conn, run_id, "awaiting_approval")
    log.info("run %s revised; new slide-01 at %s", run_id, new_first)
    return new_first


# Sync wrappers for the CLI.

def run_pipeline_sync(cfg: Config, *, top_n: int | None = None) -> list[RunOutcome]:
    return asyncio.run(run_pipeline(cfg, top_n=top_n))


def resume_on_revise_sync(cfg: Config, run_id: str, feedback: str) -> Path:
    return asyncio.run(resume_on_revise(cfg, run_id, feedback))
