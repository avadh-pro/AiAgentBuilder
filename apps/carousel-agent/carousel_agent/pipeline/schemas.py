"""Pydantic schemas for inter-agent data flow.

All inputs/outputs of LLM agents are validated against these. Keeps the
boundary between LLM-judgment stages and deterministic-Python stages crisp.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Geo = Literal["IN", "GLOBAL"]


class NewsItem(BaseModel):
    url: str
    canonical_url: str
    headline: str
    summary: str = Field(max_length=2000)
    source: str
    published_at: datetime
    geo_hint: str | None = None
    negative_framing_score: float = Field(ge=0.0, le=1.0)


class ScoredItem(NewsItem):
    source_authority: float = Field(ge=0.0, le=1.0)
    impact: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)
    composite: float = Field(ge=0.0, le=1.0)


class ClassifiedItem(ScoredItem):
    geo: Geo


class Slide(BaseModel):
    index: int = Field(ge=1, le=10)
    hook: str = ""
    body: str = ""
    payoff: str = ""


class SlideScript(BaseModel):
    slides: list[Slide]
    caption: str = Field(max_length=2200)
    hashtags: list[str] = Field(min_length=3, max_length=20)


class TextOverlay(BaseModel):
    text: str
    position: Literal[
        "top", "center", "bottom", "top-left", "top-right", "bottom-left", "bottom-right"
    ]
    style: Literal["headline", "body", "citation", "sticky-note"]


class SlideVisual(BaseModel):
    index: int = Field(ge=1, le=10)
    image_prompt: str = Field(min_length=20)
    text_overlays: list[TextOverlay]
    palette: list[str] = Field(min_length=2, max_length=8)


class VisualSpec(BaseModel):
    style_token: str = "editorial-collage-v1"
    size: str = "1080x1350"
    geo: Geo
    slides: list[SlideVisual]


class CarouselArtifacts(BaseModel):
    """End-of-pipeline artifact bundle persisted to metadata.json."""
    run_id: str
    geo: Geo
    source_url: str
    headline: str
    caption: str
    hashtags: list[str]
    slides: list[str]  # filenames in run dir
    score: float
    rendered_at: datetime
    approved_at: datetime | None
    model: str
