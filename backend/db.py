"""SQLite storage. Structured-field matching only: no FTS5, BM25 or embeddings."""
import json
from contextlib import nullcontext
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
    summary TEXT,
    incident_start TEXT,
    incident_end TEXT
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
    started_at TEXT NOT NULL,
    ended_at TEXT,
    report_json TEXT
);
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    turn_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    followups_json TEXT NOT NULL DEFAULT '[]'
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
-- Claim illustrations stay separate from the claim's verification details.
CREATE TABLE IF NOT EXISTS claim_illustrations (
    claim_id INTEGER PRIMARY KEY REFERENCES claims(id) ON DELETE CASCADE,
    illustration_prompt TEXT NOT NULL,
    illustration_preview TEXT,
    image TEXT
);
-- Case records. Seeded ones, ones proposed from a witness's statement, and uploaded proof.
-- A case can hold several records of one type (two sightings, two tickets).
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    evidence_type TEXT NOT NULL,
    description TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    image TEXT,
    image_kind TEXT,           -- illustration | generated | photo
    source TEXT NOT NULL DEFAULT 'seed',  -- seed | statement | upload
    session_id INTEGER REFERENCES sessions(id),
    statement_id INTEGER REFERENCES statements(id),
    subject_id INTEGER REFERENCES subjects(id),
    created_at TEXT,
    illustration_prompt TEXT,
    illustration_preview TEXT
);
-- Alibi-check findings: a new claim clashing with an earlier claim (SELF or WITNESS) or with a
-- case-file record (EVIDENCE). Exactly one of other_claim_id / evidence_id is set.
CREATE TABLE IF NOT EXISTS alibi_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    statement_id INTEGER NOT NULL REFERENCES statements(id),
    claim_id INTEGER NOT NULL REFERENCES claims(id),
    other_claim_id INTEGER REFERENCES claims(id),
    evidence_id INTEGER REFERENCES evidence(id),
    kind TEXT NOT NULL CHECK (kind IN ('SELF', 'WITNESS', 'EVIDENCE')),
    severity TEXT NOT NULL CHECK (severity IN ('HIGH', 'MEDIUM', 'LOW')),
    explanation TEXT NOT NULL,
    new_quote TEXT,
    prior_quote TEXT
);
-- Items listed on a stolen-property record, each with an illustration.
CREATE TABLE IF NOT EXISTS evidence_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id INTEGER NOT NULL REFERENCES evidence(id),
    name TEXT NOT NULL,
    description TEXT,
    weight TEXT,
    value TEXT,
    image TEXT,
    UNIQUE (evidence_id, name)
);
-- Images the investigator adds during an interview.
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    after_turn INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT,
    caption TEXT,
    created_at TEXT NOT NULL,
    evidence_id INTEGER REFERENCES evidence(id)
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


