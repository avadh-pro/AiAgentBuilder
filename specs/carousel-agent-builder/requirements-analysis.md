# Requirements Analysis: Carousel Agent Builder

**Project:** Carousel Agent Builder — automated health-news → Instagram carousel pipeline
**Source:** `/create-spec-from-requirements` invocation, 2026-05-01
**Status:** DRAFT — Phase 1 of spec creation

---

## 1. Restated Requirements

### 1.1 Functional Requirements

#### FR-001: Automated News Collection
**Original:** "automatically collects early-stage negative health-related news"
**Interpretation:** The system runs on a schedule (and on-demand) to retrieve health-related news items where the framing is negative or cautionary, published within the last 2–3 days. "Early-stage" means not yet saturated in the @amarolabs feed and not previously processed.
**Category:** Core | **Testable:** Yes

#### FR-002: Credibility & Impact Filtering
**Original:** "filters for high-impact and credible stories"
**Interpretation:** Each collected item is scored against (a) source authority (allowlist tiers), (b) impact (severity / population-affected), and (c) novelty. Items below a configurable threshold are discarded.
**Category:** Core | **Testable:** Yes

#### FR-003: Geographic Classification
**Original:** "classifies each item into either India-specific health news or global health news based purely on where the event occurs (not audience adaptation)"
**Interpretation:** Each surviving item is labeled `IN` (event located in India) or `GLOBAL` (event located outside India, multi-country, or geography-ambiguous). Classification is event-locus only — *not* tailored to audience demographics or language.
**Category:** Core | **Testable:** Yes

#### FR-004: Carousel Generation per Item
**Original:** "converts each selected news item into a high-engagement carousel post"
**Interpretation:** For each selected item, the system produces a multi-slide carousel asset (PNG slides + caption + hashtags + source URL metadata) ready for Instagram publishing.
**Category:** Core | **Testable:** Yes

#### FR-005: Existing Skills Used As-Is
**Original:** "leveraging existing skills as-is without any modification"
**Interpretation:** The system invokes pre-existing skills (`carousel-style`, `neuro-scriptwriter`, `amarolabs-news`, etc.) without altering their files, frontmatter, or behavior. New behavior must be expressed via *new* skills, not edits to existing ones.
**Category:** Core (constraint) | **Testable:** Yes — pre/post hash comparison.

#### FR-006: New Skill — `neuro-carousel-writer`
**Original:** "introducing new adapted skills such as `neuro-carousel-writer` (derived from `neuro-scriptwriter`) for generating emotionally compelling slide-wise scripts"
**Interpretation:** Create a new skill named `neuro-carousel-writer`. Inherits the neuroscience-backed framing of `neuro-scriptwriter` but produces slide-wise output (one short, hook-driven block per slide) instead of long-form video script. Output schema: `{slides: [{index, hook, body, payoff}], caption, hashtags}`.
**Category:** Core | **Testable:** Yes

#### FR-007: New Skill — `amara-news-carousel`
**Original:** "`Amara news carousel` (built on top of `carousel-style`) for formatting"
**Interpretation:** Create a new skill named `amara-news-carousel`. Built on `carousel-style` (Editorial Collage — B&W cutouts, torn paper textures, selective color pops). Translates the slide-wise script into per-slide visual specs (layout, text placement, color accents, image-prompt seed). Does NOT modify `carousel-style`.
**Category:** Core | **Testable:** Yes

#### FR-008: New Skill — `amarolabs-news-carousel` (added in clarification)
**Original (clarification, turn 2):** "for the new-source layer you need to create the new skill called amarolabs-news-carousel, which would only have the latest news past 2 to 3 days max and not 2024-2026 ... it should be latest only"
**Interpretation:** Create a new skill named `amarolabs-news-carousel`. Inherits source curation and cross-verification from `amarolabs-news` but enforces a strict recency window of 48–72 hours (default 48h, configurable up to 72h). Replaces the 2024–2026 long-window framing with "latest only."
**Category:** Core | **Testable:** Yes

