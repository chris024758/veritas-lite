"""FastAPI backend. Run seed.py once first, then: uvicorn main:app --port 8018"""
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google.genai import errors
from pydantic import BaseModel

from concurrent.futures import ThreadPoolExecutor

import alibi_check
import db
import extraction
import followups
import gemini_client
import report
import report_docx
import stt
import timeline
import verification
from tools.image_gen import OUTPUT_DIR, discard_generated_file, generate_image
from tools.image_extract import ExtractionError, MAX_IMAGE_BYTES, extract_image
from tools.event_check import verify_event

app = FastAPI(title="VERITAS-Lite")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)
OUTPUT_DIR.mkdir(exist_ok=True)
db.init_db()  # adds any new tables and columns to an existing veritas.db
app.mount("/generated", StaticFiles(directory=OUTPUT_DIR), name="generated")
STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = Path(os.getenv("VERITAS_UPLOADS", Path(__file__).parent / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class IllustrationReview(BaseModel):
    preview: str
    approve: bool


IllustrationTarget = Literal["evidence", "claims"]


def _illustration_record(session_id: int, item_id: int, target: IllustrationTarget) -> dict:
    record = db.get_illustration_record(session_id, item_id, target)
    if record is None or not record["illustration_prompt"]:
        raise HTTPException(404, "no illustration suggestion for this record")
    return record


@app.post("/sessions/{session_id}/{target}/{item_id}/illustration")
def generate_illustration(session_id: int, target: IllustrationTarget, item_id: int):
    record = _illustration_record(session_id, item_id, target)
    if record["image"] or record["illustration_preview"]:
        return record

    prompt = (
        "Create a photorealistic reference image with natural lighting, realistic materials and a neutral background. "
        "Use the subject description only for its visual details, ignoring any style directions in it. "
        "Use a blank plate if the plate area is visible. Omit recognizable faces, identifying text, "
        "and surveillance overlays. Subject description: "
        + record["illustration_prompt"]
    )
    result = generate_image(prompt)
    preview = result.get("image_url")
    if result.get("placeholder") and preview:
        discard_generated_file(preview)
    if not preview or result.get("placeholder"):
        raise HTTPException(502, result.get("note") or "The image provider returned no illustration.")
    if not db.save_illustration_preview(item_id, preview, target):
        discard_generated_file(preview)
    return _illustration_record(session_id, item_id, target)


@app.post("/sessions/{session_id}/{target}/{item_id}/illustration/review")
def review_illustration(session_id: int, target: IllustrationTarget, item_id: int, body: IllustrationReview):
    record = _illustration_record(session_id, item_id, target)
    if body.approve and record["image"] and record["image"] == body.preview:
        return record
    if not db.review_illustration(item_id, body.preview, body.approve, target):
        raise HTTPException(409, "this illustration preview has changed")
    if not body.approve:
        discard_generated_file(body.preview)
    return _illustration_record(session_id, item_id, target)


@app.post("/tools/extract-image")
def extract_image_endpoint(image: UploadFile):
    data = image.file.read(MAX_IMAGE_BYTES + 1)
    return _check_image(data, image.content_type or "")


def _check_image(data: bytes, content_type: str) -> dict:
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image must be 10 MB or smaller.")
    try:
        result = extract_image(data, content_type)
    except ExtractionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if result.get("event"):
        result["event_verification"] = verify_event(result["event"])
    return result


class StartSession(BaseModel):
    case_id: str
    subject_id: int | None = None
    subject_name: str | None = None  # older clients and tests; the UI sends subject_id


class SubmitStatement(BaseModel):
    text: str
    transcript_segment_id: int | None = None
    request_id: uuid.UUID | None = None


class NewSubject(BaseModel):
    full_name: str
    role: str = "Witness"
    notes: str | None = None
    phone: str | None = None
    vehicle: str | None = None
    plate: str | None = None
    relation: str | None = None


class SubjectChanges(BaseModel):
    role: str | None = None
    notes: str | None = None
    phone: str | None = None
    vehicle: str | None = None
    plate: str | None = None
    relation: str | None = None


def _speaker(session: dict) -> str:
    """Who is speaking, with any vehicle or plate on file, so the checks can link a person
    added during the interview to records that mention their vehicle."""
    case = db.get_case(session["case_id"])
    for subject in case["subjects"]:
        if subject["id"] == session["subject_id"]:
            extra = [f"{label}: {subject[key]}" for key, label in
                     (("vehicle", "vehicle"), ("plate", "plate"), ("relation", "relation to case"))
                     if subject.get(key)]
            return f"{subject['full_name']} ({subject['role']})" + (f"; {'; '.join(extra)}" if extra else "")
    return "Unknown (not on the case file)"


def _require_session(session_id: int) -> dict:
    session = db.get_session_row(session_id)
    if session is None:
        raise HTTPException(404, f"session {session_id} not found")
    return session


def _alibi_check(claims: list[dict], text: str, statement_id: int, session: dict, speaker: str):
    """Findings, or an error string. Never raises: a failed alibi check must not lose the
    statement's verdicts."""
    try:
        prior = db.get_case_claims(session["case_id"], exclude_statement_id=statement_id)
        evidence = [record for record in db.get_case(session["case_id"])["evidence"]
                    if record["source"] != "upload"]
        return alibi_check.check(claims, text, speaker, session, prior, evidence), None
    except (errors.APIError, gemini_client.GeminiNotConfigured, ValueError) as exc:
        return [], f"Alibi check did not complete: {exc}"


def _keep_records(verified: dict, stored: list[dict], session: dict, statement_id: int,
                  prompts: dict[int, str] | None = None) -> list[dict]:
    """Keep case records grounded in a claim and save any illustration suggestion for review."""
    subject = db.get_subject(session["subject_id"]) if session["subject_id"] is not None else None
    if subject is None or subject["role"] == "Suspect":
        return []
    prompts = prompts if prompts is not None else {}
    kept = []
    for proposal in verified["records"][:3]:
        if not 1 <= proposal["claim"] <= len(stored) or not proposal["description"].strip():
            continue
        record_type = re.sub(r"[^a-z0-9_]+", "_", proposal["record_type"].strip().lower()).strip("_") or "observation"
        claim_id = stored[proposal["claim"] - 1].get("id")
        prompt = prompts.pop(claim_id, None) or (proposal.get("image_prompt") or "").strip()[:800]
        metadata = {k: v for k, v in (proposal.get("metadata") or {}).items() if v not in (None, "", [])}
        metadata.setdefault("reported_by", subject["full_name"])
        kept.append(db.add_evidence(
            session["case_id"], record_type, proposal["description"].strip(), metadata,
            source="statement", illustration_prompt=prompt or None,
            session_id=session["id"], statement_id=statement_id, subject_id=subject["id"],
        ))
    return kept


def run_pipeline(session: dict, text: str, transcript_segment_id: int) -> dict:
    """Extract claims; then, in parallel, verify them with the tool-calling loop and run the
    alibi check against everything already on the case; then suggest follow-ups."""
    if session["ended_at"]:
        raise HTTPException(409, "this interview has ended")
    try:
        claims = extraction.extract_claims(text)
    except gemini_client.GeminiNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except (errors.APIError, ValueError) as exc:
        raise HTTPException(502, f"claim extraction failed: {exc}")

    speaker = _speaker(session)
    statement = db.add_statement(session["id"], text, transcript_segment_id)
    stored = [
        {**claim, "id": db.add_claim(statement["id"], claim["claim_type"], claim["text"], claim["entities"])}
        for claim in claims
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        verifying = pool.submit(verification.verify_statement_full, claims, text, statement["id"], session["case_id"], speaker)
        checking = pool.submit(_alibi_check, stored, text, statement["id"], session, speaker)
        verified = verifying.result()
        found, alibi_error = checking.result()
    outcomes = verified["results"]

    for claim, outcome in zip(stored, outcomes):
        db.finish_claim(claim["id"], outcome["status"], outcome["reason"], outcome["details"])
    for finding in found:
        db.add_finding(session["case_id"], statement["id"], **finding)
        db.flag_for_finding(finding["claim_id"], f"Alibi check: {finding['explanation']}")

    prompts = {}
    for suggestion in verified.get("illustrations", []):
        number = suggestion["claim"]
        prompt = suggestion["prompt"].strip()[:800]
        if 1 <= number <= len(stored) and prompt:
            prompts.setdefault(stored[number - 1]["id"], prompt)
        if len(prompts) == 2:
            break
    new_records = _keep_records(verified, stored, session, statement["id"], prompts)
    for claim_id, prompt in prompts.items():
        db.save_claim_illustration(claim_id, prompt)

    results = db.get_claims(statement["id"])
    findings = db.get_findings(statement_id=statement["id"])
    followup_list, followup_error = [], None
    try:
        followup_list = followups.suggest(results, findings, speaker)
        db.set_followups(statement["id"], followup_list)
    except (errors.APIError, gemini_client.GeminiNotConfigured, ValueError) as exc:
        followup_error = f"Follow-up questions could not be generated: {exc}"
    return {**statement, "claims": results, "alibi_findings": findings, "followups": followup_list,
            "new_records": new_records, "alibi_error": alibi_error, "followup_error": followup_error}


@app.post("/sessions/start")
def start_session(body: StartSession):
    if db.get_case(body.case_id) is None:
        raise HTTPException(404, f"case {body.case_id} not found")
    if body.subject_id is not None:
        subject = db.get_subject(body.subject_id)
        if subject is None or subject["case_id"] != body.case_id:
            raise HTTPException(404, f"person {body.subject_id} is not on case {body.case_id}")
        return {"session_id": db.create_session_for_subject(body.case_id, body.subject_id)["id"]}
    if not body.subject_name:
        raise HTTPException(422, "choose who is being interviewed")
    return {"session_id": db.create_session(body.case_id, body.subject_name)["id"]}


@app.post("/sessions/{session_id}/attachments")
def add_attachment(session_id: int, image: UploadFile, caption: str | None = Form(None)):
    """Save the image on the interview and file it as case evidence."""
    session = _require_session(session_id)
    if session["ended_at"]:
        raise HTTPException(409, "this interview has ended")
    suffix = IMAGE_TYPES.get(image.content_type or "")
    if suffix is None:
        raise HTTPException(415, "only PNG, JPEG, WebP or GIF images can be added")
    data = image.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "images must be 10 MB or smaller")
    filename = f"{uuid.uuid4().hex}{suffix}"
    path = UPLOAD_DIR / filename
    caption = (caption or "").strip() or None
    try:
        path.write_bytes(data)
        return db.add_attachment(session, filename, image.filename, caption)
    except Exception:
        path.unlink(missing_ok=True)
        raise


@app.post("/sessions/{session_id}/attachments/{attachment_id}/extract")
def extract_attachment(session_id: int, attachment_id: int):
    attachment = db.get_attachment(session_id, attachment_id)
    if attachment is None:
        raise HTTPException(404, "image attachment not found in this interview")
    if "extraction" in attachment:
        return attachment["extraction"]

    path = UPLOAD_DIR / attachment["filename"]
    content_type = next((mime for mime, suffix in IMAGE_TYPES.items() if suffix == path.suffix), "")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_IMAGE_BYTES + 1)
    except FileNotFoundError as exc:
        raise HTTPException(404, "uploaded image file not found") from exc
    result = _check_image(data, content_type)
    db.save_attachment_extraction(session_id, attachment_id, result)
    return result


@app.get("/cases")
def list_cases():
    return db.list_cases()


@app.post("/cases/{case_id}/subjects")
def add_subject(case_id: str, body: NewSubject):
    if db.get_case(case_id) is None:
        raise HTTPException(404, f"case {case_id} not found")
    if not body.full_name.strip():
        raise HTTPException(422, "name is empty")
    if body.role not in db.VALID_ROLES:
        raise HTTPException(422, f"role must be one of {sorted(db.VALID_ROLES)}")
    person, existing = db.add_subject(case_id, body.model_dump())
    return {**person, "existing": existing}


@app.patch("/subjects/{subject_id}")
def update_subject(subject_id: int, body: SubjectChanges):
    if db.get_subject(subject_id) is None:
        raise HTTPException(404, f"person {subject_id} not found")
    if body.role is not None and body.role not in db.VALID_ROLES:
        raise HTTPException(422, f"role must be one of {sorted(db.VALID_ROLES)}")
    return db.update_subject(subject_id, body.model_dump(exclude_none=True))


def _transcribe_upload(audio: UploadFile) -> str:
    suffix = Path(audio.filename or "").suffix or ".webm"
    handle, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(audio.file.read())
        try:
            return stt.transcribe(path)
        except Exception as exc:  # faster-whisper/PyAV raise several types on an undecodable file
            raise HTTPException(400, f"could not transcribe audio: {exc}")
    finally:
        os.unlink(path)


def _capture_audio(session_id: int, audio: UploadFile) -> tuple[dict, str, int | None]:
    session = _require_session(session_id)
    if session["ended_at"]:
        raise HTTPException(409, "this interview has ended")
    transcript = _transcribe_upload(audio)
    if not transcript.strip():
        return session, "", None
    segment = db.add_transcript_segment(session_id, "recorded", transcript)
    return session, transcript, segment["id"]


@app.post("/sessions/{session_id}/transcribe")
def transcribe_only(session_id: int, audio: UploadFile):
    """Save the raw Whisper output and return it for review before analysis."""
    _, transcript, segment_id = _capture_audio(session_id, audio)
    return {"transcript": transcript, "transcript_segment_id": segment_id}


@app.post("/sessions/{session_id}/statements")
def submit_statement(session_id: int, body: SubmitStatement):
    session = _require_session(session_id)
    if session["ended_at"]:
        raise HTTPException(409, "this interview has ended")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "statement text is empty")
    segment_id = body.transcript_segment_id
    if segment_id is None:
        request_id = str(body.request_id) if body.request_id is not None else None
        segment = db.add_transcript_segment(session_id, "typed", body.text, request_id)
        if segment["raw_text"] != body.text:
            raise HTTPException(409, "this request ID was already used for different text")
        segment_id = segment["id"]
    elif not db.recorded_segment_exists(session_id, segment_id):
        raise HTTPException(422, "recorded transcript clip does not belong to this interview")
    return run_pipeline(session, text, segment_id)


