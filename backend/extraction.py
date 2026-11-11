"""Case-agnostic claim extraction using Groq structured output."""
from enum import Enum

from pydantic import BaseModel, Field

import groq_client


class ClaimType(str, Enum):
    ROUTE = "ROUTE"
    TIMELINE = "TIMELINE"
    LOCATION = "LOCATION"
    VEHICLE = "VEHICLE"
    PERSON = "PERSON"
    EVENT = "EVENT"
    OTHER = "OTHER"


class Entities(BaseModel):
    # Extra fields retain useful model output without coupling the database to every entity type.
    model_config = {"extra": "allow"}
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
    text: str = Field(min_length=1)
    entities: Entities


class ExtractionResult(BaseModel):
    claims: list[Claim]


EXTRACTION_PROMPT = """You extract factual, independently checkable claims from an investigative
interview statement. Ignore opinions, feelings, greetings, and failures of memory.

Return atomic claims. A journey between places is ROUTE and must include origin, destination,
and claimed_minutes whenever its timestamps establish a duration. Also extract an arrival as a
TIMELINE claim. Preserve names, places, and times exactly as said; do not resolve vague
references or invent facts. Claim types are ROUTE, TIMELINE, LOCATION, VEHICLE, PERSON, EVENT,
and OTHER. If there is nothing checkable, return an empty claims list."""


def extract_claims(statement: str) -> list[dict]:
    """Extract validated claims; schema validation protects persistence from malformed output."""
    if not statement.strip():
        return []
    try:
        result = groq_client.get_model().with_structured_output(ExtractionResult).invoke(
            [("system", EXTRACTION_PROMPT), ("human", statement)]
        )
    except groq_client.GroqNotConfigured:
        # Configuration is actionable and should map to HTTP 503, not a provider failure.
        raise
    except Exception as exc:  # Provider and transport failures need a user-safe API error.
        raise ValueError(f"claim extraction failed: {exc}") from exc
    if not isinstance(result, ExtractionResult):
        raise ValueError("claim extraction returned an invalid structured response")
    return [
        {"claim_type": claim.claim_type.value, "text": claim.text,
         "entities": claim.entities.model_dump(exclude_none=True)}
        for claim in result.claims
    ]
