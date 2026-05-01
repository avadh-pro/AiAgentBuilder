"""Writer agent — bridges to the neuro-carousel-writer skill.

The skill's SKILL.md content is loaded as the agent's `instructions=`. The
agent receives the ClassifiedItem as JSON in its input and emits a SlideScript.
"""

from __future__ import annotations

import json

from agents import Agent, Runner

from carousel_agent.logging_setup import get_logger
from carousel_agent.pipeline.schemas import ClassifiedItem, SlideScript
from carousel_agent.pipeline.skills import load_skill_instructions

log = get_logger(__name__)

_SKILL_SLUG = "neuro-carousel-writer"

_writer_agent: Agent | None = None


def _agent() -> Agent:
    global _writer_agent
    if _writer_agent is None:
        instructions = load_skill_instructions(_SKILL_SLUG)
        # Append a strict-output reminder; the skill mostly says this already.
        instructions += (
            "\n\n---\n\nFINAL REMINDER: emit ONLY the SlideScript JSON object. "
            "Do not include any text before or after the JSON. "
            "Do not include markdown code fences."
        )
        _writer_agent = Agent(
            name="carousel-writer",
            instructions=instructions,
            output_type=SlideScript,
            model="gpt-4o-mini",
        )
    return _writer_agent


async def write_script(item: ClassifiedItem) -> SlideScript:
    payload = {
        "url": item.url,
        "headline": item.headline,
        "summary": item.summary,
        "source": item.source,
        "geo": item.geo,
    }
    result = await Runner.run(_agent(), json.dumps(payload))
    script = result.final_output
    if len(script.slides) < 3 or len(script.slides) > 10:
        raise ValueError(
            f"writer produced {len(script.slides)} slides; must be 3..10"
        )
    log.info("wrote %d-slide script for %s", len(script.slides), item.headline[:60])
    return script
