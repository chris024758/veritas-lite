"""SQLite storage. Structured-field matching only: no FTS5, BM25 or embeddings."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("VERITAS_DB", Path(__file__).parent / "veritas.db"))

VALID_STATUSES = {"PENDING", "CONSISTENT", "FLAGGED", "CONFLICT"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    full_name TEXT NOT NULL,
    nicknames TEXT,
    role TEXT,
    notes TEXT,
    UNIQUE (case_id, full_name)
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    subject_id INTEGER REFERENCES subjects(id),
    started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    turn_index INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id INTEGER NOT NULL REFERENCES statements(id),
    claim_type TEXT NOT NULL,
    text TEXT NOT NULL,
    entities_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'CONSISTENT', 'FLAGGED', 'CONFLICT')),
    reason TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    evidence_type TEXT NOT NULL,
    description TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (case_id, evidence_type)
);
-- Not one of the six domain tables: the geocode/route cache from the PRD's risk table.
CREATE TABLE IF NOT EXISTS geo_cache (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _claim_row(row: sqlite3.Row) -> dict:
    claim = dict(row)
    claim["entities"] = json.loads(claim.pop("entities_json"))
    claim["details"] = json.loads(claim.pop("details_json"))
    return claim


def get_case(case_id: str) -> dict | None:
    with connect() as conn:
        case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if case is None:
            return None
        subjects = conn.execute(
            "SELECT * FROM subjects WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
        evidence = conn.execute(
            "SELECT * FROM evidence WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
    return {
        **dict(case),
        "subjects": [dict(s) for s in subjects],
        "evidence": [
            {**{k: e[k] for k in ("id", "case_id", "evidence_type", "description")},
             "metadata": json.loads(e["metadata_json"])}
            for e in evidence
        ],
    }


def create_session(case_id: str, subject_name: str) -> dict:
    """Returns the new session. subject_id stays NULL for a name not on the case file."""
    with connect() as conn:
        subject = conn.execute(
            "SELECT id FROM subjects WHERE case_id = ? AND full_name = ? COLLATE NOCASE",
            (case_id, subject_name),
        ).fetchone()
        subject_id = subject["id"] if subject else None
        cur = conn.execute(
            "INSERT INTO sessions (case_id, subject_id, started_at) VALUES (?, ?, ?)",
            (case_id, subject_id, datetime.now(timezone.utc).isoformat()),
        )
        return {"id": cur.lastrowid, "case_id": case_id, "subject_id": subject_id}


def get_session_row(session_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def add_statement(session_id: int, text: str) -> dict:
    with connect() as conn:
        turn = conn.execute(
            "SELECT COALESCE(MAX(turn_index), -1) + 1 FROM statements WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO statements (session_id, turn_index, text) VALUES (?, ?, ?)",
            (session_id, turn, text),
        )
        return {"id": cur.lastrowid, "session_id": session_id, "turn_index": turn, "text": text}


def add_claim(statement_id: int, claim_type: str, text: str, entities: dict) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO claims (statement_id, claim_type, text, entities_json) VALUES (?, ?, ?, ?)",
            (statement_id, claim_type, text, json.dumps(entities)),
        )
        return cur.lastrowid


def finish_claim(claim_id: int, status: str, reason: str, details: dict) -> None:
    """Written once, after the tool-calling loop for this claim finishes."""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid claim status: {status}")
    with connect() as conn:
        conn.execute(
            "UPDATE claims SET status = ?, reason = ?, details_json = ? WHERE id = ?",
            (status, reason, json.dumps(details), claim_id),
        )


def get_claims(statement_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM claims WHERE statement_id = ? ORDER BY id", (statement_id,)
        ).fetchall()
    return [_claim_row(r) for r in rows]


def get_session_history(session_id: int) -> dict | None:
    session = get_session_row(session_id)
    if session is None:
        return None
    with connect() as conn:
        statements = conn.execute(
            "SELECT * FROM statements WHERE session_id = ? ORDER BY turn_index", (session_id,)
        ).fetchall()
    session["statements"] = [{**dict(s), "claims": get_claims(s["id"])} for s in statements]
    return session


def cache_get(key: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT value_json FROM geo_cache WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value_json"]) if row else None


def cache_set(key: str, value: dict) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO geo_cache (key, value_json) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
