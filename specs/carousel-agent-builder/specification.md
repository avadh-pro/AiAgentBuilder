# Specification: Carousel Agent Builder

**Version:** 1.0
**Status:** DRAFT — awaiting CTO Review
**Author:** system-architect (executed by Claude Code)
**Date:** 2026-05-01

**Related Documents:**
- [requirements-analysis.md](./requirements-analysis.md)
- [test-plan.md](./test-plan.md)
- [cto-review-report.md](./cto-review-report.md)

---

## Executive Summary

The **Carousel Agent Builder** is a Python pipeline built on the OpenAI Agents SDK that turns recent (≤72h), credible, high-impact, negative-framed health news into Instagram carousels styled for the @amarolabs feed. It runs daily on schedule (and on-demand via CLI), produces a single first-slide preview per selected story, and pauses for human approval before paying the cost of rendering the rest of the carousel.

The system is composed of SDK-native agents arranged as a manager-with-tools pipeline, three new Claude skills (`amarolabs-news-carousel`, `neuro-carousel-writer`, `amara-news-carousel`), and an SQLite-backed dedup + run-state store. Existing skills are invoked unchanged. Image rendering uses `gpt-image-2`.

The architecture exploits two SDK features specifically: **human-in-the-loop interruptions** for the first-slide approval gate (so approvals can occur asynchronously, days later) and **agents-as-tools** orchestration (so the pipeline manager retains synthesis control rather than handing off the user-facing reply).

---

## 1. Objectives and Success Criteria

### 1.1 Primary Objectives
1. Surface fresh, credible, negative-framed health stories suitable for an @amarolabs Instagram carousel — without manual research.
2. Produce one carousel asset per approved story, end-to-end (script → visual spec → images → caption + metadata).
3. Spend image-API budget only on stories the operator explicitly approves.
4. Preserve full provenance (source URL, trace, intermediate artifacts) for editorial review.

### 1.2 Success Criteria
See [test-plan.md §8](./test-plan.md). In particular: cost-gating works (≤1 image API call per rejected story), approval survives process restart, all three new skills validate against schema.

### 1.3 Non-Goals (v1)
- Posting carousels to Instagram (operator does this manually from disk artifacts)
- Telegram / Slack approval channels (CLI only)
- Multi-account / multi-tenant
- Performance under high load (>10 stories/day)
- Voice or video output
- Web dashboard
- Automatic A/B testing of carousel variants

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       carousel_agent (Python)                         │
│                                                                       │
│   ┌────────────┐   ┌──────────────┐   ┌───────────────┐              │
│   │  Scheduler │──▶│  Pipeline    │──▶│   State /     │              │
│   │  / CLI     │   │  Manager     │   │   Dedup DB    │              │
│   └────────────┘   │  (Agent)     │   │   (SQLite)    │              │
│                    └──────┬───────┘   └───────────────┘              │
│                           │                                           │
│                           │ agents-as-tools                           │
│                           ▼                                           │
│   ┌─────────────────────────────────────────────────────────┐        │
│   │                                                          │        │
│   │   Collector ──▶ Filter ──▶ Classifier ──▶ Triage         │        │
│   │      │                                       │           │        │
│   │      │                                       ▼           │        │
│   │      │                                    Writer         │        │
│   │      │                                       │           │        │
│   │      │                                       ▼           │        │
│   │      │                                  Formatter        │        │
│   │      │                                       │           │        │
│   │      │                                       ▼           │        │
│   │      │                                 Renderer ─┐       │        │
│   │      │                                           │       │        │
│   │      │            ┌──────────────────────────────┘       │        │
│   │      │            │                                       │        │
│   │      │            ▼  (slide 1 only)                       │        │
│   │      │     ┌──────────────────┐                           │        │
│   │      │     │  APPROVAL GATE   │  needs_approval=True      │        │
│   │      │     │  (interruption)  │  state serialized to disk │        │
│   │      │     └──────────────────┘                           │        │
│   │      │            │                                       │        │
│   │      │   approve  │  reject / revise                      │        │
│   │      │            ▼                                       │        │
│   │      │     Renderer (slides 2..N)                         │        │
│   │      │            │                                       │        │
│   │      │            ▼                                       │        │
│   │      │      Persister                                     │        │
│   │      └─────▶  output/<date>/<slug>/                       │        │
│   │                  ├── slide-01.png ... slide-NN.png        │        │
│   │                  ├── preview.json                         │        │
│   │                  └── metadata.json                        │        │
│   └─────────────────────────────────────────────────────────┘        │
│                                                                       │
│   External calls:                                                     │
│     • amarolabs-news-carousel skill  (collection)                    │
│     • neuro-carousel-writer skill    (script)                        │
│     • amara-news-carousel skill      (visual spec)                   │
│     • OpenAI Image API: gpt-image-2  (rendering)                     │
│     • OpenAI tracing dashboard       (observability)                 │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Overview

