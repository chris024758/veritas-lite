"""Run backend unit tests with Python's standard library and real SQLite."""
import gc
import sys
import tempfile
import unittest
from pathlib import Path

# Resolve imports from the script location so the runner works from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import timeline
from tools.case_file import search_case_file


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        # SQLite uses a file because production opens a new connection per operation.
        directory = self.enterContext(tempfile.TemporaryDirectory())
        # SQLite's transaction context managers leave connections open until collected.
        # Collect them before Windows tries to remove the test database file.
        self.addCleanup(gc.collect)
        self.addCleanup(setattr, db, "DB_PATH", db.DB_PATH)
        db.DB_PATH = Path(directory) / "unit.db"
        db.init_db()
        connection = db.connect()
        try:
            with connection:
                connection.execute("INSERT INTO cases (id, name) VALUES (?, ?)", ("TEST", "Test case"))
        finally:
            connection.close()

    def test_statements_round_trip_in_turn_order(self):
        session = db.create_session("TEST", "Unknown")
        db.add_statement(session["id"], "First statement")
        db.add_statement(session["id"], "Second statement")

        history = db.get_session_history(session["id"])
        self.assertEqual(
            [(row["turn_index"], row["text"]) for row in history["statements"]],
            [(0, "First statement"), (1, "Second statement")],
        )

    def test_invalid_verdict_leaves_claim_pending(self):
        session = db.create_session("TEST", "Unknown")
        statement = db.add_statement(session["id"], "I saw a scooter")
        claim_id = db.add_claim(statement["id"], "VEHICLE", "I saw a scooter", {})

        with self.assertRaises(ValueError):
            db.finish_claim(claim_id, "MAYBE", "Invalid status", {})

        self.assertEqual(db.get_claims(statement["id"])[0]["status"], "PENDING")

    def test_case_search_matches_plate_with_spaces_in_evidence(self):
        db.add_evidence("TEST", "vehicle_sighting", "Plate MH 12 AB 4521", {}, source="seed")

        result = search_case_file("MH12AB4521", "TEST")

        self.assertEqual([item["description"] for item in result["evidence"]], ["Plate MH 12 AB 4521"])

    def test_case_search_excludes_current_statement_and_its_claims(self):
        session = db.create_session("TEST", "Unknown")
        prior = db.add_statement(session["id"], "A white scooter passed by")
        current = db.add_statement(session["id"], "A blue scooter passed by")
        db.add_claim(current["id"], "VEHICLE", "A blue scooter passed by", {})

        result = search_case_file("scooter", "TEST", exclude_statement_id=current["id"])

        self.assertEqual([row["id"] for row in result["prior_statements"]], [prior["id"]])
        self.assertEqual(result["prior_claims"], [])


class TimelineTests(unittest.TestCase):
    def test_time_formats_and_invalid_values(self):
        for value, expected in [("12:00 AM", 0), ("12:00 PM", 720), ("9:40 PM", 1300),
                                ("21:40", 1300), ("25:00", None), (None, None)]:
            with self.subTest(value=value):
                self.assertEqual(timeline.to_minutes(value), expected)

    def test_gaps_merge_overlapping_coverage(self):
        self.assertEqual(timeline._gaps((0, 60), [(20, 30), (10, 25), (40, 50)]),
                         [[0, 10], [30, 40], [50, 60]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
