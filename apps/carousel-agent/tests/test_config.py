"""Tests for carousel_agent.config — load, validate, error paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from carousel_agent import config


def _write_yaml(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")


def test_packaged_default_loads():
    cfg = config.load_config()
    # Default config either lives at .config/carousel.yaml in cwd or ships with the package.
    assert cfg.rendering.image_model == "gpt-image-2"
    assert cfg.rendering.fallback_model == "gpt-image-1"
    assert cfg.collection.window_hours == 48


def test_explicit_path_loads(tmp_path: Path):
    p = tmp_path / "c.yaml"
    _write_yaml(
        p,
        """
schedule: {cron: "0 9 * * *", timezone: "UTC"}
collection: {window_hours: 24, limit: 5}
filter:
  threshold: 0.7
  source_authority_weight: 0.5
  impact_weight: 0.3
  novelty_weight: 0.2
triage: {top_n: 2}
rendering: {image_model: "gpt-image-1", fallback_model: "gpt-image-1", size: "1024x1024", retries: 1}
output: {base_dir: "./out"}
state: {db_path: "./.s/x.db"}
logging: {level: "DEBUG", file: "./.s/l.log"}
""",
    )
    cfg = config.load_config(p)
    assert cfg.schedule.timezone == "UTC"
    assert cfg.collection.window_hours == 24
    assert cfg.filter.threshold == 0.7
    assert cfg.triage.top_n == 2
    assert cfg.rendering.image_model == "gpt-image-1"


def test_window_hours_upper_bound(tmp_path: Path):
    p = tmp_path / "c.yaml"
    _write_yaml(p, "collection: {window_hours: 100}\n")
    with pytest.raises(config.ConfigError):
        config.load_config(p)


def test_filter_weights_must_sum_to_one(tmp_path: Path):
    p = tmp_path / "c.yaml"
    _write_yaml(
        p,
        """
filter:
  threshold: 0.5
  source_authority_weight: 0.5
  impact_weight: 0.4
  novelty_weight: 0.4
""",
    )
    with pytest.raises(config.ConfigError) as exc:
        config.load_config(p)
    assert "weights must sum" in str(exc.value)


def test_unknown_key_rejected(tmp_path: Path):
    p = tmp_path / "c.yaml"
    _write_yaml(p, "mystery_section: {nope: 1}\n")
    with pytest.raises(config.ConfigError):
        config.load_config(p)


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(config.ConfigError):
        config.load_config(tmp_path / "does-not-exist.yaml")


def test_invalid_logging_level(tmp_path: Path):
    p = tmp_path / "c.yaml"
    _write_yaml(p, 'logging: {level: "TRACE"}\n')
    with pytest.raises(config.ConfigError):
        config.load_config(p)
