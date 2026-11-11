"""Idempotent seed for the PRD's single Pune demo case."""
import json

import db

CASE_ID = "2026-PUN-0219"
SURESH_ID = "subject-suresh-deshmukh"
RAMESH_ID = "subject-ramesh-kulkarni"

CASE = {"id": CASE_ID, "name": "Shree Lakshmi Jewellers Theft", "location": "Shree Lakshmi Jewellers, FC Road, Pune", "summary": "Alarm at 22:40 IST. No forced entry; rear shutter unlocked and display cabinet opened cleanly. Owner reported ₹3.2 lakh in gold jewellery missing."}
SUBJECTS = [
    (SURESH_ID, "Suresh Deshmukh", "SUSPECT", "Shop owner. Has keys to every entry point. Person of interest — no forced entry is suspicious for a break-in.", {"plate": "MH12AB4521", "color": "white", "type": "Honda Activa"}),
    (RAMESH_ID, "Ramesh Kulkarni", "WITNESS", "Runs the paan/cigarette stall next door. Eyewitness.", None),
]
EVIDENCE = [
    ("evidence-rear-shutter", "SCENE", "Rear service shutter — lock intact, no scratching, no forced damage", {"location": "rear shutter"}),
    ("evidence-display-cabinet", "SCENE", "Display cabinet — opened cleanly, no glass damage", {"location": "display cabinet"}),
    ("evidence-witness-sighting", "WITNESS_SIGHTING", "Man near rear shutter loading a bag onto a white scooter, ~22:15", {"time": "22:15", "vehicle_color": "white", "vehicle_type": "scooter", "plate_partial": "MH12", "source": "Ramesh Kulkarni"}),
    ("evidence-vehicle-record", "VEHICLE_RECORD", "Owner's registered vehicle", {"plate": "MH12AB4521", "color": "white", "type": "Honda Activa", "owner": "Suresh Deshmukh"}),
]
OFFICER_STATEMENT = "Responding to alarm trigger at 22:40 IST. Shree Lakshmi Jewellers, FC Road. Front shutter locked, no forced entry. Display cabinet open, no glass damage — opened with a key or pick tool. Rear service shutter found unlocked; lock itself undamaged, no scratching. Owner Suresh Deshmukh reports ₹3.2 lakh in gold jewellery missing, insurance claim filed same night. Owner's registered vehicle on file: white Honda Activa, plate MH12AB4521."
WITNESS_STATEMENT = "I was closing up around 10:15 PM. Saw a man near the shop's back shutter, loading something into a bag on a white scooter. Couldn't see his face clearly, but the scooter looked like the one the shop owner rides — I think the plate started with MH12."


def seed() -> None:
    db.init_db()
    with db.connect() as conn:
        conn.execute("INSERT INTO cases(id, name, location, summary) VALUES (:id, :name, :location, :summary) ON CONFLICT(id) DO UPDATE SET name=excluded.name, location=excluded.location, summary=excluded.summary", CASE)
        for subject_id, name, role, notes, vehicle in SUBJECTS:
            conn.execute("INSERT INTO subjects(id, case_id, full_name, role, notes, registered_vehicle_json) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name, role=excluded.role, notes=excluded.notes, registered_vehicle_json=excluded.registered_vehicle_json", (subject_id, CASE_ID, name, role, notes, json.dumps(vehicle) if vehicle else None))
        for evidence_id, evidence_type, description, metadata in EVIDENCE:
            conn.execute("INSERT INTO evidence(id, case_id, evidence_type, description, metadata_json) VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET evidence_type=excluded.evidence_type, description=excluded.description, metadata_json=excluded.metadata_json", (evidence_id, CASE_ID, evidence_type, description, json.dumps(metadata)))
        for session_id, subject_id, role, text in (("seed-officer-session", None, "OFFICER", OFFICER_STATEMENT), ("seed-ramesh-session", RAMESH_ID, "WITNESS", WITNESS_STATEMENT)):
            conn.execute("INSERT OR IGNORE INTO sessions(id, case_id, subject_id) VALUES (?, ?, ?)", (session_id, CASE_ID, subject_id))
            conn.execute("INSERT OR IGNORE INTO statements(session_id, case_id, subject_id, role, turn_index, text, source) VALUES (?, ?, ?, ?, 0, ?, 'seed')", (session_id, CASE_ID, subject_id, role, text))


if __name__ == "__main__":
    seed()
    print(f"Seeded case {CASE_ID} into {db.DB_PATH}")