| Component | Responsibility | Technology |
|-----------|----------------|------------|
| **Pipeline Manager** | Top-level Agent. Orchestrates child agents as tools. Owns approval state. | `Agent` from `openai-agents` |
| **Collector Agent** | Calls `amarolabs-news-carousel` skill; normalizes items. | Agent + tool |
| **Filter Agent** | Computes credibility/impact/novelty composite score; drops below-threshold. | Agent (LLM-judge for impact) + deterministic allowlist |
| **Classifier Agent** | Determines `geo ∈ {IN, GLOBAL}` from event location. | Agent (LLM-judge, temperature=0) |
| **Triage Agent** | Picks top-N items by score for rendering. | Deterministic + LLM tiebreak |
| **Writer Agent** | Calls `neuro-carousel-writer` skill; outputs slide-wise script. | Agent + skill bridge |
| **Formatter Agent** | Calls `amara-news-carousel` skill; emits per-slide visual spec. | Agent + skill bridge |
| **Renderer** | Calls `gpt-image-2` API; writes PNG to disk. | Plain Python (no LLM) |
| **Persister** | Writes `metadata.json`, marks dedup. | Plain Python |
| **State / Dedup Store** | SQLite. Tables: `runs`, `dedup`, `approvals`. | sqlite3 |
| **CLI** | `run`, `approve`, `reject`, `revise`, `pending`, `status`, `retry`. | `click` |

### 2.3 Key Design Decisions

