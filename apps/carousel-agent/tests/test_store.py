"""Tests for carousel_agent.store — schema init, idempotency, CRUD."""

from __future__ import annotations

from pathlib import Path

import pytest

from carousel_agent import store


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return tmp_path / "test_carousel.db"


def test_init_db_creates_file(db: Path):
    assert not db.exists()
    store.init_db(db)
    assert db.exists()


def test_init_db_is_idempotent(db: Path):
    store.init_db(db)
    store.init_db(db)
    with store.open_store(db) as conn:
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
    versions = sorted(r["version"] for r in rows)
    assert versions == [1]


def test_run_insert_and_fetch(db: Path):
    with store.open_store(db) as conn:
        store.insert_run(
            conn, run_id="r1", status="pending", item_url="https://example.com/a"
        )
        run = store.get_run(conn, "r1")
    assert run is not None
    assert run["status"] == "pending"
    assert run["item_url"] == "https://example.com/a"


def test_run_status_update(db: Path):
    with store.open_store(db) as conn:
        store.insert_run(conn, "r1", "pending", "https://example.com/a")
        store.update_run_status(conn, "r1", "awaiting_approval", state_blob=b"\x01\x02")
        run = store.get_run(conn, "r1")
    assert run is not None
    assert run["status"] == "awaiting_approval"
    assert run["state_blob"] == b"\x01\x02"


def test_run_invalid_status_raises(db: Path):
    with store.open_store(db) as conn:
        with pytest.raises(ValueError):
            store.insert_run(conn, "r1", "not-a-status", "https://example.com/a")


def test_dedup_lifecycle(db: Path):
    url = "https://example.com/a"
    with store.open_store(db) as conn:
        assert store.is_consumed(conn, url) is False
        store.mark_consumed(conn, url, headline_hash="h1", run_id="r1")
        assert store.is_consumed(conn, url) is True
        # mark twice is a no-op
        store.mark_consumed(conn, url, headline_hash="h1", run_id="r1")
        # unmark
        assert store.unmark_consumed(conn, url) == 1
        assert store.is_consumed(conn, url) is False


def test_approval_records_and_overwrites(db: Path):
    with store.open_store(db) as conn:
        store.insert_run(conn, "r1", "awaiting_approval", "https://example.com/a")
        store.record_approval(conn, "r1", "approve", decided_by="cli")
        a1 = store.get_approval(conn, "r1")
        assert a1 is not None
        assert a1["decision"] == "approve"

        # change of mind
        store.record_approval(conn, "r1", "reject", decided_by="cli")
        a2 = store.get_approval(conn, "r1")
        assert a2 is not None
        assert a2["decision"] == "reject"


def test_approval_invalid_decision_raises(db: Path):
    with store.open_store(db) as conn:
        store.insert_run(conn, "r1", "awaiting_approval", "https://example.com/a")
        with pytest.raises(ValueError):
            store.record_approval(conn, "r1", "maybe")


def test_list_runs_by_status(db: Path):
    with store.open_store(db) as conn:
        store.insert_run(conn, "r1", "pending", "https://example.com/a")
        store.insert_run(conn, "r2", "awaiting_approval", "https://example.com/b")
        store.insert_run(conn, "r3", "awaiting_approval", "https://example.com/c")
        pending = store.list_runs_by_status(conn, "awaiting_approval")
    assert len(pending) == 2
    assert {r["run_id"] for r in pending} == {"r2", "r3"}
