"""SQLite persistence with a small, forward-only migration for the demo database."""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).parent / "veritas.db"))
VALID_STATUSES = {"PENDING", "CONSISTENT", "FLAGGED", "CONFLICT"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT, summary TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS subjects (
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), full_name TEXT NOT NULL,
    role TEXT NOT NULL, notes TEXT, registered_vehicle_json TEXT, UNIQUE(case_id, full_name)
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
    subject_id TEXT REFERENCES subjects(id), started_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
    case_id TEXT NOT NULL REFERENCES cases(id), subject_id TEXT REFERENCES subjects(id), role TEXT,
    turn_index INTEGER NOT NULL, text TEXT NOT NULL, source TEXT DEFAULT 'text',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT, statement_id INTEGER NOT NULL REFERENCES statements(id),
    case_id TEXT NOT NULL REFERENCES cases(id), claim_type TEXT NOT NULL, text TEXT NOT NULL,
    entities_json TEXT, status TEXT DEFAULT 'PENDING'
        CHECK(status IN ('PENDING', 'CONSISTENT', 'FLAGGED', 'CONFLICT')),
    reason TEXT, tool_calls_json TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), evidence_type TEXT NOT NULL,
    description TEXT NOT NULL, metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS geo_cache (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    """Migrate the original integer-session schema once while preserving demo history."""
    if "sessions" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        return
    if conn.execute("PRAGMA table_info(sessions)").fetchone()[2].upper() == "TEXT":
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in ("claims", "statements", "sessions", "subjects", "evidence", "cases", "geo_cache"):
        conn.execute(f"ALTER TABLE {table} RENAME TO legacy_{table}")
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO cases(id, name, location, summary) SELECT id, name, location, summary FROM legacy_cases")
    subject_ids = {}
    for row in conn.execute("SELECT * FROM legacy_subjects"):
        subject_id = f"legacy-subject-{row['id']}"
        subject_ids[row["id"]] = subject_id
        conn.execute("INSERT INTO subjects VALUES (?, ?, ?, ?, ?, ?)",
                     (subject_id, row["case_id"], row["full_name"], row["role"] or "UNKNOWN", row["notes"], None))
    session_ids = {}
    for row in conn.execute("SELECT * FROM legacy_sessions"):
        session_id = f"legacy-session-{row['id']}"
        session_ids[row["id"]] = session_id
        conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                     (session_id, row["case_id"], subject_ids.get(row["subject_id"]), row["started_at"]))
    statement_cases = {}
    for row in conn.execute("SELECT * FROM legacy_statements"):
        session = conn.execute("SELECT case_id, subject_id FROM sessions WHERE id = ?", (session_ids[row["session_id"]],)).fetchone()
        statement_cases[row["id"]] = session["case_id"]
        conn.execute("INSERT INTO statements(id, session_id, case_id, subject_id, role, turn_index, text, source) VALUES (?, ?, ?, ?, ?, ?, ?, 'text')",
                     (row["id"], session_ids[row["session_id"]], session["case_id"], session["subject_id"], None, row["turn_index"], row["text"]))
    for row in conn.execute("SELECT * FROM legacy_claims"):
        details = json.loads(row["details_json"] or "{}")
        conn.execute("INSERT INTO claims(id, statement_id, case_id, claim_type, text, entities_json, status, reason, tool_calls_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (row["id"], row["statement_id"], statement_cases[row["statement_id"]], row["claim_type"], row["text"], row["entities_json"], row["status"], row["reason"], json.dumps(details.get("tool_calls", []))))
    for row in conn.execute("SELECT * FROM legacy_evidence"):
        conn.execute("INSERT INTO evidence VALUES (?, ?, ?, ?, ?)",
                     (f"legacy-evidence-{row['id']}", row["case_id"], row["evidence_type"], row["description"], row["metadata_json"]))
    for row in conn.execute("SELECT * FROM legacy_geo_cache"):
        conn.execute("INSERT INTO geo_cache VALUES (?, ?)", tuple(row))
    for table in ("claims", "statements", "sessions", "subjects", "evidence", "cases", "geo_cache"):
        conn.execute(f"DROP TABLE legacy_{table}")
    conn.execute("PRAGMA foreign_keys = ON")


def init_db() -> None:
    with connect() as conn:
        _migrate_legacy(conn)
        conn.executescript(SCHEMA)


def _claim_row(row: sqlite3.Row) -> dict:
    claim = dict(row)
    claim["entities"] = json.loads(claim.pop("entities_json") or "{}")
    claim["tool_calls"] = json.loads(claim.pop("tool_calls_json") or "[]")
    return claim


def get_case(case_id: str) -> dict | None:
    with connect() as conn:
        case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if case is None:
            return None
        subjects = conn.execute("SELECT * FROM subjects WHERE case_id = ? ORDER BY full_name", (case_id,)).fetchall()
        evidence = conn.execute("SELECT * FROM evidence WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    return {
        **dict(case),
        "subjects": [{**dict(s), "registered_vehicle": json.loads(s["registered_vehicle_json"]) if s["registered_vehicle_json"] else None} for s in subjects],
        "evidence": [{**dict(e), "metadata": json.loads(e["metadata_json"] or "{}")} for e in evidence],
    }


def create_session(case_id: str, subject_name: str) -> dict:
    with connect() as conn:
        subject = conn.execute("SELECT id FROM subjects WHERE case_id = ? AND full_name = ? COLLATE NOCASE", (case_id, subject_name)).fetchone()
        session = {"id": str(uuid.uuid4()), "case_id": case_id, "subject_id": subject["id"] if subject else None}
        conn.execute("INSERT INTO sessions(id, case_id, subject_id) VALUES (:id, :case_id, :subject_id)", session)
    return session


def get_session_row(session_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def add_statement(session: dict, text: str, *, source: str = "text", role: str | None = None) -> dict:
    with connect() as conn:
        turn = conn.execute("SELECT COALESCE(MAX(turn_index), -1) + 1 FROM statements WHERE session_id = ?", (session["id"],)).fetchone()[0]
        cur = conn.execute("INSERT INTO statements(session_id, case_id, subject_id, role, turn_index, text, source) VALUES (?, ?, ?, ?, ?, ?, ?)", (session["id"], session["case_id"], session["subject_id"], role, turn, text, source))
    return {"id": cur.lastrowid, "session_id": session["id"], "turn_index": turn, "text": text, "source": source}


def add_claim(statement_id: int, case_id: str, claim_type: str, text: str, entities: dict) -> int:
    with connect() as conn:
        return conn.execute("INSERT INTO claims(statement_id, case_id, claim_type, text, entities_json) VALUES (?, ?, ?, ?, ?)", (statement_id, case_id, claim_type, text, json.dumps(entities))).lastrowid


def finish_claim(claim_id: int, status: str, reason: str, tool_calls: list[dict]) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid claim status: {status}")
    with connect() as conn:
        conn.execute("UPDATE claims SET status = ?, reason = ?, tool_calls_json = ? WHERE id = ?", (status, reason, json.dumps(tool_calls), claim_id))


def get_claims(statement_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM claims WHERE statement_id = ? ORDER BY id", (statement_id,)).fetchall()
    return [_claim_row(row) for row in rows]


def get_session_history(session_id: str) -> dict | None:
    session = get_session_row(session_id)
    if session is None:
        return None
    with connect() as conn:
        statements = conn.execute("SELECT * FROM statements WHERE session_id = ? ORDER BY turn_index", (session_id,)).fetchall()
    session["statements"] = [{**dict(row), "claims": get_claims(row["id"])} for row in statements]
    return session


def cache_get(key: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT value_json FROM geo_cache WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value_json"]) if row else None


def cache_set(key: str, value: dict) -> None:
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO geo_cache(key, value_json) VALUES (?, ?)", (key, json.dumps(value)))
