"""Illustration tool with a safe placeholder when no image provider is configured."""
import uuid
from html import escape
from pathlib import Path

from langchain_core.tools import tool

OUTPUT_DIR = Path(__file__).parent.parent / "generated"


@tool
def generate_image(description: str) -> dict:
    """Generate an explicitly non-evidentiary illustration from a scene description."""
    try:
        OUTPUT_DIR.mkdir(exist_ok=True)
        name = f"{uuid.uuid4().hex}.svg"
        image = ("<svg xmlns='http://www.w3.org/2000/svg' width='512' height='288'>"
                 "<rect width='100%' height='100%' fill='#e5e7eb'/>"
                 "<text x='256' y='140' text-anchor='middle' font-family='sans-serif' "
                 "font-size='16' fill='#374151'>Illustration unavailable</text>"
                 f"<text x='256' y='170' text-anchor='middle' font-size='12'>{escape(description[:60])}</text></svg>")
        (OUTPUT_DIR / name).write_text(image, encoding="utf-8")
        return {"image_url": f"/generated/{name}", "placeholder": True, "description": description,
                "note": "No image-generation provider is configured; this is not evidence."}
    except OSError as exc:
        return {"success": False, "note": f"image generation unavailable: {exc}"}
