"""TDD test suite — Cloudflare Workers AI image-generation tool.

Vertical slices (TDD skill: one test → one impl → repeat):
  1. Happy path: Cloudflare credentials set → image_url returned, placeholder=False
  2. No-token path: placeholder=True, image_url present, no crash
  3. Non-blocking: Cloudflare error → {success: False}, no exception raised
  4. Proposed prompt → preview → approval before attaching the illustration

Run from backend/ directory:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -p test_07_cloudflare_image_gen.py -v
"""
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# bootstrap: add backend/ to sys.path so "tools.image_gen" is importable
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

# Use a throwaway DB so this test never touches the real one
os.environ.setdefault("VERITAS_DB", os.path.join(tempfile.mkdtemp(), "test_image_gen.db"))

# ---------------------------------------------------------------------------
# Test bytes with a JPEG signature. The backend serves the bytes as received.
# ---------------------------------------------------------------------------
_TEST_JPEG = b"\xff\xd8\xfftest\xff\xd9"
_CREDENTIALS = {
    "CLOUDFLARE_ACCOUNT_ID": "fake-account",
    "CLOUDFLARE_API_TOKEN": "fake-token",
}


# ---------------------------------------------------------------------------
# Slice 1 — happy path: token + successful HF call
# ---------------------------------------------------------------------------
class TestSlice1HappyPath(unittest.TestCase):
    def test_returns_image_url_and_not_placeholder(self):
        """With credentials set and Cloudflare returning bytes, result has image_url."""
        import tools.image_gen as img

        with patch.dict(os.environ, _CREDENTIALS):
            with patch("tools.image_gen._cloudflare_generate", return_value=_TEST_JPEG):
                result = img.generate_image("a white scooter at night")

        self.assertIn("image_url", result, f"Expected image_url: {result}")
        self.assertFalse(result.get("placeholder", False), "Should not be a placeholder")
        # 'success' key is only present on failure path — absent on success
        self.assertNotIn("success", result)


# ---------------------------------------------------------------------------
# Slice 2 — no token: graceful SVG placeholder
# ---------------------------------------------------------------------------
class TestSlice2NoToken(unittest.TestCase):
    def test_no_token_returns_placeholder(self):
        """Without Cloudflare credentials the tool degrades to an SVG placeholder (no crash)."""
        import tools.image_gen as img

        clean_env = {k: v for k, v in os.environ.items() if k not in _CREDENTIALS}
        with patch.dict(os.environ, clean_env, clear=True):
            result = img.generate_image("a shop at night")

        self.assertTrue(result.get("placeholder"), f"Expected placeholder=True: {result}")
        self.assertIn("image_url", result)
        self.assertNotIn("success", result)


# ---------------------------------------------------------------------------
# Slice 3 — non-blocking: Cloudflare error must not raise
# ---------------------------------------------------------------------------
class TestSlice3NonBlocking(unittest.TestCase):
    def test_provider_error_returns_failure_dict_not_exception(self):
        """A Cloudflare error must be caught; function returns {success: False}."""
        import tools.image_gen as img

        with patch.dict(os.environ, _CREDENTIALS):
            with patch("tools.image_gen._cloudflare_generate", side_effect=RuntimeError("Cloudflare 503")):
                result = img.generate_image("some scene")

        self.assertFalse(result.get("success", True), f"Expected success=False: {result}")
        self.assertNotIn("image_url", result)


# ---------------------------------------------------------------------------
# Slice 4 — generation and approval against a witness record.
# ---------------------------------------------------------------------------
class TestSlice4ApiEndpoint(unittest.TestCase):
    def test_statement_prompt_is_used_and_only_approved_image_reaches_case_file(self):
        from fastapi.testclient import TestClient
        import db
        import main
        import seed

        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder,
            patch.dict(os.environ, _CREDENTIALS),
            patch("tools.image_gen.requests.post") as post,
            patch("db.DB_PATH", str(Path(folder) / "illustrations.db")),
        ):
            seed.seed()
            client = TestClient(main.app)
            session = db.create_session(seed.CASE_ID, "Ramesh Kulkarni")
            statement = db.add_statement(session["id"], "I saw a white scooter near the shop shutter.")
            suggested = "A white scooter near a shop shutter."
            record, = main._keep_records({"records": [{
                "claim": 1, "record_type": "vehicle_sighting", "description": statement["text"],
                "image_prompt": suggested,
            }]}, [{}], session, statement["id"])
            post.assert_not_called()
            post.return_value.json.return_value = {
                "success": True,
                "result": {"image": base64.b64encode(_TEST_JPEG).decode("ascii")},
            }
            endpoint = f"/sessions/{session['id']}/evidence/{record['id']}/illustration"
            review = f"{endpoint}/review"
            self.assertEqual(client.post(review, json={"preview": "/generated/arbitrary.jpg", "approve": True}).status_code, 409)
            self.assertEqual(client.post(endpoint.replace(f"/sessions/{session['id']}/", "/sessions/999/")).status_code, 404)
            with patch("tools.image_gen.OUTPUT_DIR", Path(folder)):
                draft = client.post(endpoint).json()
                preview = draft["illustration_preview"]
                self.assertEqual((Path(folder) / Path(preview).name).read_bytes(), _TEST_JPEG)
                self.assertTrue(post.call_args.kwargs["json"]["prompt"].endswith(suggested))
                self.assertIsNone(draft["image"])
                on_file = next(r for r in db.get_case(seed.CASE_ID)["evidence"] if r["id"] == record["id"])
                self.assertIsNone(on_file["image"])
                self.assertEqual(client.post(review, json={"preview": preview, "approve": False}).status_code, 200)
                self.assertEqual(client.post(review, json={"preview": preview, "approve": True}).status_code, 409)
                preview = client.post(endpoint).json()["illustration_preview"]
                approved = client.post(review, json={"preview": preview, "approve": True}).json()
            self.assertEqual(approved["image"], preview)
            self.assertEqual(approved["image_kind"], "generated")
            self.assertIsNone(approved["illustration_preview"])
            self.assertEqual(client.post(endpoint).json()["image"], preview)
            self.assertEqual(post.call_count, 2)
            on_file = next(r for r in db.get_case(seed.CASE_ID)["evidence"] if r["id"] == record["id"])
            self.assertEqual(on_file["image"], preview)


if __name__ == "__main__":
    unittest.main(verbosity=2)
