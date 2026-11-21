"""FastAPI backend. Run seed.py once first, then: uvicorn main:app --port 8018"""
import os
import tempfile
import uuid
from pathlib import Path

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
from tools.image_gen import OUTPUT_DIR, generate_image as _hf_generate_image

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


class GenerateImageRequest(BaseModel):
    description: str


@app.post("/tools/generate-image")
def generate_image_endpoint(body: GenerateImageRequest):
    if not body.description.strip():
        raise HTTPException(422, "description must not be empty")
    return _hf_generate_image(body.description)


class StartSession(BaseModel):
    case_id: str
    subject_id: int | None = None
    subject_name: str | None = None  # older clients and tests; the UI sends subject_id


class SubmitStatement(BaseModel):
    text: str


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
        evidence = db.get_case(session["case_id"])["evidence"]
        return alibi_check.check(claims, text, speaker, session, prior, evidence), None
    except (errors.APIError, gemini_client.GeminiNotConfigured, ValueError) as exc:
        return [], f"Alibi check did not complete: {exc}"


def run_pipeline(session: dict, text: str) -> dict:
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
    statement = db.add_statement(session["id"], text)
    stored = [
        {**claim, "id": db.add_claim(statement["id"], claim["claim_type"], claim["text"], claim["entities"])}
        for claim in claims
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        verifying = pool.submit(verification.verify_statement, claims, text, statement["id"], session["case_id"], speaker)
        checking = pool.submit(_alibi_check, stored, text, statement["id"], session, speaker)
        outcomes = verifying.result()
        found, alibi_error = checking.result()

    for claim, outcome in zip(stored, outcomes):
        db.finish_claim(claim["id"], outcome["status"], outcome["reason"], outcome["details"])
    for finding in found:
        db.add_finding(session["case_id"], statement["id"], **finding)
        db.flag_for_finding(finding["claim_id"], f"Alibi check: {finding['explanation']}")

    results = db.get_claims(statement["id"])
    findings = db.get_findings(statement_id=statement["id"])
    followup_list, followup_error = [], None
    try:
        followup_list = followups.suggest(results, findings, speaker)
        db.set_followups(statement["id"], followup_list)
    except (errors.APIError, gemini_client.GeminiNotConfigured, ValueError) as exc:
        followup_error = f"Follow-up questions could not be generated: {exc}"
    return {**statement, "claims": results, "alibi_findings": findings, "followups": followup_list,
            "alibi_error": alibi_error, "followup_error": followup_error}


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
    """An image the investigator adds to the interview, for example a photo the subject shows.
    It is stored and shown in the conversation; it is not analysed or sent to Gemini."""
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
    (UPLOAD_DIR / filename).write_bytes(data)
    record = db.add_attachment(session_id, db.count_statements(session_id), filename,
                               image.filename, (caption or "").strip() or None)
    return {**record, "url": f"/uploads/{filename}"}


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


@app.post("/sessions/{session_id}/transcribe")
def transcribe_only(session_id: int, audio: UploadFile):
    """Speech-to-text only: nothing is stored and nothing goes to Gemini. The investigator
    reviews the text, then sends it to /statements."""
    session = _require_session(session_id)
    if session["ended_at"]:
        raise HTTPException(409, "this interview has ended")
    return {"transcript": _transcribe_upload(audio)}


@app.post("/sessions/{session_id}/statements")
def submit_statement(session_id: int, body: SubmitStatement):
    session = _require_session(session_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "statement text is empty")
    return run_pipeline(session, text)


@app.post("/sessions/{session_id}/audio")
def submit_audio(session_id: int, audio: UploadFile):
    session = _require_session(session_id)
    transcript = _transcribe_upload(audio)

    if not transcript:
        return {"transcript": "", "claims": []}
    try:
        return {"transcript": transcript, **run_pipeline(session, transcript)}
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
