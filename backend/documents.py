"""Reading an image shown during an interview (a ticket, a receipt, a photo): one Gemini call with
the image and the case context. The model only reads and relates; the program decides what is
stored (see main.add_attachment)."""
import re

from google.genai import types
from pydantic import BaseModel

import gemini_client

# Must stay generic: the case details arrive in the prompt, never in these instructions.
INSTRUCTIONS = """You read an image that a person showed during an investigative interview. Use only what is visible in the image.

Say what kind of document or picture it is and extract its fields (for a ticket: event, venue, date as YYYY-MM-DD, start time as 24-hour HH:MM, holder name; for a receipt: merchant, date, time, amount). Then relate it to the interview:
- supports: the numbers of the speaker's own claims that this image backs up.
- contradicts: claims by OTHER people (their C ids) that cannot be true if this image is genuine, for example because it places the speaker somewhere else at the time those claims describe.

Reply with JSON only:
{"document_type": "<e.g. event ticket, receipt, photo>", "fields": {"event": "...", "venue": "...", "date": "YYYY-MM-DD", "time": "HH:MM", "holder": "..."}, "summary": "<one sentence>", "supports": [<claim number>], "contradicts": [{"source": "C<id>", "severity": "HIGH|MEDIUM|LOW", "explanation": "<one sentence>", "prior_quote": "<a few words from that claim>"}]}"""


class Contradiction(BaseModel):
    source: str
    severity: str = "MEDIUM"
    explanation: str
    prior_quote: str | None = None


class Fields(BaseModel):
    """Fixed fields: the Gemini Developer API rejects free-form objects in a response schema."""
    event: str | None = None
    venue: str | None = None
    date: str | None = None
    time: str | None = None
    holder: str | None = None
    merchant: str | None = None
    amount: str | None = None
    other: str | None = None


class Reading(BaseModel):
    document_type: str
    fields: Fields = Fields()
    summary: str
    supports: list[int] = []
    contradicts: list[Contradiction] = []


def build_prompt(case: dict, speaker: str, own_claims: list[dict], other_claims: list[dict]) -> str:
    lines = [
        "DOCUMENT CHECK",
        f"Case: {case['name']} · incident date {case.get('incident_date') or 'unknown'}, "
        f"window {case.get('incident_start') or '?'}–{case.get('incident_end') or '?'}",
        f"Shown by: {speaker}",
        "This speaker's claims:",
    ]
    lines += [f"[{n}] ({c['claim_type']}) {c['text']}" for n, c in enumerate(own_claims, start=1)] or ["(none)"]
    lines.append("Other claims in the case:")
    lines += [f"C{c['id']} | {c['speaker']} ({c['speaker_role']}), turn {c['turn_index'] + 1} | ({c['claim_type']}) {c['text']}"
              for c in other_claims] or ["(none)"]
    return "\n".join(lines)


def read(image: bytes, mime_type: str, prompt: str) -> Reading:
    """Raises on a Gemini failure; the caller keeps the upload either way."""
    response = gemini_client.generate(
        gemini_client.MODEL,
        [types.Part.from_bytes(data=image, mime_type=mime_type), prompt],
        types.GenerateContentConfig(
            system_instruction=INSTRUCTIONS,
            temperature=0,
            response_mime_type="application/json",
            response_schema=Reading,
        ),
    )
    return response.parsed if isinstance(response.parsed, Reading) else Reading.model_validate_json(response.text)


def iso_date(value) -> str | None:
    """'2026-11-21', '21/11/2026', '21 Nov 2026' and similar to YYYY-MM-DD; None if unreadable."""
    if not value:
        return None
    text = str(value).strip().lower()
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        y, m, d = map(int, match.groups())
        return f"{y:04d}-{m:02d}-{d:02d}"
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    match = re.search(r"(\d{1,2})\s*(?:st|nd|rd|th)?[\s/.-]*([a-z]{3})[a-z]*[\s,/.-]*(\d{4})", text)
    if match and match.group(2) in months:
        return f"{int(match.group(3)):04d}-{months.index(match.group(2)) + 1:02d}-{int(match.group(1)):02d}"
    match = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", text)
    if match:  # day first, as written in India
        d, m, y = map(int, match.groups())
        return f"{y:04d}-{m:02d}-{d:02d}"
    return None
