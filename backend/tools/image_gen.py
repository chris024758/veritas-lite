"""HuggingFace Inference API image-generation tool.

Primary model : black-forest-labs/FLUX.1-schnell  (fast, public, free tier)
Fallback model: stabilityai/stable-diffusion-xl-base-1.0

Design goals (per PRD §7 generate_image contract):
  - Non-blocking: any error is caught and returned as a plain dict so a failed
    call never aborts the claim-verification turn.
  - Graceful degradation: when HF_TOKEN is absent, an SVG placeholder is
    returned instead of raising.
  - Testable: the actual HTTP call lives in _hf_generate() so tests can patch
    it without touching networking.

Environment variables (loaded from backend/.env):
  HF_TOKEN  – HuggingFace access token (hf_…). Required for real generation.

Compatibility note:
  The function is decorated with @tool only when langchain_core is importable
  (some environments carry it; others don't).  Callers that cannot import
  langchain_core can still call generate_image() directly — it's a plain
  Python callable in both cases.
"""
from __future__ import annotations

import os
import uuid
from html import escape
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

OUTPUT_DIR = Path(__file__).parent.parent / "generated"

# ---------------------------------------------------------------------------
# HuggingFace Inference API config
# ---------------------------------------------------------------------------
_HF_API_BASE = "https://api-inference.huggingface.co/models"
_PRIMARY_MODEL = "black-forest-labs/FLUX.1-schnell"
_FALLBACK_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
_TIMEOUT = 60  # seconds; first cold-start of FLUX.1 can be slow


# ---------------------------------------------------------------------------
# Internal: separated so tests can patch it cleanly
# ---------------------------------------------------------------------------
def _hf_generate(description: str, token: str) -> bytes:
    """POST to HF Inference API; return raw image bytes.  Raises on failure."""
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"inputs": description}

    for model in (_PRIMARY_MODEL, _FALLBACK_MODEL):
        url = f"{_HF_API_BASE}/{model}"
        resp = requests.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
        if resp.status_code == 200:
            return resp.content
        if resp.status_code == 503:
            # Model still loading — try fallback before giving up
            continue
        raise RuntimeError(f"HF API {resp.status_code}: {resp.text[:200]}")

    raise RuntimeError("Both HF models unavailable (503).")


# ---------------------------------------------------------------------------
# Public callable — works with or without langchain
# ---------------------------------------------------------------------------
def generate_image(description: str) -> dict:
    """Generate a quick illustrative image from a text description.

    Returns a dict with at minimum an ``image_url`` key (served from
    /generated/<name>) on success, or ``placeholder=True`` / ``success=False``
    on graceful failure.  Never raises.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    token = os.getenv("HF_TOKEN", "").strip()

    if not token:
        return _svg_placeholder(
            description,
            note="Set HF_TOKEN in backend/.env to enable real image generation.",
        )

    try:
        image_bytes = _hf_generate(description, token)
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "note": f"image generation failed: {exc}"}

    name = f"{uuid.uuid4().hex}.png"
    dest = OUTPUT_DIR / name
    dest.write_bytes(image_bytes)

    return {
        "image_url": f"/generated/{name}",
        "placeholder": False,
        "description": description,
        "model": _PRIMARY_MODEL,
        "note": "Illustrative only — not forensic evidence.",
    }


# ---------------------------------------------------------------------------
# Optional LangChain @tool wrapper (for verification.py when langchain exists)
# ---------------------------------------------------------------------------
try:
    from langchain_core.tools import tool as _lc_tool  # type: ignore[import]

    @_lc_tool
    def generate_image_tool(description: str) -> dict:  # noqa: D401
        """Generate an explicitly non-evidentiary illustration from a scene description."""
        return generate_image(description)

except ModuleNotFoundError:
    # langchain_core not installed — verification.py must call generate_image() directly
    generate_image_tool = generate_image  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _svg_placeholder(description: str, note: str = "") -> dict:
    name = f"{uuid.uuid4().hex}.svg"
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='512' height='288'>"
        "<rect width='100%' height='100%' fill='#e5e7eb'/>"
        "<text x='256' y='120' text-anchor='middle' font-family='sans-serif' "
        "font-size='16' fill='#374151'>Illustration unavailable</text>"
        f"<text x='256' y='152' text-anchor='middle' font-size='12' fill='#6b7280'>"
        f"{escape(description[:60])}</text>"
        f"<text x='256' y='180' text-anchor='middle' font-size='10' fill='#9ca3af'>"
        f"{escape(note[:80])}</text>"
        "</svg>"
    )
    (OUTPUT_DIR / name).write_text(svg, encoding="utf-8")
    return {
        "image_url": f"/generated/{name}",
        "placeholder": True,
        "description": description,
        "note": note or "No image provider configured.",
    }
