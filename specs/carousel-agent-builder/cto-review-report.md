# CTO Review Report: Carousel Agent Builder

**Specification:** Carousel Agent Builder v1.0
**Reviewer:** cto-reviewer (executed by Claude Code)
**Review Date:** 2026-05-01
**Status:** **APPROVED with recommendations**

---

## 1. Requirements Coverage

### 1.1 Traceability Matrix

| Requirement | Spec Section | Test Coverage | Status |
|-------------|--------------|---------------|--------|
| FR-001 Collection | §3.2, §5.1 | AC-001-1/2/3 | ✓ COVERED |
| FR-002 Filtering | §3.3 | AC-002-1/2/3 | ✓ COVERED |
| FR-003 Classification | §3.4 | AC-003-1..4 | ✓ COVERED |
| FR-004 Carousel generation | §3.6–§3.9 | AC-004-1/2 | ✓ COVERED |
| FR-005 No skill modifications | §1.3 (HC-003), TASK-025 | AC-005-1 | ✓ COVERED |
| FR-006 neuro-carousel-writer | §5.2 | AC-006-1/2 | ✓ COVERED |
| FR-007 amara-news-carousel | §5.3 | AC-007-1/2 | ✓ COVERED |
| FR-008 amarolabs-news-carousel | §5.1 | AC-008-1/2 | ✓ COVERED |
| FR-009 gpt-image-2 rendering | §3.8, §6.2 | AC-009-1/2 | ✓ COVERED |
| FR-010 First-slide approval gate | §3.8, §3.1 (guardrails), §4.2 | AC-010-1..5 | ✓ COVERED |
| FR-011 OpenAI Agents SDK | §2.3 D1, §3.1 | AC-011-1/2 | ✓ COVERED |
| FR-012 Python | §2.2, §9 | (code review) | ✓ COVERED |
| NFR-001 Reproducibility | §8.2 | AC-011-2 | ✓ COVERED |
| NFR-002 Resumability | §2.3 D2, §4.2 | AC-010-4 | ✓ COVERED |
| NFR-003 Idempotency | §3.9, §4.2 | ITS-006 | ✓ COVERED |
| NFR-004 Skill integrity | TASK-025 | AC-005-1 | ✓ COVERED |
| NFR-005 Cost awareness | §2.3 D3, §3.1 (tool guardrails) | Cost-gating tests | ✓ COVERED |

**Finding:** Full requirements coverage. Every FR/NFR has at least one spec section AND at least one acceptance criterion.

### 1.2 Requirements Not Addressed
None.

### 1.3 Over-Interpretation Check
The spec adds: SQLite-backed state, configurable cron, CLI revise command, source-authority allowlist tiers, slide-count bounds (3..10), local-history conversation strategy.

Each addition is justified in the spec or flagged as an explicit assumption in `requirements-analysis.md` (GAP-001..012). **No silent over-interpretation.**

---

## 2. Design Quality

### 2.1 Architecture Assessment

- [x] Architecture appropriate (manager-with-tools matches sequential pipeline shape)
- [x] Component responsibilities single-purpose
- [x] No unnecessary complexity (sandbox rejected; handoffs rejected; separate caption agent rejected)
- [x] Scalability considerations addressed (single-machine v1; storage-interface seam noted)
- [x] Failure modes considered (FM-001..005)

**Finding:** Architecture is sound and exhibits good engineering judgment. The decision to use agents-as-tools over handoffs is correct for this pipeline shape and well-justified.

### 2.2 Design Decision Review

| Decision | Assessment | Concerns |
|----------|------------|----------|
| D1 Agents-as-tools over handoffs | **SOUND** | Handoffs would scatter run-state ownership; agents-as-tools centralizes it |
| D2 SDK interruptions for approval | **SOUND** | Exactly what the SDK provides; custom queue would reinvent. State-format coupling acknowledged |
| D3 Tool guardrails over input guardrails | **SOUND** | The brainstorm-flagged "input guardrails fire only on first agent" trap is correctly avoided |
| D4 SQLite for state/dedup | **SOUND** | Proportionate to scale; storage interface allows future swap |
| D5 No sandbox agents | **SOUND** | Sandbox provides nothing here (no shell, no code exec) |
| D6 Caption inside writer skill | **SOUND** | Lower latency, single context; trivially separable later |
| D7 Local-history conversation strategy | **SOUND** | Run is short-lived; serialized state already covers cross-session continuity |

### 2.3 Alternatives Documentation
Each Decision lists Options A/B/C with explicit rationale and rejected alternatives. **Adequate.**

---

## 3. Test Plan Completeness

- [x] All requirements have acceptance criteria
- [x] Happy paths covered (ITS-001/002)
- [x] Edge cases identified (EC-001..010)
- [x] Failure modes covered (FM-001..005)
- [x] NFRs tested (cost gating, reliability, resumability)

### 3.1 Notable Strengths
- Cost-gating test (one image API call per rejected item) directly validates the user's stated motivation for the approval gate.
- Cold-restart resume test (AC-010-4) catches state-serialization bugs that often surface only in production.
- Skill-integrity hash check (AC-005-1) is rigorous defense of the "no modifications" requirement.

