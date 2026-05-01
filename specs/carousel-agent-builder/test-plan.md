# Test Plan: Carousel Agent Builder

**Created:** 2026-05-01
**Requirements Source:** [./requirements-analysis.md](./requirements-analysis.md)
**Status:** DRAFT — awaiting CTO review

---

## 1. Test Strategy

### Scope
- **In Scope:** All pipeline stages (collect → filter → classify → triage → write → format → render-1 → approve → render-rest → persist), all three new skills, dedup store, approval state machine, tracing, CLI.
- **Out of Scope:** Instagram posting, Telegram integration, web dashboard, multi-tenant, performance under load >10 runs/day.

### Test Categories
1. **Functional** — per-FR acceptance criteria
2. **Skill conformance** — output-schema validation for each new skill
3. **Integration** — end-to-end pipeline scenarios
4. **State / resumability** — approval pause-resume behavior
5. **Failure mode** — API/network/dedup failures
6. **Edge case** — empty results, ambiguous classification, malformed inputs
7. **Cost / side-effect** — image API only invoked for approved slides

---

## 2. Acceptance Criteria by Requirement

### FR-001: Automated News Collection

#### AC-001-1: Fresh items collected
**Given:** `amarolabs-news-carousel` skill returns 3 items published in the last 24h
**When:** Collector agent runs with default 48h window
**Then:** All 3 items appear in collection output with intact `url`, `headline`, `published_at`, `source`
**Priority:** Must Pass

#### AC-001-2: Stale items rejected
**Given:** Skill returns one item published 5 days ago
**When:** Collector runs with 48h window
**Then:** Item NOT in collection output; one warning log line records the rejection
**Priority:** Must Pass

#### AC-001-3: Zero-result run is clean
**Given:** Skill returns empty list
**When:** Collector runs
**Then:** Pipeline exits with code 0, status `no-items`, no carousel artifacts produced, no traceback
**Priority:** Must Pass

### FR-002: Credibility & Impact Filtering

#### AC-002-1: Allowlisted Tier-1 source passes
**Given:** Item from a Tier-1 source (peer-reviewed journal or major health agency) with non-zero impact score
**When:** Filter agent runs
**Then:** Item proceeds to classifier
**Priority:** Must Pass

#### AC-002-2: Below-threshold item dropped
**Given:** Item with composite score below configured threshold
**When:** Filter runs
**Then:** Item dropped, reason logged, NOT counted as dedup-consumed
**Priority:** Must Pass

#### AC-002-3: Score formula is stable
**Given:** Same item input twice within a single run
**When:** Filter runs twice
**Then:** Composite scores match within ±0.05 (LLM-judge sub-score has bounded non-determinism even at temperature=0)
**Priority:** Should Pass

### FR-003: Geographic Classification

#### AC-003-1: India-event → IN
**Given:** Item describes a health event in Mumbai
**When:** Classifier runs
**Then:** `geo: "IN"`
**Priority:** Must Pass

#### AC-003-2: Multi-country event → GLOBAL
**Given:** Item describes WHO advisory affecting 12 countries including India
**When:** Classifier runs
**Then:** `geo: "GLOBAL"` (multi-country defaults to GLOBAL)
**Priority:** Must Pass

#### AC-003-3: Geography-ambiguous → GLOBAL
**Given:** Item with no clear geographic anchor (e.g., a meta-analysis)
**When:** Classifier runs
**Then:** `geo: "GLOBAL"`
**Priority:** Must Pass

#### AC-003-4: No audience-adaptation leak
**Given:** Item describing a US-only outbreak
**When:** Classifier runs
**Then:** `geo: "GLOBAL"` (NOT "IN" merely because @amarolabs audience is partly Indian)
**Priority:** Must Pass

### FR-004: Carousel Generation

#### AC-004-1: First-slide artifact produced
**Given:** Approved item reaches the first-slide renderer
**When:** Renderer calls `gpt-image-2`
**Then:** PNG file written to `output/<date>/<slug>/slide-01.png` AND `preview.json` containing the full slide-wise script (so the operator can review the entire planned carousel before approving)
**Priority:** Must Pass

#### AC-004-2: Full carousel post-approval
**Given:** First slide rendered, operator issues `approve`
**When:** Pipeline resumes
**Then:** Remaining slides rendered as `slide-02.png`...`slide-NN.png`; `metadata.json` contains caption, hashtags, source URL, run_id, model name
**Priority:** Must Pass

### FR-005: Existing Skills Untouched

#### AC-005-1: Pre/post hash check
**Given:** SHA-256 snapshot of `carousel-style/SKILL.md`, `neuro-scriptwriter/SKILL.md`, `amarolabs-news/SKILL.md` (and bundled files) taken before implementation
**When:** Implementation completes
**Then:** Every snapshotted file's SHA-256 is unchanged
**Priority:** Must Pass

### FR-006/007/008: New Skills