#### FR-009: Image Rendering via `gpt-image-2`
**Original:** "final carousel images generated using the OpenAI Image-2 model API" + clarification: model ID is `gpt-image-2`, released 2026-04-21.
**Interpretation:** All slide images are rendered by calling the OpenAI Image API with `model: "gpt-image-2"`. Model name is config-pinned; resolution and aspect ratio are config-driven (default 1080×1350 portrait for Instagram).
**Category:** Core | **Testable:** Yes

#### FR-010: First-Slide Approval Gate (added in clarification)
**Original (clarification, turn 2):** "first you should only create the first slide, if I like we can have the next slides"
**Interpretation:** The pipeline renders ONLY slide 1 per item and then pauses, awaiting human approval. On `approve`, the remaining slides are rendered and the carousel is finalized. On `reject`, the item is logged and dropped. On `revise` (with feedback), the writer re-runs and a new slide-1 is produced. State is serialized so approvals can occur asynchronously (hours/days later) without re-running the pipeline from scratch.
**Category:** Core | **Testable:** Yes

#### FR-011: OpenAI Agents SDK Orchestration
**Original:** "Python-based AI agent system using the OpenAI Agent SDK"
**Interpretation:** Multi-agent pipeline implemented with `openai-agents` (Python). Each pipeline stage is an `Agent` with explicit instructions and tools. Inter-stage flow uses agents-as-tools where the manager retains control; handoffs only where appropriate (rare in this pipeline shape).
**Category:** Core (constraint) | **Testable:** Yes

#### FR-012: Python Implementation
**Original:** "Python-based"
**Interpretation:** Codebase is Python 3.11+. No TypeScript components. Sandbox agents (Python-only SDK feature) are NOT required for this pipeline (no shell/file execution).
**Category:** Core (constraint) | **Testable:** Yes

### 1.2 Non-Functional Requirements

#### NFR-001: Reproducibility
Every run is recorded via the SDK's built-in tracer. A given trace must allow a developer to inspect every model call, tool call, and decision.
**Measurement:** Trace dashboard shows complete run; replay possible via local history.

#### NFR-002: Resumability
A pipeline paused on the approval gate must survive process restart. Approval can be granted hours or days after the initial run.
**Measurement:** State serialized to disk (SDK state blob in SQLite); resume via `state` snapshot; integration test confirms cold-restart resume works.

#### NFR-003: Idempotency / Dedup
The same news item must not be processed twice across runs.
**Measurement:** SQLite-backed dedup store keyed on canonical URL + headline-hash; second run with same item logs "already processed" and exits clean.

#### NFR-004: Existing-Skill Integrity
No existing skill file in `~/.claude/skills/` is modified.
**Measurement:** Pre/post SHA-256 comparison of all skill files predating the project.

#### NFR-005: Cost Awareness
Image generation is the dominant cost driver; the first-slide gate exists partly to avoid paying for full carousels on items the operator will reject.
**Measurement:** Cost-per-run logged; full-carousel cost only paid post-approval.

### 1.3 Constraints

| ID | Constraint | Source |
|----|------------|--------|
| HC-001 | Python + `openai-agents` SDK | Requirements |
| HC-002 | `gpt-image-2` for image rendering | Requirements + clarification |
| HC-003 | Existing skills must not be modified | Requirements |
| HC-004 | Three new skills only (`neuro-carousel-writer`, `amara-news-carousel`, `amarolabs-news-carousel`) | Requirements |
| HC-005 | Recency window: ≤72h for news collection | Clarification |
| HC-006 | First-slide-only render before approval | Clarification |
| HC-007 | Geographic classification: event-locus only | Requirements |

---

## 2. Gap Analysis

### 2.1 Critical Gaps
**None blocking spec creation.** All critical questions were resolved in the user's clarification turn (model ID, news source layer, output flow).

