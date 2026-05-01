"""End-to-end pipeline test with mocked LLM + image API.

Exercises ITS-001 (happy path — single India item) and ITS-003 (reject path)
from the test plan. Real OpenAI calls are stubbed so this runs in CI without
network or cost.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from carousel_agent import cli as cli_module
from carousel_agent import store
from carousel_agent.pipeline.schemas import (
    ClassifiedItem,
    NewsItem,
    Slide,
    SlideScript,
    SlideVisual,
    TextOverlay,
    VisualSpec,
)


def _seed_news_item() -> NewsItem:
    return NewsItem(
        url="https://example.test/x",
        canonical_url="https://example.test/x",
        headline="Test family of four dies after watermelon in Mumbai",
        summary="Test summary describing the event in Mumbai with health implications.",
        source="who.int",
        published_at=datetime.now(timezone.utc),
        geo_hint="Mumbai, India",
        negative_framing_score=0.9,
    )


def _classified(item: NewsItem) -> ClassifiedItem:
    return ClassifiedItem(
        **item.model_dump(),
        source_authority=1.0,
        impact=0.85,
        novelty=0.8,
        composite=0.91,
        geo="IN",
    )


def _script() -> SlideScript:
    return SlideScript(
        slides=[
            Slide(index=1, hook="Test hook on slide 1.", body="", payoff=""),
            Slide(index=2, hook="", body="Test body slide 2.", payoff=""),
            Slide(index=3, hook="", body="Test body slide 3.", payoff=""),
            Slide(index=4, hook="", body="Test body slide 4.", payoff=""),
            Slide(index=5, hook="", body="Test body slide 5.", payoff="Source: {{source}}"),
        ],
        caption="Test caption for the carousel describing the finding.",
        hashtags=["#publichealth", "#healthnews", "#amarolabs"],
    )


def _visual_spec() -> VisualSpec:
    preamble = "Editorial collage. Test preamble for prompt consistency."
    slides = [
        SlideVisual(
            index=i,
            image_prompt=f"{preamble}. Slide {i}.",
            text_overlays=[
                TextOverlay(text=f"slide {i} overlay", position="center", style="headline" if i == 1 else "body")
            ],
            palette=["#0f172a", "#f5f5dc", "#14b8a6", "#f59e0b"],
        )
        for i in range(1, 6)
    ]
    # Last slide gets a citation overlay, as required by formatter validation
    slides[-1].text_overlays.append(
        TextOverlay(text="Source: who.int", position="bottom", style="citation")
    )
    return VisualSpec(geo="IN", slides=slides)


@pytest.fixture()
def patched_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Patch every external boundary so the pipeline runs offline."""
    from carousel_agent.pipeline import collector, formatter, manager, renderer, scorer, writer
    from carousel_agent.pipeline.schemas import ScoredItem

    def fake_collect(window_hours, limit=10, source=None):
        return [_seed_news_item()]

    async def fake_score(items, cfg):
        return [
            ScoredItem(
                **i.model_dump(),
                source_authority=1.0,
                impact=0.85,
                novelty=0.8,
                composite=0.91,
            )
            for i in items
        ]

    async def fake_classify(item):
        return ClassifiedItem(**item.model_dump(), geo="IN")

    async def fake_write_script(item):
        return _script()

    async def fake_format_visuals(script, item):
        return _visual_spec()

    def fake_render_slide(slide, spec, out_dir, cfg, *, use_fallback=False):
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = out_dir / f"slide-{slide.index:02d}.png"
        fname.write_bytes(b"\x89PNG\r\n\x1a\n" + b"FAKE")
        return fname

    def fake_render_first(spec, out_dir, cfg):
        return fake_render_slide(spec.slides[0], spec, out_dir, cfg)

    def fake_render_rest(spec, out_dir, cfg):
        return [fake_render_slide(s, spec, out_dir, cfg) for s in spec.slides[1:]]

    # Patch at usage sites — manager imports these names directly.
    monkeypatch.setattr(collector, "collect", fake_collect)
    monkeypatch.setattr(scorer, "score_and_filter", fake_score)
    monkeypatch.setattr(scorer, "classify", fake_classify)
    monkeypatch.setattr(writer, "write_script", fake_write_script)
    monkeypatch.setattr(formatter, "format_visuals", fake_format_visuals)
    monkeypatch.setattr(renderer, "render_first_slide", fake_render_first)
    monkeypatch.setattr(renderer, "render_remaining_slides", fake_render_rest)


