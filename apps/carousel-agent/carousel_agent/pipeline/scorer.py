"""Filter (score) and Classifier (geo).

Filter: deterministic source-allowlist + LLM-judge for impact + simple novelty.
Classifier: LLM-judge that returns 'IN' or 'GLOBAL' based on event location.

Both use the openai-agents SDK so traces and structured outputs come for free.
"""

from __future__ import annotations

import re
from typing import Literal

from agents import Agent, Runner
from pydantic import BaseModel, Field

from carousel_agent.config import Config
from carousel_agent.logging_setup import get_logger
from carousel_agent.pipeline.schemas import ClassifiedItem, Geo, NewsItem, ScoredItem

log = get_logger(__name__)

# ---- source allowlist (Tiered) ----

TIER_1: dict[str, float] = {
    "who.int": 1.0,
    "icmr.gov.in": 1.0,
    "cdc.gov": 1.0,
    "fda.gov": 1.0,
    "aiims.edu": 1.0,
    "fssai.gov.in": 1.0,
    "nature.com": 1.0,
    "thelancet.com": 1.0,
    "nejm.org": 1.0,
    "bmj.com": 1.0,
    "jamanetwork.com": 1.0,
}

TIER_2: dict[str, float] = {
    "statnews.com": 0.7,
    "reuters.com": 0.7,
    "bbc.com": 0.7,
    "thehindu.com": 0.7,
    "indianexpress.com": 0.7,
    "medicalxpress.com": 0.7,
    "sciencedaily.com": 0.7,
    "businesstoday.in": 0.7,
}

TIER_3: dict[str, float] = {
    "indiatimes.com": 0.4,
    "kffhealthnews.org": 0.4,
    "medpagetoday.com": 0.4,
}


def source_authority_score(source: str) -> float:
    s = source.lower().strip()
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0]
    s = re.sub(r"^www\.", "", s)
    for table in (TIER_1, TIER_2, TIER_3):
        for domain, score in table.items():
            if s.endswith(domain):
                return score
    return 0.0


# ---- impact (LLM-judge) ----

class _ImpactResult(BaseModel):
    impact: float = Field(ge=0.0, le=1.0)


_impact_agent = Agent(
    name="impact-judge",
    instructions=(
        "You are scoring health-news items for general-audience impact on a 0.0-1.0 scale.\n"
        "0.0 = niche academic finding affecting <0.1% of any population.\n"
        "0.5 = moderate, relevant to a particular demographic or region.\n"
        "0.9-1.0 = mortality, outbreak, or product-level harm with broad consumer relevance.\n"
        "Output ONLY the JSON object {\"impact\": <number>}. No prose."
    ),
    output_type=_ImpactResult,
    model="gpt-4o-mini",
)


async def _llm_impact(item: NewsItem) -> float:
    prompt = f"HEADLINE: {item.headline}\n\nSUMMARY: {item.summary}"
    result = await Runner.run(_impact_agent, prompt)
    return result.final_output.impact


# ---- novelty (deterministic, simple) ----

def novelty_score(_item: NewsItem) -> float:
    """Simple v1: every item gets 0.8.

    The spec calls for a saturation-aware novelty score (drops to 0.2 when many
    similar topics are in dedup recently). Implementing that requires text
    similarity over the dedup table; deferring to v1.1.
    """
    return 0.8


# ---- combined filter ----

async def score_and_filter(items: list[NewsItem], cfg: Config) -> list[ScoredItem]:
    out: list[ScoredItem] = []
    for item in items:
        sa = source_authority_score(item.source)
        if sa == 0.0:
            log.info("dropping non-allowlisted source: %s (%s)", item.source, item.headline)
            continue
        impact = await _llm_impact(item)
        novelty = novelty_score(item)
        composite = (
            cfg.filter.source_authority_weight * sa
            + cfg.filter.impact_weight * impact
            + cfg.filter.novelty_weight * novelty
        )
        if composite < cfg.filter.threshold:
            log.info(
                "below threshold (%.2f < %.2f): %s",
                composite,
                cfg.filter.threshold,
                item.headline,
            )
            continue
        out.append(
            ScoredItem(
                **item.model_dump(),
                source_authority=sa,
                impact=impact,
                novelty=novelty,
                composite=composite,
            )
        )
    log.info("filter accepted %d/%d items", len(out), len(items))
    return out


# ---- classifier (geo) ----

class _GeoResult(BaseModel):
    geo: Literal["IN", "GLOBAL"]


_classifier_agent = Agent(
    name="geo-classifier",
    instructions=(
        "You are routing health-news items by event location, NOT by audience adaptation.\n"
        "Output 'IN' if the health event occurs in India (single state or pan-India).\n"
        "Output 'GLOBAL' for everything else: a single non-Indian country, multi-country, "
        "or geographically ambiguous (e.g. a global meta-analysis).\n"
        "Output ONLY the JSON object {\"geo\": \"IN\" | \"GLOBAL\"}. No prose."
    ),
    output_type=_GeoResult,
    model="gpt-4o-mini",
)


async def classify(item: ScoredItem) -> ClassifiedItem:
    prompt = (
        f"HEADLINE: {item.headline}\n\n"
        f"SUMMARY: {item.summary}\n\n"
        f"GEO HINT (free-text from collection): {item.geo_hint or 'none'}"
    )
    result = await Runner.run(_classifier_agent, prompt)
    geo: Geo = result.final_output.geo
    log.info("classified %s -> %s", item.headline[:60], geo)
    return ClassifiedItem(**item.model_dump(), geo=geo)


# ---- triage ----

def triage(items: list[ClassifiedItem], top_n: int) -> list[ClassifiedItem]:
    return sorted(items, key=lambda i: i.composite, reverse=True)[:top_n]
