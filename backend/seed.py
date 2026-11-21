"""Seeds the demo case. Run once before starting uvicorn; safe to re-run."""
import json

import db

CASE_ID = "2026-PUN-0219"

CASE = {
    "id": CASE_ID,
    "name": "Shree Lakshmi Jewellers theft",
    "location": "Shree Lakshmi Jewellers, FC Road, Pune",
    "summary": (
        "Night-time theft. Display cabinet opened with no sign of forced entry, consistent "
        "with a key or pick tool. Rear shutter found unlocked, but the lock itself is "
        "undamaged. Owner Suresh Deshmukh reports ₹3.2 lakh in gold jewellery missing and "
        "filed an insurance claim the same day. Registered vehicle on file: white Honda "
        "Activa, plate MH12 AB 4521."
    ),
}

SUBJECTS = [
    {
        "full_name": "Suresh Deshmukh",
        "nicknames": "",
        "role": "Suspect",
        "notes": (
            "Shop owner, person of interest. Has keys to every entry point. "
            "Registered vehicle: white Honda Activa, plate MH12 AB 4521."
        ),
    },
    {
        "full_name": "Ramesh Kulkarni",
        "nicknames": "",
        "role": "Witness",
        "notes": "Neighbouring paanwala.",
    },
]

EVIDENCE = [
    {
        "evidence_type": "rear_shutter_lock",
        "description": "Rear shutter found unlocked; the lock itself is intact with no damage.",
        "metadata": {"item": "rear shutter lock", "condition": "intact, no damage",
                     "location": "Shree Lakshmi Jewellers, FC Road, Pune"},
    },
    {
        "evidence_type": "display_cabinet",
        "description": "Display cabinet opened cleanly with no glass damage; no sign of forced entry.",
        "metadata": {"item": "display cabinet", "condition": "opened cleanly, no glass damage",
                     "location": "Shree Lakshmi Jewellers, FC Road, Pune"},
    },
    {
        "evidence_type": "witness_statement",
        "description": (
            "Ramesh Kulkarni, neighbouring paanwala, reports seeing a man in a blue helmet "
            "loading a bag onto a white scooter near the rear shutter around 10:15 PM. The "
            "scooter's plate partially matches Suresh Deshmukh's registered white Honda "
            "Activa, MH12 AB 4521."
        ),
        "metadata": {
            "witness": "Ramesh Kulkarni",
            "time": "22:15",
            "location": "near rear shutter, Shree Lakshmi Jewellers, FC Road, Pune",
            "person_descriptor": "man in a blue helmet",
            "vehicle_descriptor": "white scooter",
            "plate_match": "partial match to MH12 AB 4521",
        },
    },
    {
        "evidence_type": "insurance_claim",
        "description": "Suresh Deshmukh filed an insurance claim for ₹3.2 lakh in gold jewellery the same day as the theft.",
        "metadata": {"claimant": "Suresh Deshmukh", "amount": "₹3.2 lakh",
                     "items": "gold jewellery", "filed": "same day as the theft"},
    },
    {
        "evidence_type": "stolen_items",
        "description": (
            "Gold jewellery reported stolen from the display cabinet: a temple necklace, a pair of "
            "bangles, jhumka earrings and a signet ring, 83 g of 22K gold in all, valued at ₹3.2 lakh."
        ),
        "metadata": {"reported_by": "Suresh Deshmukh", "count": "4 items", "total_weight": "83 g (22K)",
                     "total_value": "₹3.2 lakh", "taken_from": "display cabinet"},
    },
]

# Illustrations shown on the evidence cards. Served from /static; never sent to Gemini.
EVIDENCE_IMAGES = {
    "rear_shutter_lock": "/static/evidence/rear_shutter_lock.svg",
    "display_cabinet": "/static/evidence/display_cabinet.svg",
    "witness_statement": "/static/evidence/witness_statement.svg",
    "insurance_claim": "/static/evidence/insurance_claim.svg",
    "stolen_items": "/static/evidence/stolen_items.svg",
    "door_damage": "/static/evidence/door_damage.svg",
}

STOLEN_ITEMS = [
    {"name": "Temple necklace", "description": "22K gold, Lakshmi pendant with a red stone, 9 beads each side.",
     "weight": "38 g", "value": "₹1.45 lakh", "image": "/static/evidence/necklace.svg"},
    {"name": "Pair of bangles", "description": "22K gold, engraved rim pattern, 2.4 size.",
     "weight": "24 g", "value": "₹0.92 lakh", "image": "/static/evidence/bangles.svg"},
    {"name": "Jhumka earrings", "description": "22K gold bell earrings with bead fringe.",
     "weight": "9 g", "value": "₹0.35 lakh", "image": "/static/evidence/earrings.svg"},
    {"name": "Signet ring", "description": "22K gold men's ring engraved 'SD'.",
     "weight": "12 g", "value": "₹0.48 lakh", "image": "/static/evidence/ring.svg"},
]


