"""Tests for the CLI surface — happy-path argument parsing + DB integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from carousel_agent import cli as cli_module
from carousel_agent import store


@pytest.fixture()
def runner_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("CAROUSEL_HOME", str(tmp_path))
    return CliRunner()


def test_help_lists_commands(runner_in_tmp: CliRunner):
    result = runner_in_tmp.invoke(cli_module.cli, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "run", "pending", "status", "approve", "reject", "revise", "retry", "config"):
        assert cmd in result.output


def test_init_creates_db(runner_in_tmp: CliRunner, tmp_path: Path):
    result = runner_in_tmp.invoke(cli_module.cli, ["init"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".state" / "carousel.db").exists()


def test_config_show_emits_json(runner_in_tmp: CliRunner):
    result = runner_in_tmp.invoke(cli_module.cli, ["config", "show"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["rendering"]["image_model"] == "gpt-image-2"


def test_pending_empty(runner_in_tmp: CliRunner):
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    result = runner_in_tmp.invoke(cli_module.cli, ["pending"])
    assert result.exit_code == 0
    assert "(no runs)" in result.output


def test_pending_lists_awaiting_runs(runner_in_tmp: CliRunner, tmp_path: Path):
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    db_path = tmp_path / ".state" / "carousel.db"
    with store.open_store(db_path) as conn:
        store.insert_run(conn, "r-A", "awaiting_approval", "https://x.test/a")
        store.insert_run(conn, "r-B", "complete", "https://x.test/b")
    result = runner_in_tmp.invoke(cli_module.cli, ["pending"])
    assert result.exit_code == 0
    assert "r-A" in result.output
    assert "r-B" not in result.output


def test_status_unknown_run(runner_in_tmp: CliRunner):
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    result = runner_in_tmp.invoke(cli_module.cli, ["status", "r-missing"])
    assert result.exit_code == 2
    assert "not found" in result.output


def test_approve_records_decision_and_resumes(
    runner_in_tmp: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Approve records the decision in DB AND triggers manager.resume_on_approve."""
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    db_path = tmp_path / ".state" / "carousel.db"
    with store.open_store(db_path) as conn:
        store.insert_run(conn, "r-1", "awaiting_approval", "https://x.test/a")

    # Mock the pipeline resume so we don't hit the network.
    from carousel_agent.pipeline import manager

    monkeypatch.setattr(
        manager, "resume_on_approve", lambda cfg, run_id: [tmp_path / "slide-01.png", tmp_path / "slide-02.png"]
    )

    result = runner_in_tmp.invoke(cli_module.cli, ["approve", "r-1"])
    assert result.exit_code == 0, result.output

    with store.open_store(db_path) as conn:
        approval = store.get_approval(conn, "r-1")
    assert approval is not None
    assert approval["decision"] == "approve"
    assert "rendered 2 total slides" in result.output


def test_approve_rejects_wrong_state(runner_in_tmp: CliRunner, tmp_path: Path):
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    db_path = tmp_path / ".state" / "carousel.db"
    with store.open_store(db_path) as conn:
        store.insert_run(conn, "r-2", "complete", "https://x.test/a")
    result = runner_in_tmp.invoke(cli_module.cli, ["approve", "r-2"])
    assert result.exit_code == 2
    assert "not awaiting_approval" in result.output


def test_revise_requires_feedback(runner_in_tmp: CliRunner):
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    result = runner_in_tmp.invoke(cli_module.cli, ["revise", "r-x"])
    assert result.exit_code != 0
    assert "feedback" in result.output.lower()


def test_revise_caps_feedback_length(runner_in_tmp: CliRunner):
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    long_fb = "x" * 2001
    result = runner_in_tmp.invoke(cli_module.cli, ["revise", "r-x", "--feedback", long_fb])
    assert result.exit_code == 2


def test_run_command_invokes_pipeline(
    runner_in_tmp: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """`run` invokes manager.run_pipeline_sync; we mock it to avoid network calls."""
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    from carousel_agent.pipeline import manager

    captured = {}

    def fake_run_pipeline_sync(cfg, *, top_n=None):
        captured["called"] = True
        captured["top_n"] = top_n
        return []

    monkeypatch.setattr(manager, "run_pipeline_sync", fake_run_pipeline_sync)
    result = runner_in_tmp.invoke(cli_module.cli, ["run", "--top-n", "2"])
    assert result.exit_code == 0, result.output
    assert captured.get("called") is True
    assert captured.get("top_n") == 2
    assert "no items selected" in result.output


def test_reject_with_unconsume(runner_in_tmp: CliRunner, tmp_path: Path):
    runner_in_tmp.invoke(cli_module.cli, ["init"])
    db_path = tmp_path / ".state" / "carousel.db"
    with store.open_store(db_path) as conn:
        store.insert_run(conn, "r-3", "awaiting_approval", "https://x.test/a")
        store.mark_consumed(conn, "https://x.test/a", run_id="r-3")
    result = runner_in_tmp.invoke(cli_module.cli, ["reject", "r-3", "--unconsume"])
    assert result.exit_code == 0
    with store.open_store(db_path) as conn:
        assert store.is_consumed(conn, "https://x.test/a") is False
        run = store.get_run(conn, "r-3")
    assert run is not None and run["status"] == "rejected"
