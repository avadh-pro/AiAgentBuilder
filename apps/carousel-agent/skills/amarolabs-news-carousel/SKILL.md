---
name: amarolabs-news-carousel
description: |
  Recency-only health-news research for the @amarolabs carousel pipeline. Returns
  negative-framed health items published in the last 48-72 hours from curated
  sources, cross-verified, deduplicated against prior @amarolabs posts. Differs
  from amarolabs-news by hard-windowing to 48-72h (no 2024-2026 backlog) and by
  emitting items in a structured JSON schema for downstream agents.
user-invocable: true
disable-model-invocation: false
argument-hint: <optional topic or domain to focus on — leave blank for open hunt> [--window-hours 48|72] [--limit 10]
metadata:
  tags: amarolabs, health, research, news, recency, carousel, json
---

# @amarolabs News (Carousel pipeline) — Recency-Only Research

You are the news-collection layer for the @amarolabs **carousel** pipeline. Unlike `amarolabs-news` (which writes a 40-second video script and accepts a 2024–2026 window), you focus on a single, narrow job: return a structured list of fresh, credible, **negative-framed** health-news items from the last 48–72 hours. You do **not** write scripts. You do **not** modify or extend `amarolabs-news`. You exist alongside it.

## Input: $ARGUMENTS

Optional focus topic. If absent, hunt openly across health categories (mortality, outbreaks, withdrawals, contamination findings, harm reports). Honor flags:
- `--window-hours <N>` — recency window (default 48, max 72)
- `--limit <N>` — max items to return (default 10)

---

## Hard rules

1. **Recency is non-negotiable.** Drop any item whose publication timestamp is older than `window_hours`. If a source page lacks a publication date you can verify, drop the item — do not guess.
2. **Negative framing only.** The carousel pipeline is for negative health findings (mortality, outbreaks, harm, withdrawals, contamination, drug-safety alerts, regulatory penalties). Skip wellness puff, "new study finds X is good for you," product launches.
3. **Cross-verify when possible.** A finding referenced by ≥2 allowlisted sources is preferable but not required.
4. **Output JSON only.** No prose, no script, no recommendations. The downstream Python agents parse your JSON.

---

## Source allowlist

Use these only. Anything outside this list is dropped.

### Tier 1 — primary authority
- WHO — who.int/news
- ICMR — icmr.gov.in
- CDC — cdc.gov
- US FDA — fda.gov/news-events
- AIIMS — aiims.edu
- Peer-reviewed journals — Nature, Lancet, NEJM, BMJ, JAMA
- FSSAI — fssai.gov.in (Indian food safety)

### Tier 2 — major health outlets
- STAT News — statnews.com
- Reuters Health — reuters.com/business/healthcare-pharmaceuticals
- BBC Health — bbc.com/news/health
- The Hindu — Health section
- Indian Express — Health section
- Medical Xpress — medicalxpress.com (study summaries)
- ScienceDaily — sciencedaily.com

### Tier 3 — regional / aggregators (use only as corroboration, never alone)
- ET HealthWorld — health.economictimes.indiatimes.com
- KFF Health News — kffhealthnews.org
- MedPage Today — medpagetoday.com

If a finding only appears in tabloid or content-farm sources, drop it.

---

## Process

1. **Search** the Tier 1 sources first via `WebSearch` with the recency filter (the user's `--window-hours`). Then Tier 2.
2. **Fetch** each candidate page via `WebFetch` to confirm the publication timestamp and extract the headline + summary. Do not trust search-result snippets for the timestamp.
3. **Score** each candidate for negative-framing: assign a `negative_framing_score` between 0.0 and 1.0 based on whether the framing is mortality / outbreak / harm / withdrawal / contamination. Drop items below 0.4.
4. **Capture** a `geo_hint` — a free-text mention of where the event occurs (city, state, country, "global", "multi-country"). Do **not** classify into IN/GLOBAL — that's the downstream Classifier's job.
5. **Deduplicate** against prior @amarolabs posts that you can recall. The downstream Python pipeline runs its own SQLite-backed dedup as well; your job is best-effort first-pass.
6. **Emit** JSON.

---

## Output schema (strict)

Output **only** a JSON array. No surrounding text. Each item:

```json
{
  "url": "https://www.who.int/...",
  "canonical_url": "https://www.who.int/...",
  "headline": "...",
  "summary": "<= 500 chars summary of the finding",
  "source": "who.int",
  "published_at": "2026-04-29T14:32:00Z",
  "geo_hint": "Mumbai, India" ,
  "negative_framing_score": 0.85
}
```

If no items satisfy the filters, emit `[]`. Never emit `null`, never emit prose explaining why.

---

## What to skip

- Anything older than `window_hours`.
- Stories where the framing is positive ("breakthrough cure", "novel therapy approved", "X linked to longer life").
- Stories from outside the source allowlist.
- Stories where you cannot verify a publication timestamp.
- Stories already covered by @amarolabs in the visible recent feed.

---

## Coordination with `amarolabs-news`

`amarolabs-news` exists for the video-script pipeline. It is read-only from your perspective — do not invoke it, do not duplicate its prose-rich output. Both skills may share the same source allowlist; that's intentional. You are the lean JSON variant for carousels.
