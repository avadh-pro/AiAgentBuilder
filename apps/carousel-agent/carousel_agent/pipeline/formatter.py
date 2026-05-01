"""Formatter agent — bridges to the amara-news-carousel skill.

Translates a SlideScript into a VisualSpec ready for the renderer. The skill's
SKILL.md is loaded as the agent's instructions; the agent emits a structured
VisualSpec.
"""

from __future__ import annotations

import json

from agents import Agent, Runner

from carousel_agent.logging_setup import get_logger
from carousel_agent.pipeline.schemas import (
    ClassifiedItem,
    SlideScript,
    VisualSpec,
)
from carousel_agent.pipeline.skills import load_skill_instructions

log = get_logger(__name__)

_SKILL_SLUG = "amara-news-carousel"

_formatter_agent: Agent | None = None


def _agent() -> Agent:
    global _formatter_agent
    if _formatter_agent is None:
        instructions = load_skill_instructions(_SKILL_SLUG)
        instructions += (
            "\n\n---\n\nFINAL REMINDER: emit ONLY the VisualSpec JSON object. "
            "No prose, no markdown fences. Every slide's image_prompt MUST start "
            "with the style_preamble verbatim."
        )
        _formatter_agent = Agent(
            name="carousel-formatter",
            instructions=instructions,
            output_type=VisualSpec,
            model="gpt-4o-mini",
        )
    return _formatter_agent


async def format_visuals(script: SlideScript, item: ClassifiedItem) -> VisualSpec:
    payload = {
        "script": script.model_dump(),
        "geo": item.geo,
        "source": item.source,
    }
    result = await Runner.run(_agent(), json.dumps(payload))
    spec = result.final_output
    if len(spec.slides) != len(script.slides):
        raise ValueError(
            f"formatter slide count mismatch: script={len(script.slides)} spec={len(spec.slides)}"
        )
    # Tool-guardrail-equivalent: confirm the last slide has a citation overlay.
    last = spec.slides[-1]
    if not any(o.style == "citation" for o in last.text_overlays):
        raise ValueError("formatter omitted source citation on last slide")
    log.info("formatted %d-slide visual spec", len(spec.slides))
    return spec
