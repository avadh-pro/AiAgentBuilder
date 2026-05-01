"""SQLite store — runs, dedup, approvals.

Tables match `specs/carousel-agent-builder/specification.md` §4.2.

Migrations: linear, identified by an integer in the `schema_version` table.
Each migration is an idempotent SQL block applied in order.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from carousel_agent import paths

# Each entry is (version, ddl). Append-only; never edit historical entries.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id     TEXT PRIMARY KEY,
            status     TEXT NOT NULL,
            item_url   TEXT NOT NULL,
            geo        TEXT,
            score      REAL,
            state_blob BLOB,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dedup (
            canonical_url TEXT PRIMARY KEY,
            headline_hash TEXT,
            consumed_at   TEXT NOT NULL,
            run_id        TEXT
        );

        CREATE TABLE IF NOT EXISTS approvals (
            run_id      TEXT PRIMARY KEY,
            decision    TEXT NOT NULL,
            feedback    TEXT,
            decided_at  TEXT NOT NULL,
            decided_by  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
        CREATE INDEX IF NOT EXISTS idx_dedup_url ON dedup(canonical_url);
        """,
    ),
]


VALID_RUN_STATUSES = frozenset(
    {
        "pending",
        "awaiting_approval",
        "approved",
        "rejected",
        "complete",
        "errored",
        "policy-blocked",
    }
)

VALID_APPROVAL_DECISIONS = frozenset({"approve", "reject", "revise"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _current_version(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version")
    row = cur.fetchone()
    return int(row["v"])


def init_db(db_path: Path | None = None) -> Path:
    """Create the DB file and run any pending migrations. Idempotent."""
    target = db_path if db_path is not None else paths.db_path()
    conn = _connect(target)
    try:
        _ensure_schema_version_table(conn)
        current = _current_version(conn)
        for version, ddl in MIGRATIONS:
            if version <= current:
                continue
            conn.executescript(ddl)
            conn.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (version, _now()),
            )
            conn.commit()
    finally:
        conn.close()
    return target


@contextmanager
def open_store(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context-managed connection. Caller is responsible for commit/rollback."""
    target = db_path if db_path is not None else paths.db_path()
    init_db(target)
    conn = _connect(target)
    try:
        yield conn
    finally:
        conn.close()


# ---------- runs ----------

def insert_run(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    item_url: str,
    geo: str | None = None,
    score: float | None = None,
    state_blob: bytes | None = None,
) -> None:
    if status not in VALID_RUN_STATUSES:
        raise ValueError(f"invalid run status: {status}")
    now = _now()
    conn.execute(
        """
        INSERT INTO runs(run_id, status, item_url, geo, score, state_blob, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, status, item_url, geo, score, state_blob, now, now),
    )
    conn.commit()


def update_run_status(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    state_blob: bytes | None = None,
) -> None:
    if status not in VALID_RUN_STATUSES:
        raise ValueError(f"invalid run status: {status}")
    if state_blob is None:
        conn.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
            (status, _now(), run_id),
        )
    else:
        conn.execute(
            "UPDATE runs SET status = ?, state_blob = ?, updated_at = ? WHERE run_id = ?",
            (status, state_blob, _now(), run_id),
        )
    conn.commit()


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs_by_status(conn: sqlite3.Connection, status: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM runs WHERE status = ? ORDER BY created_at DESC", (status,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- dedup ----------

def is_consumed(conn: sqlite3.Connection, canonical_url: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM dedup WHERE canonical_url = ?", (canonical_url,)
    ).fetchone()
    return row is not None


def mark_consumed(
    conn: sqlite3.Connection,
    canonical_url: str,
    headline_hash: str | None = None,
    run_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO dedup(canonical_url, headline_hash, consumed_at, run_id)
        VALUES (?, ?, ?, ?)
        """,
        (canonical_url, headline_hash, _now(), run_id),
    )
    conn.commit()


def unmark_consumed(conn: sqlite3.Connection, canonical_url: str) -> int:
    cur = conn.execute("DELETE FROM dedup WHERE canonical_url = ?", (canonical_url,))
    conn.commit()
    return cur.rowcount


# ---------- approvals ----------

def record_approval(
    conn: sqlite3.Connection,
    run_id: str,
    decision: str,
    feedback: str | None = None,
    decided_by: str | None = None,
) -> None:
    if decision not in VALID_APPROVAL_DECISIONS:
        raise ValueError(f"invalid approval decision: {decision}")
    conn.execute(
        """
        INSERT OR REPLACE INTO approvals(run_id, decision, feedback, decided_at, decided_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, decision, feedback, _now(), decided_by),
    )
    conn.commit()


def get_approval(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM approvals WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None