# The window the theft happened in, for the timeline's incident marker and alibi gaps.
INCIDENT = {"incident_start": "21:30", "incident_end": "22:30"}

# An earlier interview with the witness, so the subject's alibi has a prior statement to be
# checked against from the first live turn. Verdicts are stored as-is, not re-verified.
WITNESS_SESSION = {
    "subject": "Ramesh Kulkarni",
    "started_at": "2026-11-06T10:00:00+05:30",
    "text": (
        "I shut my paan stall at about ten. Around 10:15 I saw a man in a blue helmet loading a "
        "bag onto a white Activa right by the jewellers' rear shutter. The plate started MH12 AB. "
        "Then he rode off towards Kothrud."
    ),
    "claims": [
        {"claim_type": "TIMELINE", "status": "CONSISTENT",
         "text": "Shut the paan stall at about 10 PM.",
         "entities": {"time": "22:00", "time_start": "22:00", "time_approx": True, "location": "paan stall, FC Road, Pune"},
         "reason": "Matches the witness record on the case file."},
        {"claim_type": "TIMELINE", "status": "CONSISTENT",
         "text": "Saw a man in a blue helmet loading a bag onto a white Activa by the jewellers' rear shutter around 10:15 PM.",
         "entities": {"time": "22:15", "time_start": "22:15", "time_approx": True,
                      "location": "rear shutter, Shree Lakshmi Jewellers, FC Road, Pune",
                      "person": "man in a blue helmet", "vehicle": "white Activa"},
         "reason": "Matches the witness_statement record on the case file."},
        {"claim_type": "VEHICLE", "status": "CONSISTENT",
         "text": "The scooter's plate started MH12 AB.",
         "entities": {"vehicle": "white Activa", "plate": "MH12 AB", "time_start": "22:15", "time_approx": True},
         "reason": "Partly matches the registered plate MH12 AB 4521 of Suresh Deshmukh's Activa."},
        {"claim_type": "ROUTE", "status": "PENDING",
         "text": "The rider left the shop heading towards Kothrud.",
         "entities": {"origin": "Shree Lakshmi Jewellers, FC Road, Pune", "destination": "Kothrud",
                      "time_start": "22:17", "time_approx": True},
         "reason": "Direction of travel only; no record establishes it either way."},
    ],
}


def seed_witness_session(conn) -> None:
    exists = conn.execute(
        "SELECT 1 FROM statements st JOIN sessions se ON st.session_id = se.id "
        "WHERE se.case_id = ? AND st.text = ?", (CASE_ID, WITNESS_SESSION["text"]),
    ).fetchone()
    if exists:
        return
    subject_id = conn.execute(
        "SELECT id FROM subjects WHERE case_id = ? AND full_name = ?", (CASE_ID, WITNESS_SESSION["subject"]),
    ).fetchone()[0]
    session_id = conn.execute(
        "INSERT INTO sessions (case_id, subject_id, started_at, ended_at) VALUES (?, ?, ?, ?)",
        (CASE_ID, subject_id, WITNESS_SESSION["started_at"], WITNESS_SESSION["started_at"]),
    ).lastrowid
    statement_id = conn.execute(
        "INSERT INTO statements (session_id, turn_index, text) VALUES (?, 0, ?)",
        (session_id, WITNESS_SESSION["text"]),
    ).lastrowid
    for claim in WITNESS_SESSION["claims"]:
        conn.execute(
            "INSERT INTO claims (statement_id, claim_type, text, entities_json, status, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (statement_id, claim["claim_type"], claim["text"], json.dumps(claim["entities"]),
             claim["status"], claim["reason"]),
        )


KNOWN_ROUTES = [
    ("FC Road, Pune", "Kothrud, Pune"),
    ("Hadapsar, Pune", "FC Road, Pune"),
]


