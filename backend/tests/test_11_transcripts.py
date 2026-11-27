"""Transcript persistence and interview isolation without live model calls."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True)))
        path = directory / "test.db"
        with patch.dict(os.environ, {"VERITAS_DB": str(path), "VERITAS_UPLOADS": str(directory / "uploads")}):
            import main
        self.db = main.db
        self.enterContext(patch.object(self.db, "DB_PATH", path))
        self.db.init_db()
        with self.db.connect() as conn:
            conn.executemany("INSERT INTO cases (id, name) VALUES (?, ?)", [("TEST", "Test"), ("OTHER", "Other")])
            subject_id = conn.execute(
                "INSERT INTO subjects (case_id, full_name, role) VALUES ('TEST', 'Witness', 'Witness')"
            ).lastrowid
        conn.close()
        self.first = self.db.create_session_for_subject("TEST", subject_id)["id"]
        self.second = self.db.create_session_for_subject("TEST", subject_id)["id"]
        self.legacy = self.db.create_session_for_subject("TEST", subject_id)["id"]
        self.db.add_statement(self.legacy, "Previously reviewed")
        self.client = self.enterContext(TestClient(main.app))
        self.extract = self.enterContext(patch("main.extraction.extract_claims", return_value=[]))
        self.enterContext(patch("main.verification.verify_statement_full", return_value={"results": [], "records": []}))
        self.enterContext(patch("main.followups.suggest", return_value=[]))

    def record(self, session_id, text, endpoint="transcribe"):
        with patch("main.stt.transcribe", return_value=text):
            response = self.client.post(
                f"/sessions/{session_id}/{endpoint}", files={"audio": ("clip.webm", b"clip")}
            )
        response.raise_for_status()
        return response.json()

    def submit(self, session_id, **body):
        return self.client.post(f"/sessions/{session_id}/statements", json=body)

    def transcript(self, session_id):
        response = self.client.get(f"/cases/TEST/transcripts/{session_id}")
        response.raise_for_status()
        return response.json()["entries"]

    def test_review_and_discard_preserve_originals_in_one_interview(self):
        self.record(self.first, " Unsent words. ")
        reviewed = self.record(self.first, "Original Whisper words.")
        self.record(self.first, "")
        self.extract.assert_not_called()
        rejected = self.submit(self.second, text="Wrong session", transcript_segment_id=reviewed["transcript_segment_id"])
        self.assertEqual(rejected.status_code, 422)
        response = self.submit(self.first, text="Reviewed words.", transcript_segment_id=reviewed["transcript_segment_id"])
        response.raise_for_status()
        self.assertEqual(response.json()["transcript_segment_id"], reviewed["transcript_segment_id"])
        self.extract.assert_called_once_with("Reviewed words.")
        self.submit(self.first, text="Typed after the recording.").raise_for_status()
        entries = self.transcript(self.first)
        self.assertEqual([(e["sequence_no"], e["source"], e["raw_text"]) for e in entries], [
            (1, "recorded", " Unsent words. "),
            (2, "recorded", "Original Whisper words."),
            (3, "typed", "Typed after the recording."),
        ])
        self.record(self.first, "Direct audio submission.", endpoint="audio")
        self.assertEqual(self.transcript(self.first)[-1]["source"], "recorded")
        self.assertEqual(self.client.get(f"/cases/OTHER/transcripts/{self.first}").status_code, 404)

    def test_typed_only_and_retry_with_same_request(self):
        self.record(self.first, "A different interview.")
        submission = {"text": " Typed-only text. ", "request_id": str(uuid4())}
        self.extract.side_effect = ValueError("simulated extraction failure")
        self.assertEqual(self.submit(self.second, **submission).status_code, 502)
        saved = self.transcript(self.second)
        self.assertEqual(saved[0]["raw_text"], submission["text"])
        self.extract.side_effect = None
        result = self.submit(self.second, **submission)
        result.raise_for_status()
        self.assertEqual(result.json()["transcript_segment_id"], saved[0]["id"])
        self.assertEqual(self.transcript(self.second), saved)
        listing = self.client.get("/cases/TEST/transcripts").json()
        self.assertEqual([(row["session_id"], row["subject_name"], row["entry_count"]) for row in listing], [
            (self.second, "Witness", 1), (self.first, "Witness", 1),
        ])
        self.assertEqual(self.client.get(f"/cases/TEST/transcripts/{self.legacy}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
