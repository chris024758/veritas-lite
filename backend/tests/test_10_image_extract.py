"""Image extraction request and API behavior without contacting Groq."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("VERITAS_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from tools.image_extract import ExtractionError, extract_image

PNG = b"\x89PNG\r\n\x1a\nimage"
RESULT = {"transcribed_text": "MH12 AB", "observations": ["White scooter"], "uncertainties": ["Plate is partly obscured"]}


class ImageExtractionTests(unittest.TestCase):
    @patch("tools.image_extract.requests.post")
    @patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "GROQ_VISION_MODEL": "test-model"})
    def test_image_is_sent_to_groq_and_result_validated(self, post):
        post.return_value.json.return_value = {"choices": [{"message": {"content": json.dumps(RESULT)}}]}
        result = extract_image(PNG, "image/png")
        self.assertEqual(result, {"model": "test-model", **RESULT})
        request = post.call_args.kwargs["json"]
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertTrue(request["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_invalid_image_and_missing_key(self):
        with self.assertRaises(ExtractionError) as invalid:
            extract_image(b"not an image", "image/png")
        self.assertEqual(invalid.exception.status_code, 415)
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            with self.assertRaises(ExtractionError) as missing:
                extract_image(PNG, "image/png")
        self.assertEqual(missing.exception.status_code, 503)

    @patch("tools.image_extract.requests.post")
    @patch.dict(os.environ, {"GROQ_API_KEY": "test-key"})
    def test_invalid_model_result_is_rejected(self, post):
        post.return_value.json.return_value = {"choices": [{"message": {"content": '{"observations": "bad"}'}}]}
        with self.assertRaises(ExtractionError):
            extract_image(PNG, "image/png")

    def test_api_accepts_upload_and_rejects_invalid_type(self):
        from fastapi.testclient import TestClient
        from auth_test_helpers import seed_demo, sign_in
        from main import app
        client = TestClient(app)
        seed_demo()
        sign_in(client)
        with patch("main.extract_image", return_value={"model": "test", **RESULT}):
            response = client.post("/tools/extract-image", files={"image": ("test.png", PNG, "image/png")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcribed_text"], "MH12 AB")
        response = client.post("/tools/extract-image", files={"image": ("bad.svg", b"<svg/>", "image/svg+xml")})
        self.assertEqual(response.status_code, 415)

    def test_event_upload_checks_web_and_requires_cited_evidence_for_a_flag(self):
        from fastapi.testclient import TestClient
        from auth_test_helpers import seed_demo, sign_in
        from main import app

        event = {"title": "Demo concert", "date": "12 July 2026", "venue": "Demo Hall"}
        source = {"title": "Demo Hall", "uri": "https://example.org/concert"}
        client = TestClient(app)
        seed_demo()
        sign_in(client)
        cases = [
            ("CONFIRMED\nThe venue reported that the concert took place.", [source], True),
            ("CONTRADICTED\nThe venue cancelled the concert.", [source], False),
            ("CONTRADICTED\nNo listing found.", [], None),
        ]
        for answer, sources, expected in cases:
            with self.subTest(answer=answer):
                with (
                    patch("main.extract_image", return_value={**RESULT, "event": event}),
                    patch("tools.event_check.gemini_client.has_key", return_value=True),
                    patch("tools.event_check.web_search", return_value={"answer": answer, "sources": sources}) as search,
                ):
                    response = client.post("/tools/extract-image", files={"image": ("test.png", PNG, "image/png")})
                self.assertEqual(response.status_code, 200)
                self.assertIs(response.json()["event_verification"]["verified"], expected)
                self.assertIn(event["date"], search.call_args.args[0])

    def test_attachment_is_filed_and_verified_without_using_it_in_statement_checks(self):
        from fastapi.testclient import TestClient
        from auth_test_helpers import seed_demo, sign_in
        import db
        import main
        import seed
        from tools.case_file import search_case_file

        event = {"title": "Demo concert", "date": "22 November 2026"}
        verdict = {"verified": False, "reason": "The listing shows 21 November.", "sources": []}
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path = Path(directory)
            with patch.object(db, "DB_PATH", str(path / "test.db")), patch.object(main, "UPLOAD_DIR", path):
                seed_demo()
                client = TestClient(main.app)
                sign_in(client)
                started = client.post("/sessions/start", json={"case_id": seed.CASE_ID, "subject_name": "Ramesh Kulkarni"})
                started.raise_for_status()
                session = started.json()["session_id"]
                endpoint = f"/sessions/{session}/attachments"
                with patch("main.gemini_client.generate") as gemini:
                    uploaded = client.post(endpoint, files={"image": ("ticket.png", PNG, "image/png")},
                                           data={"caption": "Demo concert ticket"})
                    uploaded.raise_for_status()
                    gemini.assert_not_called()
                attachment = uploaded.json()
                evidence = attachment["evidence"]
                self.assertEqual(attachment["evidence_id"], evidence["id"])
                self.assertIn(evidence["id"], {e["id"] for e in client.get(f"/cases/{seed.CASE_ID}").json()["evidence"]})
                self.assertFalse(search_case_file("Demo concert ticket", seed.CASE_ID)["evidence"])
                with patch("main.alibi_check.check", return_value=[]) as check:
                    main._alibi_check([], "A statement", -1, db.get_session_row(session), "Ramesh")
                    records = check.call_args.args[-1]
                    self.assertTrue(records)
                    self.assertNotIn(evidence["id"], {record["id"] for record in records})
                with (
                    patch("main.extract_image", return_value={**RESULT, "event": event}) as extract,
                    patch("main.verify_event", return_value=verdict) as verify,
                ):
                    url = f"{endpoint}/{attachment['id']}/extract"
                    response = client.post(url)
                    response.raise_for_status()
                    self.assertEqual(response.json()["event_verification"], verdict)
                    self.assertEqual(client.post(url).json(), response.json())
                    extract.assert_called_once_with(PNG, "image/png")
                    verify.assert_called_once_with(event)
                saved = db.get_attachments(session)
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0]["extraction"], response.json())
                self.assertEqual(saved[0]["evidence_id"], evidence["id"])


if __name__ == "__main__":
    unittest.main()
