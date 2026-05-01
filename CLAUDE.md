# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

This is a **documentation-only** knowledge base — there is no application code, build system, lint config, or tests, and therefore no build/lint/test commands. It serves two distinct purposes:

1. **Reference library** (`6.SandboxAgents.md/`) — curated material for the **OpenAI Agents SDK** ecosystem, extracted from the official OpenAI developer docs.
2. **Product planning workspace** (`Brainstorm/`) — active strategy notes for productizing the SDK knowledge (templates, consulting, possible SaaS).

Tasks here are typically *editorial* (refining docs, adding new SDK topics) or *strategic* (iterating on the brainstorm and execution plan), not coding tasks.

## Repository Structure

Reference docs under `6.SandboxAgents.md/`, organized by topic number:

- **1–5**: SDK fundamentals (overview, quickstart, agent definitions, models/providers, running agents)
- **6**: Sandbox agents (container-based execution environments, Python SDK only)
- **7**: Orchestration patterns (handoffs vs agents-as-tools)
- **8**: Guardrails and human-in-the-loop approval flows
- **9**: Results, state, and continuation strategies
- **10**: MCP integration and tracing/observability
- **11**: Evaluation and trace grading
- **12**: Voice agents (RealtimeAgent in TS, VoicePipeline in Python)
- **13.Agent Builder/**: Visual workflow editor docs, node reference, safety guidance
- **13.Agent Builder/14ChatKit/**: Embeddable chat UI — setup, theming, widgets, actions, advanced self-hosted integration

Strategy docs under `Brainstorm/`:

- **1stSession.md**: Problem framing, candidate product ideas (AgentShield, Agent Production Kit, distribution-first inversion), market intelligence, and the "if OpenAI ships this tomorrow, what's left?" lens used to evaluate ideas.
- **WeekByWeekPlan.md**: 12-week execution roadmap (templates → audience → consulting → product). Treat this as the source of truth for sequencing — refer to its phase/week structure when the user discusses "what's next."

## Key Concepts Across the Docs

**Two SDK paths**: TypeScript (`@openai/agents`) and Python (`openai-agents`). Code examples appear in both languages throughout.

**Three deployment paths**:
1. **SDK-first** — your server owns orchestration, tools, state, and approvals
2. **Agent Builder** — visual hosted workflow editor, published with versioned IDs
3. **ChatKit** — embeddable chat frontend backed by Agent Builder workflows or a self-hosted `ChatKitServer`

**Sandbox agents** are Python-only and introduce a harness/compute boundary: the harness owns the agent loop while the sandbox owns file/command execution. Sandbox providers include Unix-local, Docker, and hosted services (E2B, Modal, Vercel, Cloudflare, etc.).

## Working With This Repo

- Files in `6.SandboxAgents.md/` are markdown with embedded HTML (OpenAI docs components). Preserve the HTML structure when editing.
- Numbered filenames (e.g., `6.SandboxAgents.md`) encode reading order — maintain this convention when adding files.
- The `13.Agent Builder/` subtree groups Agent Builder and ChatKit docs together because they describe one product surface.
- Cross-references in the reference docs use OpenAI developer docs URLs — do not convert these to relative paths.
- The `Brainstorm/` files are free-form strategy notes (no embedded HTML, no numbering convention to preserve). Edit them as ordinary markdown.
- The repo name "AiAgentBuilder" reflects the *intended* product direction described in `Brainstorm/`, not anything currently built. Don't assume application scaffolding exists.
