"""End-of-interview report: the structured record of the session plus a short written summary
from one Gemini call. The structured part never depends on Gemini, so a failed summary still
leaves a usable report."""
from google.genai import errors, types
from pydantic import BaseModel

import db
import gemini_client

INSTRUCTIONS = """You write the summary section of an investigator's interview report. Use only the transcript, verdicts and alibi-check findings given. Be factual and neutral: do not state guilt, and attribute every point to a claim, record or witness.

Reply with JSON only: {"overview": "<2-3 sentences>", "key_findings": ["..."], "unresolved": ["..."], "next_steps": ["..."]}. Keep each list to at most four short items."""


class Summary(BaseModel):
    overview: str
    key_findings: list[str] = []
    unresolved: list[str] = []
    next_steps: list[str] = []


def _subject(case: dict, session: dict) -> dict | None:
    return next((s for s in case["subjects"] if s["id"] == session["subject_id"]), None)


def build_prompt(case: dict, subject: dict | None, history: dict, findings: list[dict]) -> str:
    lines = ["INTERVIEW REPORT", f"Case: {case['name']} ({case['id']})", f"Case summary: {case['summary']}",
             f"Subject: {subject['full_name'] + ' (' + subject['role'] + ')' if subject else 'Unknown'}",
             "Transcript and verdicts:"]
    for statement in history["statements"]:
        lines.append(f"T{statement['turn_index'] + 1}: {statement['text']}")
        lines += [f"  - {c['status']}: {c['text']} ({c.get('reason') or ''})" for c in statement["claims"]]
    lines.append("Alibi-check findings:")
    lines += [f"- {f['kind']} {f['severity']}: \"{f['claim']['text']}\" vs {f['source']['speaker']}: "
              f"\"{f['source']['text']}\". {f['explanation']}" for f in findings] or ["(none)"]
    return "\n".join(lines)


def _summarise(prompt: str) -> Summary:
    response = gemini_client.generate(
        gemini_client.MODEL,
        prompt,
        types.GenerateContentConfig(
            system_instruction=INSTRUCTIONS,
            temperature=0,
            response_mime_type="application/json",
            response_schema=Summary,
        ),
    )
    return response.parsed if isinstance(response.parsed, Summary) else Summary.model_validate_json(response.text)


def generate(session_id: int) -> dict:
    """Builds, stores and returns the report for an ended session."""
    history = db.get_session_history(session_id)
    case = db.get_case(history["case_id"])
    subject = _subject(case, history)
    findings = db.get_findings(session_id=session_id)

    summary, summary_error = None, None
    try:
        summary = _summarise(build_prompt(case, subject, history, findings)).model_dump()
    except (errors.APIError, gemini_client.GeminiNotConfigured, ValueError) as exc:
        summary_error = f"Summary could not be generated: {exc}"

    claims = [c for s in history["statements"] for c in s["claims"]]
    report = {
        "case": {k: case[k] for k in ("id", "name", "location", "summary")},
        "subject": subject,
        "started_at": history["started_at"],
        "ended_at": history["ended_at"],
        "summary": summary,
        "summary_error": summary_error,
        "tally": {status: sum(c["status"] == status for c in claims)
                  for status in ("CONFLICT", "FLAGGED", "CONSISTENT", "PENDING")},
        "statements": [
            {
                "turn_index": s["turn_index"],
                "text": s["text"],
                "claims": [
                    {
                        "id": c["id"], "text": c["text"], "claim_type": c["claim_type"],
                        "status": c["status"], "reason": c["reason"],
                        # Cited tool results, minus illustrative images: never evidence.
                        "evidence": [{"tool": t["name"], "args": t["args"], "result": t["result"]}
                                     for t in c["details"].get("tool_calls", []) if t["name"] != "generate_image"],
                    }
                    for c in s["claims"]
                ],
            }
            for s in history["statements"]
        ],
        "alibi_findings": findings,
        "attachments": [
            {"url": f"/uploads/{a['filename']}", "caption": a["caption"], "original_name": a["original_name"],
             "after_turn": a["after_turn"]}
            for a in history["attachments"]
        ],
        "open_followups":[q for s in history["statements"] for q in s["followups"]][-5:],
    }
    db.save_report(session_id, report)
    return report