# Columns added after the first release, so an existing veritas.db gains them on startup.
MIGRATIONS = [
    ("cases", "incident_start", "TEXT"),
    ("cases", "incident_end", "TEXT"),
    ("sessions", "ended_at", "TEXT"),
    ("sessions", "report_json", "TEXT"),
    ("statements", "followups_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("subjects", "phone", "TEXT"),
    ("subjects", "vehicle", "TEXT"),
    ("subjects", "plate", "TEXT"),
    ("subjects", "relation", "TEXT"),
    ("cases", "status", "TEXT NOT NULL DEFAULT 'Open'"),
    ("evidence", "image", "TEXT"),
    ("evidence", "image_kind", "TEXT"),
    ("evidence", "source", "TEXT NOT NULL DEFAULT 'seed'"),
    ("evidence", "session_id", "INTEGER REFERENCES sessions(id)"),
    ("evidence", "statement_id", "INTEGER REFERENCES statements(id)"),
    ("evidence", "subject_id", "INTEGER REFERENCES subjects(id)"),
    ("evidence", "created_at", "TEXT"),
    ("evidence", "illustration_prompt", "TEXT"),
    ("evidence", "illustration_preview", "TEXT"),
    ("cases", "incident_date", "TEXT"),
    ("attachments", "evidence_id", "INTEGER REFERENCES evidence(id)"),
    ("attachments", "extraction_json", "TEXT"),
]

EVIDENCE_COLUMNS = ("id, case_id, evidence_type, description, metadata_json, image, image_kind, "
                    "source, session_id, statement_id, subject_id, created_at, illustration_prompt, illustration_preview")


def _drop_evidence_unique() -> None:
    """Older databases have UNIQUE (case_id, evidence_type). SQLite cannot drop a constraint,
    so the table is rebuilt with the same rows and ids. Foreign keys must be off for the swap,
    and that pragma only works outside a transaction, hence the separate connection."""
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'evidence'").fetchone()
        if not row or "UNIQUE" not in row[0]:
            return
        create = "CREATE TABLE evidence_new (" + SCHEMA.split("CREATE TABLE IF NOT EXISTS evidence (")[1].split(");")[0] + ");"
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        conn.execute(create)
        conn.execute(f"INSERT INTO evidence_new ({EVIDENCE_COLUMNS}) SELECT {EVIDENCE_COLUMNS} FROM evidence")
        conn.execute("DROP TABLE evidence")
        conn.execute("ALTER TABLE evidence_new RENAME TO evidence")
        conn.execute("COMMIT")
    finally:
        conn.close()

VALID_ROLES = {"Suspect", "Witness", "Victim", "Other"}
SUBJECT_FIELDS = ("full_name", "role", "notes", "phone", "vehicle", "plate", "relation")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        for table, column, decl in MIGRATIONS:
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    _drop_evidence_unique()


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
            """SELECT s.*, (SELECT COUNT(*) FROM sessions se WHERE se.subject_id = s.id) AS interviews
               FROM subjects s WHERE s.case_id = ? ORDER BY s.id""", (case_id,)
        ).fetchall()
        evidence = conn.execute(
            "SELECT * FROM evidence WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
        people = {s["id"]: s["full_name"] for s in subjects}
        items_by = {}
        for item in conn.execute(
            "SELECT i.* FROM evidence_items i JOIN evidence e ON i.evidence_id = e.id "
            "WHERE e.case_id = ? ORDER BY i.id", (case_id,)
        ):
            items_by.setdefault(item["evidence_id"], []).append(item)
    return {
        **dict(case),
        "subjects": [dict(s) for s in subjects],
        "evidence": [
            {**{k: e[k] for k in ("id", "case_id", "evidence_type", "description", "image", "image_kind",
                                  "source", "session_id", "statement_id", "subject_id", "created_at")},
             "provided_by": people.get(e["subject_id"]),
             "metadata": json.loads(e["metadata_json"]),
             "items": [dict(i) for i in items_by.get(e["id"], [])]}
            for e in evidence
        ],
    }


def list_cases() -> list[dict]:
    """The case directory: each case with people and interview counts and last activity."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT c.id, c.name, c.location, c.status, c.incident_start, c.incident_end,
                      (SELECT COUNT(*) FROM subjects s WHERE s.case_id = c.id) AS people,
                      (SELECT COUNT(*) FROM evidence e WHERE e.case_id = c.id) AS evidence,
                      (SELECT COUNT(*) FROM sessions se WHERE se.case_id = c.id) AS interviews,
                      (SELECT MAX(se.started_at) FROM sessions se WHERE se.case_id = c.id) AS last_activity
               FROM cases c ORDER BY c.id"""
        ).fetchall()
    return [dict(r) for r in rows]


def _subject_with_counts(conn, subject_id: int) -> dict | None:
    row = conn.execute(
        """SELECT s.*, (SELECT COUNT(*) FROM sessions se WHERE se.subject_id = s.id) AS interviews
           FROM subjects s WHERE s.id = ?""", (subject_id,)
    ).fetchone()
    return dict(row) if row else None


def get_subject(subject_id: int) -> dict | None:
    with connect() as conn:
        return _subject_with_counts(conn, subject_id)


