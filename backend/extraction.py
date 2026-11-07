"""One Gemini call: statement text in, typed claims out."""
from enum import Enum

from google.genai import types
from pydantic import BaseModel

import gemini_client


class ClaimType(str, Enum):
    ROUTE = "ROUTE"
    TIMELINE = "TIMELINE"
    LOCATION = "LOCATION"
    VEHICLE = "VEHICLE"
    PERSON = "PERSON"
    EVENT = "EVENT"
    OTHER = "OTHER"


class Entities(BaseModel):
    origin: str | None = None
    destination: str | None = None
    claimed_minutes: float | None = None
    time: str | None = None
    location: str | None = None
    person: str | None = None
    vehicle: str | None = None
    plate: str | None = None


class Claim(BaseModel):
    claim_type: ClaimType
    text: str
    entities: Entities


class ExtractionResult(BaseModel):
    claims: list[Claim]


# Must stay generic: no names or places from any particular case.
EXTRACTION_PROMPT = """You extract factual, checkable claims from a person's spoken statement in an investigative interview.

Split the statement into atomic claims. Each claim asserts one thing that could be checked against records, maps, or public information. Write each claim as a short self-contained sentence, keeping the speaker's own place names and times.

Claim types:
- ROUTE: a journey between two places. Set origin, destination, and claimed_minutes.
- TIMELINE: the speaker or someone else being somewhere, or doing something, at a stated time.
- LOCATION: a place existing or being as described, such as a venue or an address.
- VEHICLE: a vehicle used or seen, or its plate.
- PERSON: someone's identity, relationship, or presence.
- EVENT: an event having happened.
- OTHER: any other checkable fact.

Rules:
- When two timestamps bound a journey, set claimed_minutes to the difference between them, even if the speaker never states a duration. Example: "I left place A at 6:10 and got to place B by 6:35" gives a ROUTE claim with origin "place A", destination "place B", claimed_minutes 25.
- A journey with an arrival time also gets its own TIMELINE claim for being at the destination at that time.
- Copy places, people, and times exactly as spoken into entities. Do not resolve vague references such as "the office" or "my place", and do not invent details the speaker did not say. Leave unknown entity fields null.
- Do not extract opinions, feelings, greetings, or failures of memory. If the statement contains nothing checkable (for example "I don't remember"), return an empty claims list.

Statement:
"""


def extract_claims(statement: str) -> list[dict]:
    response = gemini_client.generate(
        gemini_client.MODEL,
        EXTRACTION_PROMPT + statement,
        types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=ExtractionResult,
        ),
    )
    result = response.parsed
    if result is None:
        result = ExtractionResult.model_validate_json(response.text)
    return [
        {
            "claim_type": claim.claim_type.value,
            "text": claim.text,
            "entities": claim.entities.model_dump(exclude_none=True),
        }
        for claim in result.claims
    ]