#### AC-006-1: `neuro-carousel-writer` exists with valid frontmatter
**Given:** Implementation complete
**When:** Skill loader scans `~/.claude/skills/`
**Then:** Skill appears in available list; frontmatter `name`, `description` valid
**Priority:** Must Pass

#### AC-006-2: `neuro-carousel-writer` schema-conformant output
**Given:** Skill invoked with a sample news item
**When:** Skill runs
**Then:** Output JSON validates against `{slides: [{index:int, hook:str, body:str, payoff:str}], caption:str, hashtags:[str]}`; 3 ≤ len(slides) ≤ 10; caption ≤ 2200 chars
**Priority:** Must Pass

#### AC-007-1: `amara-news-carousel` produces visual specs
**Given:** A `neuro-carousel-writer` output
**When:** `amara-news-carousel` invoked
**Then:** Output includes per-slide visual spec: layout token, text placement, color accents, image-prompt seed for `gpt-image-2`
**Priority:** Must Pass

#### AC-007-2: Editorial Collage style preserved
**Given:** Visual specs generated
**When:** Manual review of image prompts
**Then:** Prompts reference B&W cutout / torn paper / selective color pop language inherited from `carousel-style`
**Priority:** Should Pass

#### AC-008-1: `amarolabs-news-carousel` recency enforcement
**Given:** Skill invoked with default config
**When:** Skill returns items
**Then:** Every item's `published_at` is within last 48h
**Priority:** Must Pass

#### AC-008-2: `amarolabs-news-carousel` configurable window
**Given:** Skill invoked with `window_hours=72`
**When:** Skill returns items
**Then:** No item is older than 72h; items 49–72h old ARE included
**Priority:** Must Pass

### FR-009: Image Rendering

#### AC-009-1: Correct model invoked
**Given:** Renderer about to make an API call
**When:** API request inspected
**Then:** Request body contains `"model": "gpt-image-2"`
**Priority:** Must Pass

#### AC-009-2: Output PNG is valid Instagram size
**Given:** Slide rendered
**When:** Output inspected
**Then:** Image is 1080×1350 PNG (or configured dimensions); file is non-empty; not corrupt
**Priority:** Must Pass

### FR-010: Approval Gate

#### AC-010-1: Pipeline pauses after slide 1
**Given:** Item passes filter+classify
**When:** Pipeline runs
**Then:** Exactly ONE image API call made (slide 1) before run state transitions to `awaiting_approval`; state file written to disk
**Priority:** Must Pass

#### AC-010-2: Approve resumes correctly
**Given:** Run in `awaiting_approval` state
**When:** `approve <run_id>` issued
**Then:** Pipeline resumes from saved state, renders remaining N-1 slides, finalizes carousel, transitions to `complete`
**Priority:** Must Pass

