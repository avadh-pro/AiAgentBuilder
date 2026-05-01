"""Logging setup with run_id correlation.

Usage:
    from carousel_agent.logging_setup import setup_logging, set_run_id
    setup_logging(level="INFO", file_path=Path("./.state/logs/carousel.log"))
    set_run_id("r-1234")
    logging.getLogger(__name__).info("starting collection")
    # -> 2026-05-01T... INFO [r-1234] carousel_agent.collector: starting collection
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_run_id_var: ContextVar[str | None] = ContextVar("carousel_run_id", default=None)

_LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(run_id)s] %(name)s: %(message)s"


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id_var.get() or "-"
        return True


def set_run_id(run_id: str | None) -> None:
    _run_id_var.set(run_id)


def get_run_id() -> str | None:
    return _run_id_var.get()


_configured = False


def setup_logging(
    level: str | int = "INFO",
    file_path: Path | None = None,
    *,
    force: bool = False,
) -> None:
    """Configure root logger. Idempotent unless force=True."""
    global _configured
    if _configured and not force:
        return

    root = logging.getLogger()
    root.setLevel(level)

    # Wipe handlers if forcing reconfigure (e.g. in tests).
    if force:
        for h in list(root.handlers):
            root.removeHandler(h)

    formatter = logging.Formatter(_LOG_FORMAT)
    run_id_filter = _RunIdFilter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(run_id_filter)
    root.addHandler(console)

    if file_path is not None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(run_id_filter)
        root.addHandler(file_handler)

    _configured = True


def _reset_for_tests() -> None:
    """Test-only helper: clear the configured flag and remove handlers."""
    global _configured
    _configured = False
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)


# Suppress noisy third-party loggers by default.
def quiet_noisy_loggers() -> None:
    for name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# Re-export for convenience so callers can avoid an extra import.
__all__ = [
    "setup_logging",
    "set_run_id",
    "get_run_id",
    "get_logger",
    "quiet_noisy_loggers",
]


# Ensure record.run_id always exists even if filter wasn't attached (defensive).
class _DefaultRunIdAttr(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = "-"
        return True


def _install_default_attr_filter(_logger: Any = logging.getLogger()) -> None:
    _logger.addFilter(_DefaultRunIdAttr())


_install_default_attr_filter()
