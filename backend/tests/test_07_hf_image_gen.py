"""TDD test suite — HuggingFace image-generation tool.

Vertical slices (TDD skill: one test → one impl → repeat):
  1. Happy path: HF_TOKEN set → image_url returned, placeholder=False
  2. No-token path: placeholder=True, image_url present, no crash
  3. Non-blocking: HF error → {success: False}, no exception raised
  4. API endpoint contract: POST /tools/generate-image → 200 + image_url

Run from backend/ directory:
    .venv\\Scripts\\python.exe -m unittest tests.test_07_hf_image_gen -v
"""
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
os.environ.setdefault("VERITAS_DB", os.path.join(tempfile.mkdtemp(), "test_hf.db"))

# ---------------------------------------------------------------------------
# Shared fixture: a 1×1 valid PNG (parseable by Pillow / browsers)
# ---------------------------------------------------------------------------
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


# ---------------------------------------------------------------------------
# Slice 1 — happy path: token + successful HF call
# ---------------------------------------------------------------------------
class TestSlice1HappyPath(unittest.TestCase):
    def test_returns_image_url_and_not_placeholder(self):
        """With HF_TOKEN set and HF returning bytes, result has image_url."""
        import tools.image_gen as img

        with patch.dict(os.environ, {"HF_TOKEN": "hf_fake_token"}):
            with patch("tools.image_gen._hf_generate", return_value=_TINY_PNG):
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
        """Without HF_TOKEN the tool degrades to an SVG placeholder (no crash)."""
        import tools.image_gen as img

        clean_env = {k: v for k, v in os.environ.items() if k != "HF_TOKEN"}
        with patch.dict(os.environ, clean_env, clear=True):
            result = img.generate_image("a shop at night")

        self.assertTrue(result.get("placeholder"), f"Expected placeholder=True: {result}")
        self.assertIn("image_url", result)
        self.assertNotIn("success", result)


# ---------------------------------------------------------------------------
# Slice 3 — non-blocking: HF error must not raise
# ---------------------------------------------------------------------------
class TestSlice3NonBlocking(unittest.TestCase):
    def test_hf_error_returns_failure_dict_not_exception(self):
        """A HF API error must be caught; function returns {success: False}."""
        import tools.image_gen as img

        with patch.dict(os.environ, {"HF_TOKEN": "hf_fake_token"}):
            with patch("tools.image_gen._hf_generate", side_effect=RuntimeError("HF 503")):
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

        with patch.dict(os.environ, {"HF_TOKEN": "hf_fake_token"}):
            with patch("tools.image_gen._hf_generate", return_value=_TINY_PNG):
                resp = client.post(
                    "/tools/generate-image",
                    json={"description": "a white scooter near a shop shutter"},
                )

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIn("image_url", body, f"Response: {body}")
        self.assertFalse(body.get("placeholder", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