#### AC-010-3: Reject terminates cleanly
**Given:** Run in `awaiting_approval` state
**When:** `reject <run_id>` issued
**Then:** No further image API calls; run transitions to `rejected`; first slide retained for archival; item marked dedup-consumed (so it doesn't reappear next run)
**Priority:** Must Pass

#### AC-010-4: Cold-restart resume
**Given:** Run in `awaiting_approval`; process killed
**When:** Process restarts and `approve <run_id>` issued
**Then:** Pipeline resumes from disk state; remaining slides render correctly
**Priority:** Must Pass

#### AC-010-5: Revise re-runs writer only
**Given:** Run in `awaiting_approval`
**When:** `revise <run_id> --feedback "more punchy hook"` issued
**Then:** Writer agent re-runs with feedback in context; new first slide rendered; run returns to `awaiting_approval`; cost: 1 writer call + 1 image call (NOT a full pipeline restart)
**Priority:** Should Pass

### FR-011 / FR-012: SDK + Python

#### AC-011-1: Pipeline composed of `Agent` instances
**Given:** Implementation
**When:** Code reviewed
**Then:** Each LLM-using stage is an `Agent` from `openai-agents`; orchestration uses agents-as-tools (not bare API calls)
**Priority:** Must Pass

#### AC-011-2: Tracing populates dashboard
**Given:** A successful end-to-end run
**When:** OpenAI Traces dashboard checked
**Then:** Run appears with full call tree (collector → filter → classifier → writer → formatter → renderer)
**Priority:** Must Pass

---

## 3. Integration Test Scenarios

### ITS-001: Happy path — single India item
**Setup:** Seed `amarolabs-news-carousel` with one Mumbai-based health item.
**Steps:**
1. `python -m carousel_agent run`
2. Verify pipeline halts at `awaiting_approval`
3. Verify `slide-01.png` exists
4. Verify `preview.json` contains 5–7 slides of script
5. `python -m carousel_agent approve <run_id>`
6. Verify `slide-02.png`...`slide-NN.png` exist
7. Verify `metadata.json` has `geo: "IN"`, source URL, caption
**Expected:** All slides rendered; run state `complete`.

### ITS-002: Happy path — global item
Same as ITS-001 but with WHO advisory; verify `geo: "GLOBAL"`.

### ITS-003: Reject path
ITS-001 through step 4, then `reject <run_id>`. Verify only `slide-01.png` exists; no further API calls.

### ITS-004: Revise path
ITS-001 through step 4, then `revise --feedback "..."`. Verify writer reruns; new slide-01 differs from old; state returns to `awaiting_approval`.

### ITS-005: Multi-item run
**Setup:** Skill returns 3 items, `top_n=2`.
**Expected:** 2 separate runs created, each independently awaits approval. Approval of one does not affect others.

### ITS-006: Dedup across runs
**Setup:** Run pipeline; approve; immediately run again with same source items.
**Expected:** Second run logs "all items already processed", exits clean.

### ITS-007: Skill integrity check
**Setup:** Hash all existing skill files, run pipeline, hash again.
**Expected:** All hashes match.

---

## 4. Non-Functional Test Criteria

### Reliability

| Scenario | Expected Behavior |
|----------|-------------------|
| OpenAI image API timeout | 3 retries with exponential backoff (2s/4s/8s); on final failure, run marked `errored`, item NOT consumed from dedup |
| Rate-limit (429) from image API | Honor `Retry-After`; not counted as one of the 3 retries |
| Process killed mid-render | On restart, resume from last state checkpoint; partial slides re-rendered if needed |
| `amarolabs-news-carousel` skill timeout | Run fails fast with clear error; item not consumed |

### Cost / Side-Effects

| Test | Pass Criterion |
|------|----------------|
| Approve-then-render cost gating | For a rejected item, total `gpt-image-2` calls = 1 (only slide-01) |
| Approve cost | For an approved 5-slide carousel, total `gpt-image-2` calls = 5 |
| Repeat approval is idempotent | `approve <run_id>` twice does not double-render |

---

## 5. Edge Cases

| ID | Condition | Expected |
|----|-----------|----------|
| EC-001 | Skill returns malformed item (missing `url`) | Item dropped with validation error log; pipeline continues |
| EC-002 | News item has no clear publication date | Treated as stale (rejected) |
| EC-003 | Writer produces <3 slides | Schema validation fails; item marked `errored` |
| EC-004 | Writer produces >10 slides | Truncated to 10 with warning log |
| EC-005 | Caption exceeds Instagram 2200-char limit | Truncated to 2200 with `…` and warning |
| EC-006 | Source URL no longer resolves (404) | Render proceeds; warning logged in metadata |
| EC-007 | Two concurrent `run` invocations | Second blocked by global lockfile |
| EC-008 | `approve <unknown_run_id>` | Clear error message; exit code 2 |
| EC-009 | Approval issued for already-approved run | No-op; "already approved" message |
| EC-010 | Item geography is mixed-language (e.g., Hindi place name) | Classifier still routes correctly via LLM-judge |

---

## 6. Failure Mode Tests

| ID | Trigger | Expected | Recovery |
|----|---------|----------|----------|
| FM-001 | Disk full during slide write | Run errors; partial files cleaned | Manual disk free; rerun |
| FM-002 | SQLite dedup DB locked | Wait + retry (3x); error if persistent | Human inspection |
| FM-003 | OpenAI API key invalid | Fail at first call with clear "auth failed" message | Fix key; rerun |
| FM-004 | `gpt-image-2` returns content-policy block | Run marked `policy-blocked`; first slide replaced with placeholder; operator notified | Manual review |
| FM-005 | Skill loader can't find new skill | Pipeline fails fast at startup with explicit "skill X not registered" | Verify skill installation |

---

## 7. Test Coverage Matrix

| Requirement | Unit/AC | Skill conformance | Integration | E2E |
|-------------|---------|-------------------|-------------|-----|
| FR-001 | AC-001-1/2/3 | AC-008-1/2 | ITS-001 | — |
| FR-002 | AC-002-1/2/3 | — | ITS-001 | — |
| FR-003 | AC-003-1/2/3/4 | — | ITS-001/002 | — |
| FR-004 | AC-004-1/2 | — | ITS-001/002 | ✓ |
| FR-005 | AC-005-1 | — | ITS-007 | — |
| FR-006 | AC-006-1/2 | ✓ | ITS-001 | — |
| FR-007 | AC-007-1/2 | ✓ | ITS-001 | — |
| FR-008 | AC-008-1/2 | ✓ | ITS-001 | — |
| FR-009 | AC-009-1/2 | — | ITS-001 | — |
| FR-010 | AC-010-1..5 | — | ITS-001/003/004 | ✓ |
| FR-011 | AC-011-1/2 | — | All | ✓ |
| FR-012 | (code review) | — | All | — |

---

## 8. Success Metrics

The implementation is COMPLETE when:
- [ ] All Must-Pass acceptance criteria pass
- [ ] All Should-Pass criteria pass or have approved exceptions
- [ ] All 7 integration scenarios pass
- [ ] All 5 failure modes have documented recovery
- [ ] Skill integrity check (FR-005) passes
- [ ] Cost-gating test confirms first-slide-only on reject