# Short placeholder cases so the directory is not a list of one. No interviews.
OTHER_CASES = [
    {
        "case": {"id": "2026-PUN-0231", "name": "Baner warehouse break-in", "location": "Baner, Pune",
                 "summary": "Copper wiring taken from a construction-supply warehouse over a weekend. Side door forced.",
                 "incident_start": "01:00", "incident_end": "04:00", "status": "Open"},
        "subjects": [{"full_name": "Vikram Shinde", "nicknames": "", "role": "Witness", "notes": "Night watchman."}],
        "evidence": [{"evidence_type": "door_damage", "description": "Side door forced with a crowbar; frame bent.",
                      "metadata": {"item": "side door", "condition": "forced"}}],
    },
    {
        "case": {"id": "2026-PUN-0244", "name": "Koregaon Park hit-and-run", "location": "North Main Road, Koregaon Park, Pune",
                 "summary": "Pedestrian injured at a crossing; a dark hatchback did not stop.",
                 "incident_start": "19:30", "incident_end": "20:00", "status": "Open"},
        "subjects": [], "evidence": [],
    },
]

# On file for the suspect, so the checks can match the scooter in the witness record.
SURESH_VEHICLE = {"vehicle": "white Honda Activa", "plate": "MH12 AB 4521", "relation": "Shop owner"}


def _upsert_case(conn, case: dict) -> None:
    conn.execute(
        "INSERT INTO cases (id, name, location, summary, incident_start, incident_end, status) "
        "VALUES (:id, :name, :location, :summary, :incident_start, :incident_end, :status) "
        "ON CONFLICT(id) DO UPDATE SET name = excluded.name, location = excluded.location, "
        "summary = excluded.summary, incident_start = excluded.incident_start, "
        "incident_end = excluded.incident_end",
        {"status": "Open", **case},
    )


def _add_people_and_evidence(conn, case_id: str, subjects: list, evidence: list) -> None:
    for subject in subjects:
        conn.execute(
            "INSERT OR IGNORE INTO subjects (case_id, full_name, nicknames, role, notes) "
            "VALUES (:case_id, :full_name, :nicknames, :role, :notes)",
            {**subject, "case_id": case_id},
        )
    for item in evidence:
        conn.execute(
            "INSERT OR IGNORE INTO evidence (case_id, evidence_type, description, metadata_json) "
            "VALUES (?, ?, ?, ?)",
            (case_id, item["evidence_type"], item["description"], json.dumps(item["metadata"])),
        )
        conn.execute(
            "UPDATE evidence SET image = ? WHERE case_id = ? AND evidence_type = ?",
            (EVIDENCE_IMAGES.get(item["evidence_type"]), case_id, item["evidence_type"]),
        )
        if item["evidence_type"] == "stolen_items":
            evidence_id = conn.execute(
                "SELECT id FROM evidence WHERE case_id = ? AND evidence_type = 'stolen_items'", (case_id,)
            ).fetchone()[0]
            for stolen in STOLEN_ITEMS:
                conn.execute(
                    "INSERT OR IGNORE INTO evidence_items (evidence_id, name, description, weight, value, image) "
                    "VALUES (:evidence_id, :name, :description, :weight, :value, :image)",
                    {**stolen, "evidence_id": evidence_id},
                )


def seed(with_witness_interview: bool = False) -> None:
    """The demo starts with no interviews; the earlier witness interview is optional."""
    db.init_db()
    with db.connect() as conn:
        # Upsert, not REPLACE: replacing the row would break the sessions that reference it.
        _upsert_case(conn, {**CASE, **INCIDENT})
        _add_people_and_evidence(conn, CASE_ID, SUBJECTS, EVIDENCE)
        conn.execute(
            "UPDATE subjects SET vehicle = :vehicle, plate = :plate, relation = :relation "
            "WHERE case_id = :case_id AND full_name = 'Suresh Deshmukh'",
            {**SURESH_VEHICLE, "case_id": CASE_ID},
        )
        for other in OTHER_CASES:
            _upsert_case(conn, other["case"])
            _add_people_and_evidence(conn, other["case"]["id"], other["subjects"], other["evidence"])
        if with_witness_interview:
            seed_witness_session(conn)


def precompute_routes() -> None:
    """Best effort, per the PRD's risk table: caches real OSRM results for the case's known
    places so the demo survives the public servers being down later."""
    from tools.routing import check_route

    for origin, destination in KNOWN_ROUTES:
        result = check_route(origin, destination)
        print(f"Route cache {origin} -> {destination}: {result}")


if __name__ == "__main__":
    import sys

    seed(with_witness_interview="--with-witness-interview" in sys.argv)
    print(f"Seeded case {CASE_ID} and {len(OTHER_CASES)} placeholder cases into {db.DB_PATH}")
    precompute_routes()
