"""Runtime path resolution.

Resolves the project working directory and standard subpaths. The working
directory is the current process cwd unless overridden by CAROUSEL_HOME.
"""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    override = os.environ.get("CAROUSEL_HOME")
    if override:
        return Path(override).resolve()
    return Path.cwd()


def state_dir() -> Path:
    return project_root() / ".state"


def db_path() -> Path:
    return state_dir() / "carousel.db"


def logs_dir() -> Path:
    return state_dir() / "logs"


def output_dir() -> Path:
    return project_root() / "output"


def config_dir() -> Path:
    return project_root() / ".config"


def user_config_path() -> Path:
    return config_dir() / "carousel.yaml"


def packaged_default_config() -> Path:
    """Bundled default config that ships with the package."""
    return Path(__file__).parent / "carousel.default.yaml"


def ensure_runtime_dirs() -> None:
    """Create state/, state/logs/, and output/ if missing. Idempotent."""
    for d in (state_dir(), logs_dir(), output_dir()):
        d.mkdir(parents=True, exist_ok=True)
