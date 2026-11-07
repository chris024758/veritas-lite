"""generate_image: Gemini image generation. A tool-calling demo, not forensic evidence."""
import uuid
from html import escape
from pathlib import Path

from google.genai import errors, types

import gemini_client

OUTPUT_DIR = Path(__file__).parent.parent / "generated"

PLACEHOLDER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="512" height="288">
<rect width="512" height="288" fill="#e5e7eb"/>
<text x="256" y="130" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#374151">Placeholder: image not generated</text>
<text x="256" y="160" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#6b7280">{description}</text>
</svg>"""


def _placeholder(description: str, error: str) -> dict:
    """Per the PRD's risk table: a placeholder still proves the tool call happened."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex}.svg"
    (OUTPUT_DIR / name).write_text(PLACEHOLDER_SVG.format(description=escape(description[:70])), encoding="utf-8")
    return {"image_url": f"/generated/{name}", "placeholder": True, "error": error, "description": description}


def generate_image(description: str) -> dict:
    try:
        response = gemini_client.generate(
            gemini_client.IMAGE_MODEL,
            f"A simple illustrative sketch of: {description}",
            types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
        )
    except (errors.APIError, gemini_client.GeminiNotConfigured) as exc:
        return _placeholder(description, str(exc))

    parts = response.candidates[0].content.parts if response.candidates and response.candidates[0].content else None
    for part in parts or []:
        if part.inline_data and part.inline_data.data:
            OUTPUT_DIR.mkdir(exist_ok=True)
            name = f"{uuid.uuid4().hex}.png"
            (OUTPUT_DIR / name).write_bytes(part.inline_data.data)
            return {"image_url": f"/generated/{name}", "placeholder": False, "description": description}
    return _placeholder(description, "model returned no image")
