"""Generate illustrations with FLUX.1 Schnell via Cloudflare Workers AI."""
from __future__ import annotations

import base64
import os
import uuid
from html import escape
from pathlib import Path

import requests
from dotenv import load_dotenv

import db

load_dotenv(Path(__file__).parent.parent / ".env")

OUTPUT_DIR = Path(os.getenv("VERITAS_GENERATED", Path(__file__).parent.parent / "generated"))

# ---------------------------------------------------------------------------
# Cloudflare Workers AI configuration
# ---------------------------------------------------------------------------
_MODEL = "@cf/black-forest-labs/flux-1-schnell"
_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Internal: separated so tests can patch it cleanly
# ---------------------------------------------------------------------------
def _cloudflare_generate(description: str, account_id: str, token: str) -> bytes:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{_MODEL}"
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": description},
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise ValueError("Cloudflare Workers AI rejected the request.")
    image = base64.b64decode(payload["result"]["image"], validate=True)
    if not image.startswith(b"\xff\xd8\xff"):
        raise ValueError("Cloudflare Workers AI did not return a JPEG.")
    return image


# ---------------------------------------------------------------------------
# Public callable — works with or without langchain
# ---------------------------------------------------------------------------
def generate_image(description: str, *, owner: str | None = None) -> dict:
    """Generate a quick illustrative image from a text description.

    Returns a dict with at minimum an ``image_url`` key (served from
    /generated/<name>) on success, or ``placeholder=True`` / ``success=False``
    on graceful failure.  Never raises.
    """
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        if not account_id or not token:
            return _svg_placeholder(
                description,
                note="Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in backend/.env.",
                owner=owner,
            )
        image_bytes = _cloudflare_generate(description, account_id, token)
        name = _store_image(image_bytes, ".jpg", owner)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        return {"success": False, "note": f"Cloudflare Workers AI returned HTTP {status}."}
    except Exception:  # noqa: BLE001
        return {"success": False, "note": "Image generation failed."}

    return {
        "image_url": f"/generated/{name}",
        "placeholder": False,
        "description": description,
        "model": _MODEL,
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
def _store_image(data: bytes, suffix: str, owner: str | None) -> str:
    name = f"{uuid.uuid4().hex}{suffix}"
    path = OUTPUT_DIR / name
    try:
        path.write_bytes(data)
        if owner is not None:
            with db.connect() as conn:
                conn.execute("INSERT INTO generated_images VALUES (?, ?)", (name, owner))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return name


def _svg_placeholder(description: str, note: str = "", owner: str | None = None) -> dict:
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
    name = _store_image(svg.encode(), ".svg", owner)
    return {
        "image_url": f"/generated/{name}",
        "placeholder": True,
        "description": description,
        "note": note or "No image provider configured.",
    }
