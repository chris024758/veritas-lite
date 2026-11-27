"""Shared Gemini access: key loading, model names, retry on transient errors."""
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from httpx import TimeoutException

load_dotenv(Path(__file__).parent / ".env")

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")

RETRYABLE_CODES = {429, 500, 503}
MAX_ATTEMPTS = int(os.getenv("GEMINI_MAX_ATTEMPTS", "4"))
TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "0"))

_client = None


class GeminiNotConfigured(RuntimeError):
    pass


def has_key() -> bool:
    key = os.getenv("GEMINI_API_KEY", "")
    return bool(key) and key != "your-gemini-api-key-here"


def get_client() -> genai.Client:
    global _client
    if not has_key():
        raise GeminiNotConfigured("GEMINI_API_KEY is not set; add it to backend/.env")
    if _client is None:
        options = None
        if TIMEOUT_MS:
            options = types.HttpOptions(timeout=TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1))
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=options)
    return _client


def generate(model: str, contents, config):
    for attempt in range(MAX_ATTEMPTS):
        try:
            return get_client().models.generate_content(model=model, contents=contents, config=config)
        except TimeoutException as exc:
            raise errors.ServerError(504, {"error": {"message": "Gemini request timed out."}}) from exc
        except errors.APIError as exc:
            if exc.code not in RETRYABLE_CODES or attempt == MAX_ATTEMPTS - 1:
                raise
            time.sleep(5 * 2**attempt)
