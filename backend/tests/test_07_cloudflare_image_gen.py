"""TDD test suite — Cloudflare Workers AI image-generation tool.

Vertical slices (TDD skill: one test → one impl → repeat):
  1. Happy path: Cloudflare credentials set → image_url returned, placeholder=False
  2. No-token path: placeholder=True, image_url present, no crash
  3. Non-blocking: Cloudflare error → {success: False}, no exception raised
  4. API endpoint contract: POST /tools/generate-image → 200 + image_url

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
# Slice 4 — API endpoint: POST /tools/generate-image
# Exercise the actual application endpoint.
# ---------------------------------------------------------------------------
class TestSlice4ApiEndpoint(unittest.TestCase):
    def test_endpoint_returns_200_with_image_url(self):
        """POST /tools/generate-image must return 200 with an image_url key."""

        from fastapi.testclient import TestClient
        # The report exporter is unrelated to this endpoint.
        with patch.dict(sys.modules, {"report_docx": unittest.mock.MagicMock()}):
            from main import app

        client = TestClient(app)

        with patch.dict(os.environ, _CREDENTIALS), patch("tools.image_gen.requests.post") as post:
            post.return_value.json.return_value = {
                "success": True,
                "result": {"image": base64.b64encode(_TEST_JPEG).decode("ascii")},
            }
            prompt = "a white scooter near a shop shutter"
            resp = client.post("/tools/generate-image", json={"description": prompt})

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertFalse(body["placeholder"])
        self.assertEqual(body["model"], "@cf/black-forest-labs/flux-1-schnell")
        post.assert_called_once_with(
            "https://api.cloudflare.com/client/v4/accounts/fake-account/ai/run/"
            "@cf/black-forest-labs/flux-1-schnell",
            headers={"Authorization": "Bearer fake-token"},
            json={"prompt": prompt},
            timeout=120,
        )
        image = client.get(body["image_url"])
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/jpeg")
        self.assertEqual(image.content, _TEST_JPEG)


if __name__ == "__main__":
    unittest.main(verbosity=2)
