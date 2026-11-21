"""Suggested follow-up questions for the interviewer: one Gemini call, only when a statement left
something doubtful (a FLAGGED or CONFLICT claim, or an alibi-check finding)."""
from google.genai import types
from pydantic import BaseModel

import gemini_client

MAX_QUESTIONS = 3

INSTRUCTIONS = """You help an investigator interviewing someone. From the claims just checked, their verdicts, and the alibi-check findings, suggest up to three short, neutral, open questions the investigator should ask next to resolve what is doubtful. Put questions about alibi-check findings first. Never accuse, never reveal evidence the subject may not know about, and ask one thing per question.

Reply with JSON only: {"questions": [{"question": "...", "claims": [<claim numbers>], "rationale": "<why ask it, one short sentence>", "from_finding": true|false}]}"""


class Question(BaseModel):
    question: str
    claims: list[int] = []
    rationale: str = ""
    from_finding: bool = False


class Questions(BaseModel):
    questions: list[Question]


def needed(claims: list[dict], findings: list[dict]) -> bool:
    return bool(findings) or any(c["status"] in ("FLAGGED", "CONFLICT") for c in claims)


def build_prompt(claims: list[dict], findings: list[dict], speaker: str) -> str:
    number = {c["id"]: n for n, c in enumerate(claims, start=1)}
    lines = ["FOLLOW-UP QUESTIONS", f"Speaker: {speaker}", "Claims:"]
    lines += [f"[{n}] {c['status']} ({c['claim_type']}) {c['text']} | reason: {c.get('reason') or ''}"
              for n, c in enumerate(claims, start=1)]
    lines.append("Alibi-check findings:")
    lines += [f"- claim [{number[f['claim']['id']]}] vs {f['source']['speaker']} ({f['kind']}): "
              f"{f['explanation']}" for f in findings if f["claim"]["id"] in number] or ["(none)"]
    return "\n".join(lines)


def suggest(claims: list[dict], findings: list[dict], speaker: str) -> list[dict]:
    """[{question, targets_claim_ids, rationale, from_finding}], findings first, at most three.
    Raises on a Gemini failure."""
    if not needed(claims, findings):
        return []
    response = gemini_client.generate(
        gemini_client.MODEL,
        build_prompt(claims, findings, speaker),
        types.GenerateContentConfig(
            system_instruction=INSTRUCTIONS,
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=Questions,
        ),
    )
    parsed = response.parsed if isinstance(response.parsed, Questions) else Questions.model_validate_json(response.text)
    questions = [
        {
            "question": q.question.strip(),
            "targets_claim_ids": [claims[n - 1]["id"] for n in q.claims if 1 <= n <= len(claims)],
            "rationale": q.rationale.strip(),
            "from_finding": q.from_finding,
        }
        for q in parsed.questions if q.question.strip()
    ]
    questions.sort(key=lambda q: not q["from_finding"])
    return questions[:MAX_QUESTIONS]
