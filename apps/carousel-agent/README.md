# carousel-agent

Health-news → Instagram carousel pipeline for @amarolabs. Built on the OpenAI Agents SDK (Python).

See `../../specs/carousel-agent-builder/specification.md` for the full design.

## Status

**Phase 1 (foundation) — in progress.** The pipeline itself is not yet wired; only scaffold, config, store, and CLI shells are in place.

## Quick start (development)

```powershell
# from this directory
pip install -e .[dev]

# install the three new Claude Code skills the pipeline depends on:
# copy each skills/<slug>/SKILL.md to ~/.claude/skills/<slug>/SKILL.md
# (Windows: %USERPROFILE%\.claude\skills\<slug>\SKILL.md)
# the existing carousel-style, neuro-scriptwriter, amarolabs-news skills
# remain untouched — those are the inheritance source for the new ones.

# verify CLI loads
python -m carousel_agent --help

# initialize the local SQLite store
python -m carousel_agent init

# show config
python -m carousel_agent config show
```

## Layout

```
carousel_agent/
  __main__.py        python -m carousel_agent
  cli.py             click commands (run, approve, reject, ...)
  config.py          YAML config + pydantic validation
  store.py           SQLite (runs, dedup, approvals)
  logging_setup.py   structured logging + run_id correlation
  paths.py           runtime path resolution
  carousel.default.yaml   shipped default config
tests/               pytest
```

## Phases

- **Phase 0** ✅ — Image API access probe (`specs/carousel-agent-builder/phase0_probe.py`)
- **Phase 1** 🚧 — Foundation (this directory)
- **Phase 2** — Three new skills (`amarolabs-news-carousel`, `neuro-carousel-writer`, `amara-news-carousel`)
- **Phase 3** — Pipeline agents
- **Phase 4** — Renderer + approval gate
- **Phase 5** — Persister + end-to-end tests
