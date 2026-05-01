"""Persister — final disk artifact + dedup bookkeeping.

After approval and remaining-slide rendering, this writes metadata.json and
marks the item as dedup-consumed.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from carousel_agent import store
from carousel_agent.logging_setup import get_logger
from carousel_agent.pipeline.schemas import (
    CarouselArtifacts,
    ClassifiedItem,
    SlideScript,
    VisualSpec,
)

log = get_logger(__name__)


def slugify(headline: str, max_len: int = 60) -> str:
    s = headline.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len] or "untitled"


def headline_hash(headline: str) -> str:
    norm = re.sub(r"\s+", " ", headline.lower().strip())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def run_dir(base_output: Path, item: ClassifiedItem) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return base_output / today / slugify(item.headline)


def write_preview(
    out_dir: Path,
    item: ClassifiedItem,
    script: SlideScript,
    spec: VisualSpec,
    run_id: str,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    preview = {
        "run_id": run_id,
        "item": item.model_dump(mode="json"),
        "script": script.model_dump(),
        "visual_spec": spec.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    p = out_dir / "preview.json"
    p.write_text(json.dumps(preview, indent=2, default=str), encoding="utf-8")
    return p


def load_preview(out_dir: Path) -> dict:
    return json.loads((out_dir / "preview.json").read_text(encoding="utf-8"))


def write_final_metadata(
    out_dir: Path,
    *,
    run_id: str,
    item: ClassifiedItem,
    script: SlideScript,
    slide_paths: list[Path],
    rendered_at: datetime,
    approved_at: datetime,
    model: str,
) -> Path:
    artifacts = CarouselArtifacts(
        run_id=run_id,
        geo=item.geo,
        source_url=item.url,
        headline=item.headline,
        caption=script.caption,
        hashtags=script.hashtags,
        slides=[p.name for p in slide_paths],
        score=item.composite,
        rendered_at=rendered_at,
        approved_at=approved_at,
        model=model,
    )
    p = out_dir / "metadata.json"
    p.write_text(
        json.dumps(artifacts.model_dump(mode="json"), indent=2, default=str),
        encoding="utf-8",
    )
    log.info("wrote metadata.json (%d slides) to %s", len(slide_paths), p)
    return p


def mark_consumed(db_path: Path, item: ClassifiedItem, run_id: str) -> None:
    with store.open_store(db_path) as conn:
        store.mark_consumed(
            conn,
            canonical_url=item.canonical_url,
            headline_hash=headline_hash(item.headline),
            run_id=run_id,
        )
