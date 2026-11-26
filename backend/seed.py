"""Seeds the demo case. Run once before starting uvicorn; safe to re-run."""
import json

import db
from security import DEMO_USERNAME

# The shared demo credential is stored in the same salted format as other accounts.
DEMO_PASSWORD_HASH = (
    "a1562b48d4e9da808d4936952cb00e2c:0e9aa8a172e7a37f786c4303e4e46b3b968883b3a0e7e2e5baff8fe658e21b9df"
    "6fbdb28214d88f5612f8d814da7e317a10f846115e6eb9dbc27e3b38a99d88a"
)

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
        "notes": "Suresh's friend; lives in Hadapsar.",
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
INCIDENT = {"incident_start": "21:30", "incident_end": "22:30", "incident_date": "2026-11-21"}

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

# On file for the suspect: shown in the case file and passed to the checks with his name.
SURESH_VEHICLE = {"vehicle": "white Honda Activa", "plate": "MH12 AB 4521", "relation": "Shop owner"}


def _upsert_case(conn, case: dict, subjects: list, evidence: list) -> None:
    case_id = case["id"]
    existing = conn.execute("SELECT name, owner FROM cases WHERE id = ?", (case_id,)).fetchone()
    if existing and existing["owner"] != DEMO_USERNAME:
        people = conn.execute("SELECT * FROM subjects WHERE case_id = ?", (case_id,)).fetchall()
        expected_people = {person["full_name"]: person for person in subjects}
        records = conn.execute("SELECT * FROM evidence WHERE case_id = ?", (case_id,)).fetchall()
        expected_records = {item["evidence_type"]: item for item in evidence}
        interviews = conn.execute("SELECT 1 FROM sessions WHERE case_id = ? LIMIT 1", (case_id,)).fetchone()
        conflict = ValueError(f"Case {case_id} may contain private records. Seed into a separate database.")
        if existing["owner"] is not None or existing["name"] != case["name"] or interviews:
            raise conflict
        for person in people:
            expected = expected_people.get(person["full_name"])
            vehicle = SURESH_VEHICLE if person["full_name"] == "Suresh Deshmukh" and case_id == CASE_ID else {}
            if (expected is None or person["phone"] or person["nicknames"] != expected["nicknames"]
                    or person["notes"] != expected["notes"]
                    or any(person[field] not in (None, "", vehicle.get(field)) for field in ("vehicle", "plate", "relation"))):
                raise conflict
        for record in records:
            expected = expected_records.get(record["evidence_type"])
            if (expected is None or record["source"] != "seed" or record["description"] != expected["description"]
                    or json.loads(record["metadata_json"]) != expected["metadata"]
                    or record["image"] not in (None, EVIDENCE_IMAGES.get(record["evidence_type"]))):
                raise conflict

    conn.execute(
        "INSERT INTO cases (id, name, location, summary, incident_start, incident_end, incident_date, status, owner) "
        "VALUES (:id, :name, :location, :summary, :incident_start, :incident_end, :incident_date, :status, :owner) "
        "ON CONFLICT(id) DO UPDATE SET name = excluded.name, location = excluded.location, "
        "summary = excluded.summary, incident_start = excluded.incident_start, "
        "incident_end = excluded.incident_end, incident_date = excluded.incident_date, owner = excluded.owner",
        {"status": "Open", "incident_date": None, **case, "owner": DEMO_USERNAME},
    )
    _add_people_and_evidence(conn, case_id, subjects, evidence)


def _add_people_and_evidence(conn, case_id: str, subjects: list, evidence: list) -> None:
    for subject in subjects:
        conn.execute(
            "INSERT OR IGNORE INTO subjects (case_id, full_name, nicknames, role, notes) "
            "VALUES (:case_id, :full_name, :nicknames, :role, :notes)",
            {**subject, "case_id": case_id},
        )
    for item in evidence:
        found = conn.execute(
            "SELECT id FROM evidence WHERE case_id = ? AND evidence_type = ? AND source = 'seed'",
            (case_id, item["evidence_type"]),
        ).fetchone()
        if found is None:
            conn.execute(
                "INSERT INTO evidence (case_id, evidence_type, description, metadata_json, source) "
                "VALUES (?, ?, ?, ?, 'seed')",
                (case_id, item["evidence_type"], item["description"], json.dumps(item["metadata"])),
            )
        conn.execute(
            "UPDATE evidence SET image = ?, image_kind = 'illustration' "
            "WHERE case_id = ? AND evidence_type = ? AND source = 'seed'",
            (EVIDENCE_IMAGES.get(item["evidence_type"]), case_id, item["evidence_type"]),
        )
        if item["evidence_type"] == "stolen_items":
            evidence_id = conn.execute(
                "SELECT id FROM evidence WHERE case_id = ? AND evidence_type = 'stolen_items' AND source = 'seed'", (case_id,)
            ).fetchone()[0]
            for stolen in STOLEN_ITEMS:
                conn.execute(
                    "INSERT OR IGNORE INTO evidence_items (evidence_id, name, description, weight, value, image) "
                    "VALUES (:evidence_id, :name, :description, :weight, :value, :image)",
                    {**stolen, "evidence_id": evidence_id},
                )


def seed() -> None:
    """The demo starts with no interviews. The street cleaner is not seeded: he is added live."""
    db.init_db()
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO accounts VALUES (?, ?)", (DEMO_USERNAME, DEMO_PASSWORD_HASH))
        # Upsert, not REPLACE: replacing the row would break the sessions that reference it.
        _upsert_case(conn, {**CASE, **INCIDENT}, SUBJECTS, EVIDENCE)
        for subject in SUBJECTS:  # keep seeded people current on an existing database
            conn.execute(
                "UPDATE subjects SET role = :role, notes = :notes WHERE case_id = :case_id AND full_name = :full_name",
                {**subject, "case_id": CASE_ID},
            )
        conn.execute(
            "UPDATE subjects SET vehicle = :vehicle, plate = :plate, relation = :relation "
            "WHERE case_id = :case_id AND full_name = 'Suresh Deshmukh'",
            {**SURESH_VEHICLE, "case_id": CASE_ID},
        )
        # The earlier story's paan-stall sighting is no longer part of the case.
        conn.execute(
            "DELETE FROM evidence WHERE case_id = ? AND source = 'seed' AND evidence_type = 'witness_statement' "
            "AND id NOT IN (SELECT evidence_id FROM alibi_findings WHERE evidence_id IS NOT NULL)",
            (CASE_ID,),
        )
        for other in OTHER_CASES:
            _upsert_case(conn, other["case"], other["subjects"], other["evidence"])


def precompute_routes() -> None:
    """Best effort, per the PRD's risk table: caches real OSRM results for the case's known
    places so the demo survives the public servers being down later."""
    from tools.routing import check_route

    for origin, destination in KNOWN_ROUTES:
        result = check_route(origin, destination)
        print(f"Route cache {origin} -> {destination}: {result}")


if __name__ == "__main__":
    seed()
    print(f"Seeded case {CASE_ID} and {len(OTHER_CASES)} placeholder cases into {db.DB_PATH}")
    precompute_routes()
