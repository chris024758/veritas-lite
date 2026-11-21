"""Alibi check: one Gemini call comparing a statement's new claims with everything already on
the case: the speaker's own earlier claims (SELF), other people's claims (WITNESS) and the
case-file records (EVIDENCE). The case is small, so nothing is pre-filtered.

The model only says WHICH items clash and why; the kind is worked out here from who said the
earlier claim, so a model mistake cannot turn a witness into the subject or the reverse."""
import json

from google.genai import types
from pydantic import BaseModel

import gemini_client

# Must stay generic: the case details arrive in the prompt, never in these instructions.
INSTRUCTIONS = """You check an interview subject's alibi. Compare each NEW claim with the EARLIER claims (from this speaker and from other people) and with the CASE RECORDS, and report every pair that cannot both be true.

Report a clash when, for example:
- the same person is placed in two different places at overlapping times;
- a time, place, vehicle or person in the new claim differs from what the speaker said earlier;
- a record or another person puts the speaker, or their vehicle, somewhere else at the time they claim.

Do not report pairs that are merely different topics, or that could both be true. Compare 24-hour times where given. Quote the exact clashing words from each side (a few words, not whole sentences).

severity: HIGH when the two cannot both be true, MEDIUM when they are hard to reconcile, LOW when they are only in tension.

Reply with JSON only: {"findings": [{"claim": <new claim number>, "source": "<C… or E… id>", "severity": "HIGH|MEDIUM|LOW", "explanation": "<one sentence>", "new_quote": "...", "prior_quote": "..."}]}. Reply {"findings": []} when nothing clashes."""

SEVERITIES = {"HIGH", "MEDIUM", "LOW"}


class Finding(BaseModel):
    claim: int
    source: str
    severity: str
    explanation: str
    new_quote: str | None = None
    prior_quote: str | None = None


class Findings(BaseModel):
    findings: list[Finding]


def _entities(entities: dict) -> str:
    return json.dumps(entities, ensure_ascii=False)


def build_prompt(claims: list[dict], statement: str, speaker: str,
                 prior_claims: list[dict], evidence: list[dict]) -> str:
    lines = ["ALIBI CHECK", f"Speaker: {speaker}", f"Statement: {statement}", "NEW claims:"]
    lines += [f"[{n}] ({c['claim_type']}) {c['text']} | entities: {_entities(c['entities'])}"
              for n, c in enumerate(claims, start=1)]
    lines.append("EARLIER claims:")
    lines += [f"C{c['id']} | {c['speaker']} ({c['speaker_role']}), turn {c['turn_index'] + 1} | "
              f"({c['claim_type']}) {c['text']} | entities: {_entities(c['entities'])}"
              for c in prior_claims] or ["(none)"]
    lines.append("CASE RECORDS:")
    lines += [f"E{e['id']} | {e['evidence_type']} | {e['description']} | metadata: {_entities(e['metadata'])}"
              for e in evidence] or ["(none)"]
    return "\n".join(lines)


def check(claims: list[dict], statement: str, speaker: str, session: dict,
          prior_claims: list[dict], evidence: list[dict]) -> list[dict]:
    """claims carry their stored ids. Returns findings ready for db.add_finding. Raises on a
    Gemini failure; the caller decides what that means for the statement."""
    if not claims or (not prior_claims and not evidence):
        return []
    response = gemini_client.generate(
        gemini_client.MODEL,
        build_prompt(claims, statement, speaker, prior_claims, evidence),
        types.GenerateContentConfig(
            system_instruction=INSTRUCTIONS,
            temperature=0,
            response_mime_type="application/json",
            response_schema=Findings,
        ),
    )
    parsed = response.parsed if isinstance(response.parsed, Findings) else Findings.model_validate_json(response.text)

    priors = {f"C{c['id']}": c for c in prior_claims}
    records = {f"E{e['id']}": e for e in evidence}
    results, seen = [], set()
    for item in parsed.findings:
        if not 1 <= item.claim <= len(claims):
            continue
        source = item.source.strip().upper()
        claim_id = claims[item.claim - 1]["id"]
        if (claim_id, source) in seen:
            continue
        if source in priors:
            prior = priors[source]
            same_person = prior["session_id"] == session["id"] or (
                session["subject_id"] is not None and prior["subject_id"] == session["subject_id"])
            kind, other_claim_id, evidence_id = ("SELF" if same_person else "WITNESS"), prior["id"], None
        elif source in records:
            kind, other_claim_id, evidence_id = "EVIDENCE", None, records[source]["id"]
        else:
            continue  # the model named something that does not exist
        seen.add((claim_id, source))
        severity = item.severity.strip().upper()
        results.append({
            "claim_id": claim_id, "other_claim_id": other_claim_id, "evidence_id": evidence_id,
            "kind": kind, "severity": severity if severity in SEVERITIES else "MEDIUM",
            "explanation": item.explanation.strip(),
            "new_quote": (item.new_quote or "").strip() or None,
            "prior_quote": (item.prior_quote or "").strip() or None,
        })
    return results
