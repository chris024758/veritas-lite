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
]


KNOWN_ROUTES = [
    ("FC Road, Pune", "Kothrud, Pune"),
    ("Hadapsar, Pune", "FC Road, Pune"),
]


def seed() -> None:
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cases (id, name, location, summary) "
            "VALUES (:id, :name, :location, :summary)",
            CASE,
        )
        for subject in SUBJECTS:
            conn.execute(
                "INSERT OR IGNORE INTO subjects (case_id, full_name, nicknames, role, notes) "
                "VALUES (:case_id, :full_name, :nicknames, :role, :notes)",
                {**subject, "case_id": CASE_ID},
            )
        for item in EVIDENCE:
            conn.execute(
                "INSERT OR IGNORE INTO evidence (case_id, evidence_type, description, metadata_json) "
                "VALUES (?, ?, ?, ?)",
                (CASE_ID, item["evidence_type"], item["description"], json.dumps(item["metadata"])),
            )


def precompute_routes() -> None:
    """Best effort, per the PRD's risk table: caches real OSRM results for the case's known
    places so the demo survives the public servers being down later."""
    from tools.routing import check_route

    for origin, destination in KNOWN_ROUTES:
        result = check_route(origin, destination)
        print(f"Route cache {origin} -> {destination}: {result}")


if __name__ == "__main__":
    seed()
    print(f"Seeded case {CASE_ID} into {db.DB_PATH}")
    precompute_routes()