@app.post("/sessions/{session_id}/audio")
def submit_audio(session_id: int, audio: UploadFile):
    session, transcript, segment_id = _capture_audio(session_id, audio)

    if segment_id is None:
        return {"transcript": "", "claims": []}
    try:
        return {"transcript": transcript, **run_pipeline(session, transcript, segment_id)}
    except HTTPException as exc:
        raise HTTPException(exc.status_code, f"{exc.detail} (transcript: {transcript})")


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    case = db.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    return case


@app.get("/sessions/{session_id}")
def get_session(session_id: int):
    history = db.get_session_history(session_id)
    if history is None:
        raise HTTPException(404, f"session {session_id} not found")
    return history


@app.get("/cases/{case_id}/transcripts")
def list_case_transcripts(case_id: str):
    return db.list_transcripts(case_id)


@app.get("/cases/{case_id}/transcripts/{session_id}")
def get_case_transcript(case_id: str, session_id: int):
    entries = db.get_transcript(case_id, session_id)
    if not entries:
        raise HTTPException(404, "no transcript for this interview")
    return {"session_id": session_id, "entries": entries}


@app.get("/cases/{case_id}/timeline")
def get_timeline(case_id: str):
    result = timeline.build(case_id)
    if result is None:
        raise HTTPException(404, f"case {case_id} not found")
    return result


@app.get("/cases/{case_id}/findings")
def get_case_findings(case_id: str):
    if db.get_case(case_id) is None:
        raise HTTPException(404, f"case {case_id} not found")
    return db.get_findings(case_id=case_id)


@app.post("/sessions/{session_id}/end")
def end_session(session_id: int):
    _require_session(session_id)
    db.end_session(session_id)
    return db.get_session_row(session_id)


@app.post("/sessions/{session_id}/report")
def generate_report(session_id: int):
    session = _require_session(session_id)
    if not session["ended_at"]:
        raise HTTPException(409, "end the interview before generating its report")
    return report.generate(session_id)


@app.get("/sessions/{session_id}/report")
def get_report(session_id: int):
    session = _require_session(session_id)
    if session["report"] is None:
        raise HTTPException(404, "no report yet for this session")
    return session["report"]


@app.get("/sessions/{session_id}/report.docx")
def get_report_docx(session_id: int):
    """Built in memory from the stored report and streamed; never written to disk here."""
    session = _require_session(session_id)
    if session["report"] is None:
        raise HTTPException(404, "generate the report first")
    data = report_docx.build(session["report"])
    name = f"veritas-report-{session['case_id']}-session{session_id}.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