def add_subject(case_id: str, fields: dict) -> tuple[dict, bool]:
    """(person, existing). A name already on the case, ignoring case, returns that person."""
    with connect() as conn:
        found = conn.execute(
            "SELECT id FROM subjects WHERE case_id = ? AND full_name = ? COLLATE NOCASE",
            (case_id, fields["full_name"].strip()),
        ).fetchone()
        if found:
            return _subject_with_counts(conn, found["id"]), True
        values = {k: (fields.get(k) or "").strip() or None for k in SUBJECT_FIELDS}
        values["full_name"] = fields["full_name"].strip()
        values["nicknames"] = ""
        cur = conn.execute(
            """INSERT INTO subjects (case_id, full_name, nicknames, role, notes, phone, vehicle, plate, relation)
               VALUES (:case_id, :full_name, :nicknames, :role, :notes, :phone, :vehicle, :plate, :relation)""",
            {**values, "case_id": case_id},
        )
        return _subject_with_counts(conn, cur.lastrowid), False


def update_subject(subject_id: int, fields: dict) -> dict | None:
    changes = {k: v for k, v in fields.items() if k in ("role", "notes", "phone", "vehicle", "plate", "relation")}
    with connect() as conn:
        if changes:
            conn.execute(
                f"UPDATE subjects SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                [*changes.values(), subject_id],
            )
        return _subject_with_counts(conn, subject_id)


def create_session_for_subject(case_id: str, subject_id: int) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (case_id, subject_id, started_at) VALUES (?, ?, ?)",
            (case_id, subject_id, datetime.now(timezone.utc).isoformat()),
        )
        return {"id": cur.lastrowid, "case_id": case_id, "subject_id": subject_id}


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
    if row is None:
        return None
    session = dict(row)
    session["report"] = json.loads(session.pop("report_json") or "null")
    return session


def end_session(session_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE sessions SET ended_at = COALESCE(ended_at, ?) WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )


def save_report(session_id: int, report: dict) -> None:
    with connect() as conn:
        conn.execute("UPDATE sessions SET report_json = ? WHERE id = ?", (json.dumps(report), session_id))


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
        illustrations = {
            row["id"]: dict(row)
            for row in conn.execute(
                """SELECT c.id, c.statement_id, s.session_id, i.illustration_prompt, i.illustration_preview, i.image
                   FROM claim_illustrations i JOIN claims c ON c.id = i.claim_id
                   JOIN statements s ON s.id = c.statement_id WHERE c.statement_id = ?""",
                (statement_id,),
            )
        }
    return [{**_claim_row(row), "illustration": illustrations.get(row["id"])} for row in rows]