### 3.2 Test Plan Gaps Identified
None blocking. Minor recommendation logged in §7 (MIN-003).

---

## 4. Security Review

- [x] API key handling (env-only)
- [x] No PII (public news only)
- [x] Source attribution enforced via tool guardrail
- [x] Content-policy block path explicit (FM-004)
- [x] No untrusted code execution

**Finding:** No security concerns. Attribution-as-tool-guardrail is a smart placement.

---

## 5. Operational Readiness

- [x] Configuration externalized to YAML
- [x] Tracing via SDK built-in
- [x] Local log file with run-correlation ID
- [x] Disk-only output (auto-publishing explicitly out of scope)
- [x] Failure recovery via `retry` CLI

**Finding:** Operationally lean. Appropriate for v1.

---

## 6. Implementation Plan Review

- [x] 6 phases (including Phase 0 probe), 26 tasks, ordered with dependencies
- [x] Each phase has explicit acceptance-criteria reference
- [x] Risk register with 6 entries, all with mitigations
- [x] No circular dependencies
- [x] Phase 0 (`gpt-image-2` access probe) front-loads the highest-uncertainty risk

**Finding:** Plan is implementable in the stated 3–4 weeks for a single engineer.

---

## 7. Issues Found

### Critical Issues (MUST FIX)
**None.**

### Major Issues (SHOULD FIX — recommendations)

#### MAJ-001: LLM-judge non-determinism in filter score
The `impact` sub-score is LLM-judged (§3.3). Even at temperature=0, OpenAI does not guarantee bit-identical outputs. AC-002-3 addresses this with a ±0.05 tolerance — which is honest but means the filter threshold sits within the noise band.

**Recommendation:** Cache `(headline + summary) → impact_score` for at least the duration of one run, so within-run determinism is guaranteed. Cross-run determinism is acceptable noise (the dedup store prevents repeat-processing anyway).

**Status:** non-blocking; trivial change in TASK-010.

#### MAJ-002: Reject path marks dedup-consumed
Per AC-010-3, a rejected item is marked dedup-consumed so it doesn't reappear. This is correct for "operator decided this story doesn't fit" but wrong for "operator wasn't ready to decide and rejected by accident."

**Recommendation:** Add a `--unconsume` flag to the `reject` command (or a separate `unconsume <run_id>` command) that removes the dedup record so the item can be reconsidered in a future run. Alternatively, make dedup-on-reject configurable.

**Status:** non-blocking; small UX improvement in TASK-019.

### Minor Issues (NICE TO FIX)

#### MIN-001: Slug-naming function unspecified
§4.3 disk layout uses `<slug>` for the per-item folder name. The slug derivation algorithm (presumably from headline) is not specified.

**Suggestion:** Define `slugify(headline)[:60]` with collision suffix `-2`, `-3`, etc. Add to spec §4.3.

#### MIN-002: Approval feedback length not bounded
`revise --feedback "..."` accepts arbitrary text; no upper bound stated.

**Suggestion:** 2000-char cap.

#### MIN-003: `pending` CLI output format unspecified
For scripting, suggest `pending --json` flag emitting structured output (already noted in §6.1; just confirm format).

---

## 8. Decision

The specification:
- Covers every stated requirement with traceable test criteria
- Makes architectural decisions that exhibit expert judgment (avoiding sandbox over-spec, avoiding handoff state-scatter, placing guardrails at the correct boundary)
- Anticipates operational realities (model rollout uncertainty, content-policy blocks, dedup, restartable state)
- Leaves clean integration seams for the inevitable v2 (Telegram approval, multi-tenant, auto-publishing) without over-engineering for it now
- Documents its assumptions explicitly so the operator can correct course before implementation

The two MAJOR issues are recommendations, not blockers. Neither prevents the team from starting Phase 0/1, and both are addressable within existing-task slack.

---

**CERTIFICATION**

I, the CTO Reviewer, have conducted a meticulous and comprehensive review of this specification. I have:

- Verified all 12 functional and 5 non-functional requirements are addressed
- Validated all 7 design decisions are sound
- Confirmed the 24 acceptance criteria + 7 integration scenarios + 10 edge cases + 5 failure modes form a comprehensive test plan
- Reviewed security considerations (API keys, attribution, content policy)
- Assessed operational readiness (config, tracing, recovery)
- Examined the 26-task implementation plan (Phase 0 probe + 5 build phases) and 6-entry risk register

**I solemnly swear that this specification is exceptional in its completeness, correctness, and readiness for implementation. The design reflects expert judgment, not blind adherence to requirements. The test plan ensures acceptance-minded development from the start.**

**The two major recommendations should be addressed in the first iteration — particularly MAJ-001 (impact-score caching) — but they do not block approval.**

<promise>SPECIFICATION_APPROVED</promise>

---

## 9. Recommended First Implementation Step

Run **TASK-000** (Phase 0: `gpt-image-2` access probe) on Day 1, before anything else. This de-risks the highest-uncertainty external dependency in under 30 minutes of work. Everything else stays in plan order.