### 2.2 Important Gaps (assumptions documented; reversible)

#### GAP-001: Approval Channel
**Question:** How does the operator approve/reject slide 1?
**Assumption:** CLI-based via `python -m carousel_agent approve <run_id>` / `reject <run_id>` / `revise <run_id> --feedback "..."`. A `pending` command lists runs awaiting decision. Telegram bot integration (the `mcp__telegram__*` tools exist) is a candidate v2 enhancement but is NOT in scope for v1.
**Risk if wrong:** Low — CLI is a defensible default; integrating Telegram later is a thin adapter on the same approval interface.

#### GAP-002: Run Cadence
**Assumption:** Once daily by default at 07:00 IST, configurable via cron expression. On-demand via CLI.
**Risk if wrong:** Low — config-driven.

#### GAP-003: Items Per Run
**Assumption:** Top-1 by composite score per run (one carousel per day in steady state). Configurable; values >1 supported, but each item generates its own approval gate.
**Risk if wrong:** Low — config knob.

#### GAP-004: Slide Count
**Assumption:** 5–7 slides decided by `neuro-carousel-writer` based on content density. Hard min/max enforced (3 / 10).
**Risk if wrong:** Low — bounded by skill output schema.

#### GAP-005: Caption / Hashtag Source
**Assumption:** Generated by `neuro-carousel-writer` as part of its output schema (no separate caption agent).
**Risk if wrong:** Low — separable later.

#### GAP-006: Image API Failure Behavior
**Assumption:** Exponential backoff (3 retries: 2s/4s/8s); on persistent failure, run marked `errored` with full trace; item NOT marked dedup-consumed (so it can retry next run).
**Risk if wrong:** Medium — affects manual recovery effort.

#### GAP-007: Source Attribution on Slides
**Assumption:** Source citation appears on the *last* slide AND in the post caption. Tool guardrail enforces presence at render time.
**Risk if wrong:** Low — but compliance-relevant.

### 2.3 Minor Gaps (sensible defaults)

| ID | Gap | Default |
|----|-----|---------|
| GAP-008 | Output directory | `output/<YYYY-MM-DD>/<slug>/` under project root |
| GAP-009 | Locale of caption | English (matches `amarolabs-news` default) |
| GAP-010 | Image aspect ratio | 4:5 (1080×1350) Instagram portrait |
| GAP-011 | Approval timeout | None — pending forever until acted on |
| GAP-012 | Concurrent runs | Disallowed via lockfile (per item, not per pipeline) |

---

## 3. Design Hints vs Hard Constraints

### 3.1 Hard Constraints (non-negotiable)
Listed in §1.3 (HC-001 through HC-007).

### 3.2 Design Hints (evaluated)

| ID | Hint | Assessment | Decision |
|----|------|-----------|----------|
| DH-001 | "high-engagement carousel post" | Outcome, not constraint | Optimize via `neuro-carousel-writer` framing; no engagement metric measured in v1 (no Instagram analytics) |
| DH-002 | "high-impact and credible" | Subjective — needs explicit formula | Defined as transparent composite score in spec |

### 3.3 Requirements Challenged

| ID | Requirement | Concern | Proposal |
|----|-------------|---------|----------|
| RC-001 | "convert each selected news item into a carousel" | "Each" implies all selected → carousel. With approval gate, rejected items become NO carousel. | Clarify in spec: "each selected item *is offered as a carousel via the first-slide preview*; full carousel only on approval." |

---

## 4. UI/UX Components Detection

**No graphical UI required.** The system is a headless agent pipeline with CLI for triggering and approving. The only "interface" is the CLI and the carousel images themselves (which are *outputs*, not UI). **Phase 1.5 (UI/UX design) is skipped.**

---

## 5. Decision Point

✅ **No CRITICAL gaps remain.** Proceeding to test-plan creation.

Documented assumptions (GAP-001 through GAP-012) are reversible via configuration and may be revised by the stakeholder at any point during or after implementation.