def save_claim_illustration(claim_id: int, prompt: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO claim_illustrations (claim_id, illustration_prompt) VALUES (?, ?)", (claim_id, prompt))


def _statement_row(row: sqlite3.Row) -> dict:
    statement = dict(row)
    statement["followups"] = json.loads(statement.pop("followups_json") or "[]")
    return statement


def set_followups(statement_id: int, followups: list[dict]) -> None:
    with connect() as conn:
        conn.execute("UPDATE statements SET followups_json = ? WHERE id = ?",
                     (json.dumps(followups), statement_id))


def add_attachment(session: dict, filename: str, original_name: str | None, caption: str | None) -> dict:
    """File the image and link its attachment in a single transaction."""
    session_id = session["id"]
    url = f"/uploads/{filename}"
    metadata = {"filename": original_name} if original_name else {}
    if caption:
        metadata["caption"] = caption
    with connect() as conn:
        evidence = add_evidence(
            session["case_id"], "uploaded_image", caption or original_name or "Uploaded image", metadata,
            source="upload", image=url, image_kind="photo", session_id=session_id,
            subject_id=session["subject_id"], connection=conn,
        )
        after_turn = conn.execute("SELECT COUNT(*) FROM statements WHERE session_id = ?", (session_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO attachments (session_id, after_turn, filename, original_name, caption, created_at, evidence_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, after_turn, filename, original_name, caption, datetime.now(timezone.utc).isoformat(), evidence["id"]),
        )
        row = conn.execute("SELECT * FROM attachments WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {**_attachment_row(row), "url": url, "evidence": evidence}


def _attachment_row(row: sqlite3.Row) -> dict:
    attachment = dict(row)
    extraction = attachment.pop("extraction_json", None)
    if extraction is not None:
        attachment["extraction"] = json.loads(extraction)
    return attachment


def get_attachment(session_id: int, attachment_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM attachments WHERE session_id = ? AND id = ?",
                           (session_id, attachment_id)).fetchone()
    return _attachment_row(row) if row is not None else None


def save_attachment_extraction(session_id: int, attachment_id: int, result: dict) -> None:
    with connect() as conn:
        conn.execute("UPDATE attachments SET extraction_json = ? WHERE session_id = ? AND id = ?",
                     (json.dumps(result), session_id, attachment_id))


def add_evidence(case_id: str, evidence_type: str, description: str, metadata: dict, *,
                 source: str, image: str | None = None, image_kind: str | None = None,
                 session_id: int | None = None, statement_id: int | None = None,
                 subject_id: int | None = None, connection: sqlite3.Connection | None = None,
                 illustration_prompt: str | None = None) -> dict:
    """A record from a witness's statement or an uploaded image."""
    with (connect() if connection is None else nullcontext(connection)) as conn:
        cur = conn.execute(
            """INSERT INTO evidence (case_id, evidence_type, description, metadata_json, image, image_kind,
                   source, session_id, statement_id, subject_id, created_at, illustration_prompt)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (case_id, evidence_type, description, json.dumps(metadata), image, image_kind, source,
             session_id, statement_id, subject_id, datetime.now(timezone.utc).isoformat(), illustration_prompt),
        )
        row = conn.execute("SELECT * FROM evidence WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _evidence_row(row)


def _evidence_row(row: sqlite3.Row) -> dict:
    record = dict(row)
    record["metadata"] = json.loads(record.pop("metadata_json"))
    return record


def get_illustration_record(session_id: int, item_id: int, target: str) -> dict | None:
    with connect() as conn:
        if target == "claims":
            row = conn.execute(
                """SELECT c.id, c.statement_id, s.session_id, i.illustration_prompt, i.illustration_preview, i.image
                   FROM claim_illustrations i JOIN claims c ON c.id = i.claim_id
                   JOIN statements s ON s.id = c.statement_id WHERE s.session_id = ? AND c.id = ?""",
                (session_id, item_id),
            ).fetchone()
            return dict(row) if row else None
        row = conn.execute(
            "SELECT * FROM evidence WHERE id = ? AND session_id = ? AND source = 'statement'",
            (item_id, session_id),
        ).fetchone()
    return _evidence_row(row) if row else None


def save_illustration_preview(item_id: int, preview: str, target: str) -> bool:
    table, key = ("claim_illustrations", "claim_id") if target == "claims" else ("evidence", "id")
    with connect() as conn:
        return conn.execute(
            f"UPDATE {table} SET illustration_preview = ? WHERE {key} = ? AND image IS NULL AND illustration_preview IS NULL",
            (preview, item_id),
        ).rowcount == 1


def review_illustration(item_id: int, preview: str, approve: bool, target: str) -> bool:
    table, key = ("claim_illustrations", "claim_id") if target == "claims" else ("evidence", "id")
    values = "illustration_preview = NULL"
    if approve:
        values += ", image = illustration_preview"
        if target == "evidence":
            values += ", image_kind = 'generated'"
    with connect() as conn:
        return conn.execute(
            f"UPDATE {table} SET {values} WHERE {key} = ? AND image IS NULL AND illustration_preview = ?",
            (item_id, preview),
        ).rowcount == 1


def get_claim_context(claim_id: int) -> dict | None:
    """One claim with who said it, in which interview and turn."""
    with connect() as conn:
        row = conn.execute(CLAIM_CONTEXT_SQL + " WHERE c.id = ?", (claim_id,)).fetchone()
    return _claim_row(row) if row else None


def latest_statement_id(session_id: int) -> int | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM statements WHERE session_id = ? ORDER BY turn_index DESC LIMIT 1", (session_id,)
        ).fetchone()
    return row["id"] if row else None


def get_attachments(session_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM attachments WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
    return [_attachment_row(row) for row in rows]


def count_statements(session_id: int) -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM statements WHERE session_id = ?", (session_id,)).fetchone()[0]


def get_session_history(session_id: int) -> dict | None:
    session = get_session_row(session_id)
    if session is None:
        return None
    with connect() as conn:
        statements = conn.execute(
            "SELECT * FROM statements WHERE session_id = ? ORDER BY turn_index", (session_id,)
        ).fetchall()
    session["statements"] = [
        {**_statement_row(s), "claims": get_claims(s["id"]),
         "alibi_findings": get_findings(statement_id=s["id"])}
        for s in statements
    ]
    session["attachments"] = get_attachments(session_id)
    return session


CLAIM_CONTEXT_SQL = """
    SELECT c.*, st.turn_index, st.session_id, se.subject_id,
           COALESCE(su.full_name, 'Unknown') AS speaker, COALESCE(su.role, 'Unknown') AS speaker_role
    FROM claims c
    JOIN statements st ON c.statement_id = st.id
    JOIN sessions se ON st.session_id = se.id
    LEFT JOIN subjects su ON se.subject_id = su.id
"""


def get_case_claims(case_id: str, exclude_statement_id: int | None = None) -> list[dict]:
    """Every claim in the case with who said it and in which turn, oldest first."""
    with connect() as conn:
        rows = conn.execute(
            CLAIM_CONTEXT_SQL + " WHERE se.case_id = ? AND st.id != ? ORDER BY se.id, st.turn_index, c.id",
            (case_id, exclude_statement_id if exclude_statement_id is not None else -1),
        ).fetchall()
    return [_claim_row(r) for r in rows]


def add_finding(case_id: str, statement_id: int, claim_id: int, other_claim_id: int | None,
                evidence_id: int | None, kind: str, severity: str, explanation: str,
                new_quote: str | None, prior_quote: str | None) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO alibi_findings (case_id, statement_id, claim_id, other_claim_id, evidence_id,
                   kind, severity, explanation, new_quote, prior_quote)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (case_id, statement_id, claim_id, other_claim_id, evidence_id, kind, severity,
             explanation, new_quote, prior_quote),
        )
        return cur.lastrowid


def _claim_brief(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "text": row["text"], "status": row["status"], "turn_index": row["turn_index"],
        "session_id": row["session_id"], "speaker": row["speaker"], "speaker_role": row["speaker_role"],
        "entities": json.loads(row["entities_json"]),
    }


def get_findings(statement_id: int | None = None, session_id: int | None = None,
                 case_id: str | None = None) -> list[dict]:
    """Findings with both sides spelled out, so the UI can show "then vs now" without lookups."""
    where, params = [], []
    for column, value in (("f.statement_id", statement_id), ("st.session_id", session_id), ("f.case_id", case_id)):
        if value is not None:
            where.append(f"{column} = ?")
            params.append(value)
    with connect() as conn:
        rows = conn.execute(
            "SELECT f.*, st.turn_index, st.session_id FROM alibi_findings f "
            "JOIN statements st ON f.statement_id = st.id "
            + ("WHERE " + " AND ".join(where) if where else "") + " ORDER BY f.id",
            params,
        ).fetchall()
        findings = []
        for row in rows:
            finding = dict(row)
            claim = conn.execute(CLAIM_CONTEXT_SQL + " WHERE c.id = ?", (row["claim_id"],)).fetchone()
            finding["claim"] = _claim_brief(claim)
            if row["other_claim_id"] is not None:
                other = conn.execute(CLAIM_CONTEXT_SQL + " WHERE c.id = ?", (row["other_claim_id"],)).fetchone()
                finding["source"] = {"type": "claim", **_claim_brief(other)}
            else:
                ev = conn.execute("SELECT * FROM evidence WHERE id = ?", (row["evidence_id"],)).fetchone()
                finding["source"] = {
                    "type": "evidence", "id": ev["id"], "evidence_type": ev["evidence_type"],
                    "text": ev["description"], "metadata": json.loads(ev["metadata_json"]),
                    "image": ev["image"], "image_kind": ev["image_kind"], "record_source": ev["source"],
                    "speaker": "Case file", "speaker_role": "Evidence",
                }
            findings.append(finding)
    return findings


def flag_for_finding(claim_id: int, note: str) -> None:
    """A finding makes a CONSISTENT or PENDING claim FLAGGED; a CONFLICT stays a CONFLICT."""
    with connect() as conn:
        conn.execute(
            """UPDATE claims SET status = 'FLAGGED', reason = TRIM(COALESCE(reason, '') || ' ' || ?)
               WHERE id = ? AND status IN ('CONSISTENT', 'PENDING')""",
            (note, claim_id),
        )


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
