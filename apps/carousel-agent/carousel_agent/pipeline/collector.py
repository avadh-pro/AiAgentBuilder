"""Collector — produces a list of NewsItem candidates.

v1: reads seeded items from a bundled seeds.json file. The amarolabs-news-carousel
skill markdown defines what the production behavior should be (live web search via
WebSearchTool) — that integration lands in v1.1 once we've validated the rest of
the pipeline end-to-end.

The seeds file is shaped exactly like the skill's output schema, so swapping in
real data is a one-line change.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from carousel_agent.logging_setup import get_logger
from carousel_agent.pipeline.schemas import NewsItem

log = get_logger(__name__)

_DEFAULT_SEEDS = Path(__file__).parent / "seeds.json"


def collect(window_hours: int, limit: int = 10, source: Path | None = None) -> list[NewsItem]:
    """Load and filter candidate items.

    Drops items older than `window_hours` and below the negative-framing threshold (0.4).
    """
    src = source or _DEFAULT_SEEDS
    raw = json.loads(src.read_text(encoding="utf-8"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    items: list[NewsItem] = []
    for entry in raw:
        try:
            item = NewsItem.model_validate(entry)
        except Exception as e:  # noqa: BLE001
            log.warning("dropping malformed seed item: %s", e)
            continue
        if item.published_at < cutoff:
            log.info("dropping stale item (published_at=%s): %s", item.published_at, item.headline)
            continue
        if item.negative_framing_score < 0.4:
            log.info("dropping low-negative-framing item: %s", item.headline)
            continue
        items.append(item)
        if len(items) >= limit:
            break
    log.info("collector returned %d items from %s", len(items), src)
    return items
