# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

This repo holds three things in one tree, and the lines between them matter:

1. **Live application** — `apps/carousel-agent/` is a Python pipeline (OpenAI Agents SDK) that turns recent health news into Instagram carousels for `@amarolabs`. Phases 0–5 are built; the approval gate is functional. This is real code with `pyproject.toml`, pytest, ruff, and mypy.
2. **Specification** — `specs/carousel-agent-builder/` is the source of truth for what the app is supposed to be. `specification.md`, `requirements-analysis.md`, `test-plan.md`, and `cto-review-report.md` define behavior, traceable requirement IDs (FR-/NFR-/AC-), and known deviations. **Always check the spec before designing changes** — there are CTO-issued findings (e.g. `MAJ-002`, `MIN-002`) the code is expected to honor.
3. **Reference + strategy docs** — `6.SandboxAgents.md/` (OpenAI Agents SDK reference) and `Brainstorm/` (product strategy). These are editorial — no build/test, just markdown.

Don't conflate them: a request like "add a feature" almost always means the app under `apps/carousel-agent/`, not the docs.

## Commands (apps/carousel-agent)

All commands run from `apps/carousel-agent/` unless noted.

```bash
# install
pip install -e .[dev]            # core + dev tooling
pip install -e .[dev,agents]     # + openai-agents SDK (required for pipeline.scorer/writer/formatter)

# tests
pytest                            # full suite
pytest tests/test_store.py        # single file
pytest tests/test_cli.py::test_init_creates_db   # single test
pytest --cov=carousel_agent       # with coverage

# lint / type-check
ruff check carousel_agent tests
mypy carousel_agent

# CLI (also exposed as `carousel-agent` after install)
python -m carousel_agent --help
python -m carousel_agent init                    # create .state/, SQLite DB, logs
python -m carousel_agent config show
python -m carousel_agent run --top-n 1           # Phase A: collect → render slide-1 → pause
python -m carousel_agent pending                 # list runs awaiting approval
python -m carousel_agent status r-abc123
python -m carousel_agent approve r-abc123        # Phase B: render remaining slides
python -m carousel_agent reject r-abc123 [--unconsume]
python -m carousel_agent revise r-abc123 --feedback "..."

# skill integrity (FR-005 / AC-005-1) — verify pre-existing user skills are unmodified
python -m carousel_agent.skill_integrity
python -m carousel_agent.skill_integrity --update-baseline
```

Runtime layout (relative to `project_root`, which is `cwd` or `$CAROUSEL_HOME`): `.state/carousel.db`, `.state/logs/carousel.log`, `output/<date>/<slug>/`. `.config/carousel.yaml` overrides `carousel_agent/carousel.default.yaml` if present.

## Application Architecture

The single most important architectural fact: **the pipeline is split into two phases by a human approval gate.**

- **Phase A** (`manager.run_pipeline`): collect → filter → classify → triage → for each picked item: write_script → format_visuals → **render slide-1 only** → write `preview.json` → mark run `awaiting_approval`. Stops there.
- **Phase B** (`manager.resume_on_approve` / `resume_on_reject` / `resume_on_revise`): driven by CLI subcommands. Approve renders slides 2..N + writes `metadata.json` + marks dedup. Reject keeps slide-1 for archive and marks dedup (unless `--unconsume`). Revise re-runs writer/formatter/render-slide-1 with operator feedback baked into `item.summary`, and stays `awaiting_approval`.

This is a deliberate deviation from the spec's SDK-native `needs_approval` interruption pattern. The 2-phase split achieves the same cost-gating + restart-safety (the slide-1 cost ceiling is what matters: ≤1 image API call per rejected story) without leaning on SDK interruption serialization. `manager.py`'s docstring calls this out and tags SDK-native interruption as a v1.5 refactor candidate. Don't "fix" this without reading that docstring first.

Other load-bearing pieces:

- **`pipeline/schemas.py`** — pydantic boundary types between LLM-agent stages and deterministic-Python stages (`NewsItem` → `ScoredItem` → `ClassifiedItem`; `SlideScript`; `VisualSpec`; `CarouselArtifacts`). LLM agents return these as structured outputs. Treat schema edits as breaking changes and update writer/formatter/renderer/persister together.
- **`store.py`** — SQLite with linear migrations indexed by `schema_version`. **Append-only**: never edit a historical migration; add a new tuple to `MIGRATIONS`. Tables: `runs`, `dedup`, `approvals`. Statuses are validated against `VALID_RUN_STATUSES` / `VALID_APPROVAL_DECISIONS`.
- **`renderer.py`** — calls `gpt-image-2` with `gpt-image-1` fallback; 3 retries, 2/4/8s exponential backoff, honors `Retry-After` on 429s without counting them as retries. Maps `1080x1350` → `1024x1536` for the API. `ContentPolicyBlocked` and `ImageRenderError` are distinct — a policy block is terminal, not retried.
- **`pipeline/skills.py`** — loads `~/.claude/skills/<slug>/SKILL.md`, strips YAML frontmatter, returns the body as agent `instructions=`. Three new skills (`amarolabs-news-carousel`, `neuro-carousel-writer`, `amara-news-carousel`) ship in `apps/carousel-agent/skills/` and must be copied into `~/.claude/skills/<slug>/` for the pipeline to find them.
- **`skill_integrity.py`** — guards a hard rule: pre-existing user skills (`amarolabs-news`, `carousel-style`, `neuro-scriptwriter`, etc.) **must not be modified** by this project. The baseline is `apps/carousel-agent/skill_integrity_baseline.json`. If you legitimately need to update a baseline file, run with `--update-baseline` and commit the change explicitly.
- **`config.py`** — pydantic with `extra="forbid"`; filter weights must sum to 1.0 (validator). Resolution order: CLI flag → `./.config/carousel.yaml` → packaged `carousel_agent/carousel.default.yaml`. Use `cfg.absolute_*()` accessors instead of joining paths manually.
- **`logging_setup.py`** — structured logs with `run_id` correlation. Always call `set_run_id(run_id)` at the top of any per-run async function so log lines correlate.

## Working With This Repo

- **Code changes:** spec first. Search `specs/carousel-agent-builder/specification.md` for the relevant FR/NFR/AC ID, and check `cto-review-report.md` for any `MAJ-`/`MIN-` finding that constrains the change (e.g. `MAJ-002` = `--unconsume` flag on reject; `MIN-002` = 2000-char feedback cap on revise).
- **Skills:** the pipeline depends on skills under `~/.claude/skills/`. Editing pre-existing skills is forbidden by `skill_integrity.py`. Three new skills under `apps/carousel-agent/skills/` are ours to edit; remember to re-copy them into `~/.claude/skills/` after changes (no symlink — cross-platform).
- **Approval flow:** treat `awaiting_approval` as a durable state. Phase B must be safe to run after process restart; this is why `preview.json` is written to disk in Phase A — Phase B reads it back via `manager.find_run_dir` and `_load_preview_artifacts`.
- **Reference docs (`6.SandboxAgents.md/`):** markdown with embedded HTML from OpenAI's developer docs — preserve the HTML when editing. Numbered filenames encode reading order. Don't convert OpenAI doc URLs to relative paths.
- **`Brainstorm/`:** plain markdown strategy notes. `WeekByWeekPlan.md` is the source of truth for sequencing ("what's next").
- **Repo name:** "AiAgentBuilder" reflects the broader product direction, not a single artifact. The carousel agent is the first concrete app under this banner; more may live alongside it under `apps/`.