@pytest.fixture()
def runner_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("CAROUSEL_HOME", str(tmp_path))
    return CliRunner()


def test_e2e_happy_path_approve(runner_in_tmp: CliRunner, tmp_path: Path, patched_pipeline):
    """ITS-001: run -> awaiting_approval -> approve -> all 5 slides + metadata.json."""
    runner_in_tmp.invoke(cli_module.cli, ["init"])

    result = runner_in_tmp.invoke(cli_module.cli, ["run"])
    assert result.exit_code == 0, result.output
    assert "awaiting approval" in result.output

    db = tmp_path / ".state" / "carousel.db"
    with store.open_store(db) as conn:
        rows = store.list_runs_by_status(conn, "awaiting_approval")
    assert len(rows) == 1
    run_id = rows[0]["run_id"]

    # First slide on disk; rest absent.
    output_root = tmp_path / "output"
    date_dirs = list(output_root.iterdir())
    assert len(date_dirs) == 1
    run_dir = next(date_dirs[0].iterdir())
    assert (run_dir / "slide-01.png").exists()
    assert not (run_dir / "slide-02.png").exists()
    assert (run_dir / "preview.json").exists()

    # Approve
    result2 = runner_in_tmp.invoke(cli_module.cli, ["approve", run_id])
    assert result2.exit_code == 0, result2.output
    assert "rendered 5 total slides" in result2.output

    # All slides + metadata
    for i in range(1, 6):
        assert (run_dir / f"slide-{i:02d}.png").exists()
    assert (run_dir / "metadata.json").exists()

    with store.open_store(db) as conn:
        run = store.get_run(conn, run_id)
        assert run is not None and run["status"] == "complete"
        assert store.is_consumed(conn, "https://example.test/x")


def test_e2e_reject_keeps_only_first_slide(runner_in_tmp: CliRunner, tmp_path: Path, patched_pipeline):
    """ITS-003: rejection keeps only slide-01 and never renders the rest."""
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    runner_in_tmp.invoke(cli_module.cli, ["run"])

    db = tmp_path / ".state" / "carousel.db"
    with store.open_store(db) as conn:
        rows = store.list_runs_by_status(conn, "awaiting_approval")
    run_id = rows[0]["run_id"]

    result = runner_in_tmp.invoke(cli_module.cli, ["reject", run_id])
    assert result.exit_code == 0, result.output

    output_root = tmp_path / "output"
    run_dir = next(next(output_root.iterdir()).iterdir())
    assert (run_dir / "slide-01.png").exists()
    assert not (run_dir / "slide-02.png").exists()
    assert not (run_dir / "metadata.json").exists()

    with store.open_store(db) as conn:
        run = store.get_run(conn, run_id)
        assert run is not None and run["status"] == "rejected"
        # Default behavior: marked dedup-consumed.
        assert store.is_consumed(conn, "https://example.test/x")


def test_e2e_dedup_blocks_rerun(runner_in_tmp: CliRunner, tmp_path: Path, patched_pipeline):
    """ITS-006: same item processed twice -> second run finds nothing."""
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    runner_in_tmp.invoke(cli_module.cli, ["run"])

    db = tmp_path / ".state" / "carousel.db"
    with store.open_store(db) as conn:
        rows = store.list_runs_by_status(conn, "awaiting_approval")
    run_id = rows[0]["run_id"]
    runner_in_tmp.invoke(cli_module.cli, ["approve", run_id])

    # Second run should find no fresh items.
    result = runner_in_tmp.invoke(cli_module.cli, ["run"])
    assert result.exit_code == 0
    assert "no items selected" in result.output
