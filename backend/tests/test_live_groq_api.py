"""Opt-in live API tests for the configured Groq account.

This is intentionally separate from the offline unit suite: a real provider call is
an integration test and may consume a small number of tokens.
"""
import os
import unittest
from pathlib import Path

from dotenv import load_dotenv
from groq import APIConnectionError, APIStatusError, Groq, RateLimitError
import truststore


MODEL = "llama-3.3-70b-versatile"


class LiveGroqApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load the local project configuration, rather than relying on a shell to
        # expose a secret, while keeping the key out of test output.
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        cls.api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not cls.api_key or cls.api_key == "your-groq-api-key-here":
            raise unittest.SkipTest("GROQ_API_KEY is not configured in backend/.env")
        # A machine-level SSLKEYLOGFILE points to a protected antivirus proxy here.
        # It is only useful for TLS debugging and prevents httpx from opening SSL.
        os.environ.pop("SSLKEYLOGFILE", None)
        # Corporate HTTPS proxies install their CA in the Windows trust store, not
        # certifi's bundled list.  Keep verification on while using that system CA.
        truststore.inject_into_ssl()
        cls.client = Groq(api_key=cls.api_key)

    def test_llama_returns_a_real_completion(self):
        """Verify credentials, network access, and the required production model."""
        try:
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": "Reply with exactly: VERITAS_LIVE_OK"}],
                temperature=0,
                max_completion_tokens=12,
            )
        except (APIConnectionError, APIStatusError, RateLimitError) as exc:
            # Surface provider failures as test failures without ever including the key.
            self.fail(f"Groq live API request failed: {exc}")

        content = (response.choices[0].message.content or "").strip()
        self.assertTrue(content, "Groq returned an empty completion")
        self.assertIn("VERITAS_LIVE_OK", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