#### Decision 1: Agents-as-tools (NOT handoffs) for the pipeline
**Context:** The pipeline has clear sequential stages (collect → ... → render). The SDK offers two orchestration patterns: handoffs (specialist owns next reply) vs. agents-as-tools (manager calls specialists as helpers).
**Options considered:**
- A. Handoffs — Collector hands off to Filter, ... ; each agent owns the conversation in turn.
- B. Agents-as-tools — Pipeline Manager calls each stage as a tool, retains control.
- C. Plain function calls — skip Agents entirely for non-LLM stages.
**Decision:** **B (agents-as-tools)** for stages that benefit from LLM judgment (Classifier, Writer, Formatter, Filter's impact scorer). Triage's tiebreak, Renderer, and Persister are plain Python functions exposed as tools. The manager owns run state.
**Rationale:** Handoffs would scatter run-state ownership across agents and complicate the approval gate (the approving agent and the resuming agent must share state). Agents-as-tools keeps the manager as the single coordinator. Per docs §7, agents-as-tools is the recommended pattern when "the manager synthesizes the final answer; the specialist is a bounded task."
**Consequences:** Manager carries the full pipeline context. Acceptable.

#### Decision 2: Approval gate via SDK interruptions, not a separate queue service
**Context:** First-slide approval can happen hours/days later. Need durable state surviving restarts.
**Options:**
- A. SDK `needs_approval=True` interruption + serialize `state` to disk.
- B. Custom pause/resume queue (e.g., Redis + worker).
- C. Synchronous wait (block process for human input).
**Decision:** **A.** The SDK already provides `interruptions` and a serializable `state` snapshot designed exactly for this case (per docs §8 and §9). The approval CLI command reads state from disk and resumes via `Runner.run` with the loaded state.
**Rationale:** Building a custom queue is a 5× expansion of scope reinventing what the SDK gives free. The `Brainstorm/1stSession.md` analysis specifically calls out interruption + serialization as the production-critical pattern.
**Consequences:** State serialization format is the SDK's; if the SDK changes its state schema, we may need a migration shim. Accepted.

#### Decision 3: Tool-level guardrails on Renderer (not input guardrails)
**Context:** Need to ensure (a) source attribution renders on slides, (b) renderer never runs unapproved (budget guard).
**Options:** input guardrail on Pipeline Manager | tool guardrail wrapping Renderer | both.
**Decision:** **Tool guardrails on Renderer** for both attribution and budget.
**Rationale:** Per docs §8 (and explicitly flagged in `Brainstorm/1stSession.md`), input guardrails fire only on the *first* agent in a chain — they would not catch a sub-agent invoking a tool. Tool guardrails fire every time the renderer is invoked, regardless of who called it. This is the right boundary.
**Consequences:** Two small guardrail functions on the renderer tool. Trivial.

#### Decision 4: SQLite for state + dedup (not Postgres or in-memory)
**Decision:** **SQLite** — single file, transactional, sufficient for ≤10 runs/day.
**Rationale:** Postgres is over-spec'd for one operator. JSON files require manual locking. In-memory loses state on crash. SQLite is the proportionate choice.
**Consequences:** A `Store` interface defined now allows future swap if multi-operator becomes a real requirement.

#### Decision 5: No sandbox agents
**Decision:** **No.** Pipeline does no shell execution, no untrusted code, no LLM-driven file mutation.
**Rationale:** Sandbox (docs §6) is for agents that need a Unix-like execution environment. We don't.
**Consequences:** None. Easier deploy.

#### Decision 6: Caption + hashtags inside `neuro-carousel-writer` (not a separate stage)
**Decision:** Bundle caption + hashtags into `neuro-carousel-writer` output schema.
**Rationale:** Writer already has the full slide-wise script and emotional framing. Splitting introduces context-passing overhead and a second LLM call for no quality gain. Trivial to split later.

#### Decision 7: Local-history conversation strategy for the manager
**Context:** Per docs §5, the SDK supports four conversation strategies (local history, sessions, conversationId, response IDs).
**Decision:** **Local history.** Pipeline Manager passes the full message list each turn.
**Rationale:** Run is short-lived; we already serialize full state across the approval gate (Decision 2). Sessions/conversationId would duplicate that mechanism.

---

## 3. Detailed Design

### 3.1 Pipeline Manager (Agent)

**Purpose:** Top-level orchestrator. Owns the run lifecycle.

**Instructions (sketch):**
> You are the carousel pipeline manager for @amarolabs. For each run:
> 1. Call `collect_news` to fetch fresh items.
> 2. For each item, call `score_filter`. Drop below-threshold items.
> 3. For each surviving item, call `classify_geo`.
> 4. Call `triage` to pick the top item(s).
> 5. For each picked item: call `write_script`, then `format_visuals`, then `render_first_slide`. Then **pause for approval** (return `needs_approval`).
> 6. After approval: call `render_remaining_slides`, `persist`, mark dedup.
> Never invoke `render_*` without correct approval state. Never mutate items between stages.

**Tools:**
- `collect_news() -> List[NewsItem]`
- `score_filter(items: List[NewsItem]) -> List[ScoredItem]`
- `classify_geo(item: ScoredItem) -> ClassifiedItem`
- `triage(items: List[ClassifiedItem], top_n: int) -> List[ClassifiedItem]`
- `write_script(item: ClassifiedItem) -> SlideScript`  *(calls `neuro-carousel-writer`)*
- `format_visuals(script: SlideScript) -> VisualSpec`  *(calls `amara-news-carousel`)*
- `render_first_slide(spec: VisualSpec, run_id: str) -> Path`  *(guarded: must be the first render call for this run_id)*
- `render_remaining_slides(spec: VisualSpec, run_id: str) -> List[Path]`  *(guarded: requires `approvals.decision == "approve"`)*
- `persist(run_id: str, ...) -> None`

**Guardrails:**
- *Input guardrail (CLI input only):* Validate CLI flags (`--since 99h` rejected, etc.). Per docs §8, input guardrails fire on first agent — exactly right for CLI input validation.
- *Tool guardrail on `render_first_slide`:* Verify VisualSpec last slide includes a source-citation slot before rendering.
- *Tool guardrail on `render_remaining_slides`:* Verify `state.approval(run_id) == "approved"`. Raise otherwise.

### 3.2 Collector Agent

**Behavior:**
1. Invoke `amarolabs-news-carousel` skill via the Python harness's skill bridge.
2. Validate output: each item has `url`, `headline`, `published_at`, `source`, `summary`.
3. Defensively re-check `published_at` against window (defense-in-depth; skill should already filter).
4. Drop items already in `dedup` table.
5. Return remaining items.

**Output:** `List[NewsItem]`.

### 3.3 Filter Agent

**Algorithm (deterministic + LLM-judge hybrid):**
- `source_authority`: lookup in allowlist YAML.
  - Tier 1 (1.0): peer-reviewed journals (Nature, Lancet, NEJM, BMJ, JAMA), WHO, ICMR, CDC, AIIMS
  - Tier 2 (0.7): major health outlets (STAT, The Hindu Health, Reuters Health, BBC Health)
  - Tier 3 (0.4): regional outlets
  - Unknown (0.0): drop
- `impact`: LLM-judge prompt at temperature=0 — "On a 0–1 scale, how high-impact is this story for a general health-conscious audience?"
- `novelty`: 1.0 minus social-saturation. v1 simplistic — count of recent identical-topic items in dedup store within last 7 days; >5 → 0.2, ≤2 → 1.0.
- `composite = 0.4 * source_authority + 0.4 * impact + 0.2 * novelty`
- Threshold: configurable, default 0.55.

**Output:** `List[ScoredItem]` where `composite >= threshold`.

### 3.4 Classifier Agent

LLM-judge prompt at temperature=0:
> Read the news item. Where does the health event occur? Reply with exactly one token: `IN` if the event is located in India (single-state or pan-India), `GLOBAL` for any other case (single non-Indian country, multi-country, or geographically ambiguous).

Validation: if response not in `{IN, GLOBAL}`, default to `GLOBAL` and log warning.

### 3.5 Triage Agent

Deterministic sort by composite score; LLM tiebreak ("which would make a more emotionally resonant carousel?") only when scores are within 0.02.

### 3.6 Writer Agent

Skill bridge: invoke `neuro-carousel-writer` with the ClassifiedItem. Validate output against schema (§5.2). Pass through.

### 3.7 Formatter Agent

Skill bridge: invoke `amara-news-carousel` with the SlideScript. Validate output (§5.3).

### 3.8 Renderer

Plain Python. **First-slide path:**
1. Take VisualSpec, extract slide-1 prompt + style anchors.
2. Call `client.images.generate(model="gpt-image-2", prompt=..., size="1080x1350", n=1)`.
3. Save PNG to `output/<date>/<slug>/slide-01.png`.
4. Save full SlideScript + VisualSpec to `preview.json`.
5. Return path.

**Remaining slides path:**
1. For each slide 2..N: same generate call with the style preamble that ensures `gpt-image-2`'s multi-image-consistency keeps the look coherent.
2. Save each PNG.

**Retry policy:** 3 retries, exponential backoff (2s, 4s, 8s). Honor `Retry-After` for 429s. On final failure, raise; manager catches and marks run `errored` without consuming dedup.

### 3.9 Persister

1. Write `metadata.json`:
   ```json
   {
     "run_id": "...",
     "geo": "IN",
     "source_url": "...",
     "headline": "...",
     "caption": "...",
     "hashtags": ["..."],
     "slides": ["slide-01.png", "..."],
     "score": 0.78,
     "rendered_at": "2026-05-01T07:14:22+05:30",
     "approved_at": "2026-05-01T09:31:08+05:30",
     "model": "gpt-image-2"
   }
   ```
2. Insert dedup record (canonical URL + headline-hash).
3. Update `runs` table → `complete`.

---

## 4. Data Model

### 4.1 In-flight types (Python dataclasses)

```python
@dataclass
class NewsItem:
    url: str            # canonical
    headline: str
    summary: str
    source: str         # domain
    published_at: datetime  # tz-aware
    raw: dict           # original skill output

@dataclass
class ScoredItem(NewsItem):
    source_authority: float  # 0..1
    impact: float            # 0..1
    novelty: float           # 0..1
    composite: float

@dataclass
class ClassifiedItem(ScoredItem):
    geo: Literal["IN", "GLOBAL"]

@dataclass
class Slide:
    index: int           # 1-based
    hook: str
    body: str
    payoff: str

@dataclass
class SlideScript:
    slides: List[Slide]
    caption: str
    hashtags: List[str]

@dataclass
class TextOverlay:
    text: str
    position: str        # "top" | "center" | "bottom-left" ...
    style: str           # token

@dataclass
class SlideVisual:
    index: int
    image_prompt: str    # for gpt-image-2
    text_overlays: List[TextOverlay]
    palette: List[str]   # hex codes

@dataclass
class VisualSpec:
    slides: List[SlideVisual]
    style_token: str     # e.g., "editorial-collage-v1"
```

### 4.2 SQLite Schema

```sql
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,    -- pending | awaiting_approval | approved | rejected | complete | errored | policy-blocked
  item_url TEXT NOT NULL,
  geo TEXT,
  score REAL,
  state_blob BLOB,         -- serialized SDK state for resumption
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE dedup (
  canonical_url TEXT PRIMARY KEY,
  headline_hash TEXT,
  consumed_at TEXT,
  run_id TEXT
);

CREATE TABLE approvals (
  run_id TEXT PRIMARY KEY,
  decision TEXT NOT NULL,  -- approve | reject | revise
  feedback TEXT,           -- only for revise
  decided_at TEXT,
  decided_by TEXT
);

CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_dedup_url ON dedup(canonical_url);
```

### 4.3 Disk Layout

```
output/
  2026-05-01/
    mumbai-watermelon-deaths/
      slide-01.png       # first slide (always present)
      slide-02.png       # only after approval
      ...
      preview.json       # full script + visual spec, written before approval
      metadata.json      # final, written after approval
.state/
  carousel.db            # SQLite
  logs/
    carousel.log
.config/
  carousel.yaml
```

---

## 5. Skill Definitions (NEW)

All three skills live under `~/.claude/skills/<slug>/SKILL.md` with frontmatter and instructions. **Existing skills are NOT modified.**

### 5.1 `amarolabs-news-carousel`

**Frontmatter:**
```yaml
---
name: amarolabs-news-carousel
description: Recency-only health-news research for the @amarolabs carousel pipeline. Returns negative-framed health items published in the last 48-72 hours from curated sources, cross-verified, deduplicated against prior @amarolabs posts. Differs from amarolabs-news by hard-windowing to 48-72h (no 2024-2026 backlog) and by emitting items in a structured schema for downstream agents.
type: research
---
```

**Behavior contract:**
- **Input:** `window_hours: int = 48` (max 72), `limit: int = 10`.
- **Output:** JSON array, each item:
  ```json
  {
    "url": "...",
    "canonical_url": "...",
    "headline": "...",
    "summary": "<= 500 chars",
    "source": "domain",
    "published_at": "ISO 8601",
    "geo_hint": "free-text location mention",
    "negative_framing_score": 0.0-1.0
  }
  ```
- **Source allowlist:** Same Tier 1/2 list as filter agent.
- **Recency enforcement:** Skill MUST drop items older than `window_hours`.
- **Cross-verification:** A finding referenced by ≥2 allowlisted sources is preferred but not required.
- **Negative framing:** Skill scores each item for "negative health finding" framing (mortality, outbreak, harm, withdrawal). Items with score < 0.4 are dropped.

### 5.2 `neuro-carousel-writer`

**Frontmatter:**
```yaml
---
name: neuro-carousel-writer
description: Slide-wise script generator for short-form health-news carousels. Built on the neuroscience-backed framing principles of neuro-scriptwriter (open loops, dopamine-prediction-error hooks, payoff slides) but adapted for 5-7 slide Instagram carousels with bounded text per slide. Emits structured JSON with hook/body/payoff per slide plus caption and hashtags.
type: writer
---
```

**Behavior contract:**
- **Input:** ClassifiedItem (headline, summary, source, geo).
- **Output:**
  ```json
  {
    "slides": [
      {"index": 1, "hook": "...", "body": "", "payoff": ""},
      {"index": 2, "hook": "", "body": "<=120 chars", "payoff": ""},
      ...
      {"index": 5, "hook": "", "body": "", "payoff": "..."}
    ],
    "caption": "<=2200 chars Instagram caption",
    "hashtags": ["#health", "..."]
  }
  ```
- **Slide count:** 3 ≤ N ≤ 10. Default 5–7.
- **Slide 1 (cover):** Pure hook. No body. Optional payoff teaser.
- **Last slide:** Includes source citation marker `{{source}}` for the formatter to replace.

### 5.3 `amara-news-carousel`

**Frontmatter:**
```yaml
---
name: amara-news-carousel
description: Visual formatting for @amarolabs health-news carousels. Translates a slide-wise script into per-slide visual specs in the Editorial Collage style (B&W cutouts, torn paper textures, selective color pops) defined by the carousel-style skill. Emits image-generation prompts ready for gpt-image-2, with style anchors that preserve consistency across all slides in a carousel.
type: formatter
---
```

**Behavior contract:**
- **Input:** SlideScript + geo.
- **Output:** VisualSpec (see §4.1).
- **Style anchors:** Every per-slide `image_prompt` includes the same style preamble derived from `carousel-style` so `gpt-image-2`'s multi-image-consistency keeps the look coherent.
- **India-vs-Global cue:** Subtle visual marker (e.g., color accent) selectable but NOT a localization (per FR-003 spirit — geography is an event property, not an audience property).
- **Source slot:** Last slide always includes a textual source citation overlay.

---

## 6. APIs / Interfaces

### 6.1 CLI

```
carousel_agent run [--since DURATION] [--top-n N] [--dry-run]
carousel_agent pending [--json]
carousel_agent status <run_id>
carousel_agent approve <run_id>
carousel_agent reject <run_id>
carousel_agent revise <run_id> --feedback "..."
carousel_agent retry <run_id>
```

### 6.2 OpenAI Image API call

```python
client.images.generate(
    model="gpt-image-2",
    prompt=visual_spec.slides[i].image_prompt,
    size="1080x1350",
    n=1,
    response_format="b64_json",
)
```

Model name held in `config.image_model` for swappability.

### 6.3 Skill invocation

Skills are invoked via Claude Code's skill mechanism, wrapped as a function tool by the Python harness. Each invocation produces a JSON envelope; agents validate against their schema.

---

## 7. Security & Compliance

- **API keys:** `OPENAI_API_KEY` from env only, never logged. CLI errors redact keys.
- **No PII handling:** Pipeline processes public news. No user PII.
- **Source attribution:** Hard requirement (FR + tool guardrail). Prevents plagiarism risk.
- **Content policy:** `gpt-image-2` may block content. Pipeline handles `policy-blocked` state explicitly (FM-004).

---

## 8. Operational Considerations

### 8.1 Configuration (`carousel.yaml`)
```yaml
schedule:
  cron: "0 7 * * *"      # 07:00 IST
  timezone: "Asia/Kolkata"
collection:
  window_hours: 48
  limit: 10
filter:
  threshold: 0.55
  source_authority_weight: 0.4
  impact_weight: 0.4
  novelty_weight: 0.2
triage:
  top_n: 1
rendering:
  image_model: "gpt-image-2"
  size: "1080x1350"
  retries: 3
  fallback_model: "gpt-image-1"   # used only if probe fails (see Risk Register)
output:
  base_dir: "./output"
state:
  db_path: "./.state/carousel.db"
```

### 8.2 Observability
- All agent runs traced via SDK's built-in tracer (per docs §10).
- Local logs at `./.state/logs/carousel.log` with per-run correlation ID = `run_id`.
- `status <run_id>` CLI command pretty-prints the run's lifecycle and any errors.

### 8.3 Scaling
v1 is single-machine. Bottleneck is `gpt-image-2` rate-limit. At default 1 carousel/day with ~5 images, well below any reasonable rate limit.

---

## 9. Implementation Plan

### Phase 0 — Probe (Day 1, before anything else)
- TASK-000: One-shot script that calls `gpt-image-2` with a trivial prompt and verifies success. **Blocks all subsequent work.** If access not granted, decide between (a) waiting for rollout and (b) implementing with `gpt-image-1` fallback first.

### Phase 1 — Foundation (Week 1)
- TASK-001: Repo scaffold (`carousel_agent/` package, `pyproject.toml`, lockfile, mypy/ruff config)
- TASK-002: SQLite schema + migrations
- TASK-003: Config loader + validation
- TASK-004: CLI skeleton (all subcommands stubbed)
- TASK-005: Logging + tracing scaffolding
- **Acceptance:** `carousel_agent --help` works; tests pass; DB initializes.

### Phase 2 — New Skills (Week 1–2)
- TASK-006: `amarolabs-news-carousel` skill file + tests
- TASK-007: `neuro-carousel-writer` skill file + tests
- TASK-008: `amara-news-carousel` skill file + tests
- **Acceptance:** AC-006-1, AC-007-1, AC-008-1, AC-008-2 pass.

### Phase 3 — Pipeline Agents (Week 2–3)
- TASK-009: Collector agent + skill invocation
- TASK-010: Filter agent (allowlist + LLM-judge impact)
- TASK-011: Classifier agent (LLM-judge geo)
- TASK-012: Triage agent
- TASK-013: Writer agent (skill bridge)
- TASK-014: Formatter agent (skill bridge)
- TASK-015: Pipeline Manager + agents-as-tools wiring
- **Acceptance:** AC-002-1/2/3, AC-003-1..4 pass; ITS-002 partial.

### Phase 4 — Renderer + Approval Gate (Week 3)
- TASK-016: Renderer (gpt-image-2 client, retry logic, file write)
- TASK-017: Approval state machine + SDK interruption integration
- TASK-018: State serialization (SDK state + run metadata)
- TASK-019: CLI `approve / reject / revise / pending / status`
- TASK-020: Tool guardrails (attribution, budget gate)
- **Acceptance:** AC-010-1..5, FR-009 ACs, ITS-001/003/004.

### Phase 5 — Persister + End-to-End (Week 3–4)
- TASK-021: Persister + metadata.json
- TASK-022: Dedup integration end-to-end
- TASK-023: Failure-mode handling + recovery commands
- TASK-024: End-to-end integration tests (ITS-001..007)
- TASK-025: Skill-integrity verification script (FR-005)
- **Acceptance:** All Must-Pass acceptance criteria green.

### 9.1 Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `gpt-image-2` API access not yet enabled for this account | M | H | Phase 0 probe; fall back to `gpt-image-1` behind config flag if needed |
| SDK state-serialization format changes | L | M | Pin SDK version; add migration shim if breaking change |
| `amarolabs-news-carousel` skill returns unstable output | M | M | Strict schema validation in Collector; failed items dropped not crashed |
| Image content-policy false positives | M | M | FM-004 path; placeholder slide; manual fallback |
| Editorial Collage style drift across slides | M | L | Style anchor preamble + multi-image-consistency feature of `gpt-image-2` |
| Composite-score thresholds need tuning | H | L | Threshold is config-driven; expect 1–2 weeks of tuning post-launch |

---

## 10. Open Questions

| Question | Impact | Owner | Due |
|----------|--------|-------|-----|
| Final source allowlist tiers (specific domains) | Filter accuracy | Operator | Phase 3 |
| Initial composite-score threshold | Pass-through rate | Operator | Phase 5 |
| Default hashtag set for @amarolabs | Caption quality | Operator | Phase 2 |

---

## Appendices

### A. Glossary
- **Carousel** — Multi-image Instagram post (1080×1350 portrait, 3–10 images).
- **Slide** — One image in a carousel.
- **Item** — A news item from collection, before classification.
- **Run** — One end-to-end pipeline invocation for a single item.
- **Approval gate** — The interruption between rendering slide 1 and slides 2..N.

### B. References
- OpenAI Agents SDK docs in this repo: `6.SandboxAgents.md/3.AgentDefinitions.md`, `7.Orchestration.md`, `8.GuardrailsAndHumanReviews.md`, `9.ResultAndState.md`, `10.Integrationsandobservability.md`.
- ChatGPT Images 2.0 announcement (2026-04-21).
- Existing skills at `~/.claude/skills/{carousel-style,neuro-scriptwriter,amarolabs-news}/SKILL.md`.

### C. Revision History
| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-05-01 | system-architect | Initial spec |
