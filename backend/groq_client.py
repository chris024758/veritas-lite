"""Shared Groq configuration for the VERITAS reasoning pipeline.

Keeping construction here means every model call uses the same approved provider and model,
and callers receive one actionable configuration error instead of an SDK-specific failure.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv(Path(__file__).parent / ".env")

# The required Llama model stays the default. A deployment can explicitly override it when
# its Groq account no longer has access, avoiding an account-tier failure at runtime.
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


class GroqNotConfigured(RuntimeError):
    """Raised when the server cannot make an authorised Groq request."""


def get_model(*, temperature: float = 0) -> ChatGroq:
    """Build a model on demand so tests can set their environment before importing routes."""
    if not os.getenv("GROQ_API_KEY"):
        raise GroqNotConfigured("GROQ_API_KEY is not set; add it to backend/.env")
    return ChatGroq(model=MODEL, temperature=temperature, max_retries=2)
