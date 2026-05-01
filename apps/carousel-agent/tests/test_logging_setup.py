"""Tests for logging_setup — run_id correlation, idempotency, file handler."""

from __future__ import annotations

import logging
from pathlib import Path

from carousel_agent import logging_setup


def test_setup_logging_idempotent():
    logging_setup._reset_for_tests()
    logging_setup.setup_logging(level="INFO")
    initial_handlers = len(logging.getLogger().handlers)
    logging_setup.setup_logging(level="INFO")  # second call no-op
    assert len(logging.getLogger().handlers) == initial_handlers


def test_run_id_appears_in_file(tmp_path: Path):
    logging_setup._reset_for_tests()
    log_file = tmp_path / "test.log"
    logging_setup.setup_logging(level="DEBUG", file_path=log_file)

    logging_setup.set_run_id("r-test-42")
    logging.getLogger("carousel_agent.x").info("hello")

    # Flush handlers
    for h in logging.getLogger().handlers:
        h.flush()

    text = log_file.read_text(encoding="utf-8")
    assert "r-test-42" in text
    assert "hello" in text


def test_run_id_default_is_dash(tmp_path: Path):
    logging_setup._reset_for_tests()
    log_file = tmp_path / "test.log"
    logging_setup.setup_logging(level="DEBUG", file_path=log_file)

    logging_setup.set_run_id(None)
    logging.getLogger("carousel_agent.y").info("nope")
    for h in logging.getLogger().handlers:
        h.flush()

    text = log_file.read_text(encoding="utf-8")
    assert "[-]" in text
