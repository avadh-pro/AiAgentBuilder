"""Config loader.

Search order for the active config:
  1. Path passed via CLI flag / function argument.
  2. ./.config/carousel.yaml (user override, gitignored if local.yaml).
  3. The packaged default (carousel_agent/carousel.default.yaml).

Validation is via pydantic. Only known fields are accepted; unknown keys raise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from carousel_agent import paths


class ScheduleCfg(BaseModel):
    cron: str = "0 7 * * *"
    timezone: str = "Asia/Kolkata"


class CollectionCfg(BaseModel):
    window_hours: int = Field(default=48, ge=1, le=72)
    limit: int = Field(default=10, ge=1, le=100)


class FilterCfg(BaseModel):
    threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    source_authority_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    impact_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    novelty_weight: float = Field(default=0.2, ge=0.0, le=1.0)

    @field_validator("novelty_weight")
    @classmethod
    def _weights_sum_to_one(cls, v: float, info: Any) -> float:
        s = (
            info.data.get("source_authority_weight", 0.0)
            + info.data.get("impact_weight", 0.0)
            + v
        )
        if abs(s - 1.0) > 1e-6:
            raise ValueError(
                f"filter weights must sum to 1.0; got {s:.6f}"
            )
        return v


class TriageCfg(BaseModel):
    top_n: int = Field(default=1, ge=1, le=10)


class RenderingCfg(BaseModel):
    image_model: str = "gpt-image-2"
    fallback_model: str = "gpt-image-1"
    size: str = "1080x1350"
    retries: int = Field(default=3, ge=0, le=10)


class OutputCfg(BaseModel):
    base_dir: str = "./output"


class StateCfg(BaseModel):
    db_path: str = "./.state/carousel.db"


class LoggingCfg(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: str = "./.state/logs/carousel.log"


class Config(BaseModel):
    schedule: ScheduleCfg = ScheduleCfg()
    collection: CollectionCfg = CollectionCfg()
    filter: FilterCfg = FilterCfg()
    triage: TriageCfg = TriageCfg()
    rendering: RenderingCfg = RenderingCfg()
    output: OutputCfg = OutputCfg()
    state: StateCfg = StateCfg()
    logging: LoggingCfg = LoggingCfg()

    model_config = {"extra": "forbid"}

    def _absolutize(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else paths.project_root() / path

    def absolute_db_path(self) -> Path:
        return self._absolutize(self.state.db_path)

    def absolute_log_file(self) -> Path:
        return self._absolutize(self.logging.file)

    def absolute_output_dir(self) -> Path:
        return self._absolutize(self.output.base_dir)


class ConfigError(RuntimeError):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path}: top-level YAML must be a mapping, got {type(loaded).__name__}")
    return loaded


def resolve_config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        if not explicit.exists():
            raise ConfigError(f"config not found: {explicit}")
        return explicit
    user = paths.user_config_path()
    if user.exists():
        return user
    return paths.packaged_default_config()


def load_config(path: Path | None = None) -> Config:
    target = resolve_config_path(path)
    raw = _read_yaml(target)
    try:
        return Config(**raw)
    except ValidationError as e:
        raise ConfigError(f"invalid config in {target}:\n{e}") from e


def load_config_or_defaults(path: Path | None = None) -> Config:
    """Like load_config but returns built-in defaults silently if no file exists."""
    try:
        return load_config(path)
    except ConfigError:
        if path is None:
            return Config()
        raise
