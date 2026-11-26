"""FastAPI backend. Run seed.py once first, then: uvicorn main:app --port 8018"""
import os
import re
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.genai import errors
from pydantic import BaseModel, Field

from concurrent.futures import ThreadPoolExecutor

import alibi_check
import db
import extraction
import followups
import gemini_client
import report
import report_docx
import security
import stt
import timeline
import verification
from tools.image_gen import OUTPUT_DIR, generate_image
from tools.image_extract import ExtractionError, MAX_IMAGE_BYTES, SIGNATURES, extract_image
from tools.event_check import verify_event

app = FastAPI(title="VERITAS-Lite", openapi_url=None if security.PRODUCTION else "/openapi.json",
              redirect_slashes=False)
origins = security.allowed_origins()
app.add_middleware(security.RequestSecurity, origins=origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "POST", "PATCH"],
    allow_headers=["Content-Type"],
    expose_headers=["Retry-After"],
)
app.include_router(security.auth)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
db.init_db()  # adds any new tables and columns to an existing veritas.db
STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = Path(os.getenv("VERITAS_UPLOADS", Path(__file__).parent / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # FastAPI's default includes the rejected input, which can contain a password or evidence.
    return JSONResponse({"detail": [{"loc": error["loc"], "msg": error["msg"]} for error in exc.errors()]},
                        status_code=422)


def _image_file(directory: Path, filename: str) -> FileResponse:
    path = (directory / filename).resolve()
    if path.parent != directory.resolve() or not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path, headers={"Content-Security-Policy": "default-src 'none'; sandbox"})


@app.get("/uploads/{filename}")
@app.head("/uploads/{filename}", include_in_schema=False)
def uploaded_image(filename: str, request: Request):
    if not re.fullmatch(r"[0-9a-f]{32}\.(png|jpg|webp|gif)", filename) or not db.owns_upload(filename, request.state.account):
        raise HTTPException(404, "File not found")
    return _image_file(UPLOAD_DIR, filename)


@app.get("/generated/{filename}")
@app.head("/generated/{filename}", include_in_schema=False)
def generated_image(filename: str, request: Request):
    if not re.fullmatch(r"[0-9a-f]{32}\.(png|jpg|svg)", filename) or not db.owns_generated_image(filename, request.state.account):
        raise HTTPException(404, "File not found")
    return _image_file(OUTPUT_DIR, filename)


class GenerateImageRequest(BaseModel):
    description: str = Field(max_length=4000)


@app.post("/tools/generate-image")
def generate_image_endpoint(body: GenerateImageRequest, request: Request):
    if not body.description.strip():
        raise HTTPException(422, "description must not be empty")
    return generate_image(body.description, owner=request.state.account)


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
    text: str = Field(max_length=12000)


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


def _require_case(case_id: str, request: Request) -> None:
    if not db.owns_case(case_id, request.state.account):
        raise HTTPException(404, f"case {case_id} not found")


def _require_session(session_id: int, request: Request) -> dict:
    session = db.get_session_row(session_id)
    if session is None or not db.owns_case(session["case_id"], request.state.account):
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
    except (errors.APIError, gemini_client.GeminiNotConfigured, ValueError):
        return [], "Alibi check did not complete."


def _keep_records(verified: dict, stored: list[dict], session: dict, statement_id: int) -> list[dict]:
    """Turn the model's record PROPOSALS into case records, under the program's rules: a suspect
    cannot add records, each must come from a real claim of this statement, and an image is
    attached only from a real generate_image call, marked as generated so nothing treats it as
    proof."""
    subject = db.get_subject(session["subject_id"]) if session["subject_id"] is not None else None
    if subject is None or subject["role"] == "Suspect":
        return []
    images = {c["id"]: c["result"].get("image_url") for c in verified["tool_calls"]
              if c["name"] == "generate_image" and isinstance(c.get("result"), dict)}
    kept = []
    for proposal in verified["records"][:3]:
        if not 1 <= proposal["claim"] <= len(stored) or not proposal["description"].strip():
            continue
        record_type = re.sub(r"[^a-z0-9_]+", "_", proposal["record_type"].strip().lower()).strip("_") or "observation"
        image = images.get(proposal.get("image_call"))
        metadata = {k: v for k, v in (proposal.get("metadata") or {}).items() if v not in (None, "", [])}
        metadata.setdefault("reported_by", subject["full_name"])
        kept.append(db.add_evidence(
            session["case_id"], record_type, proposal["description"].strip(), metadata,
            source="statement", image=image, image_kind="generated" if image else None,
            session_id=session["id"], statement_id=statement_id, subject_id=subject["id"],
        ))
    return kept


def run_pipeline(session: dict, text: str, owner: str) -> dict:
    """Extract claims; then, in parallel, verify them with the tool-calling loop and run the
    alibi check against everything already on the case; then suggest follow-ups."""
    if session["ended_at"]:
        raise HTTPException(409, "this interview has ended")
    try:
        claims = extraction.extract_claims(text)
    except gemini_client.GeminiNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except (errors.APIError, ValueError) as exc:
        raise HTTPException(502, "Claim extraction failed.") from exc

    speaker = _speaker(session)
    statement = db.add_statement(session["id"], text)
    stored = [
        {**claim, "id": db.add_claim(statement["id"], claim["claim_type"], claim["text"], claim["entities"])}
        for claim in claims
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        verifying = pool.submit(verification.verify_statement_full, claims, text, statement["id"], session["case_id"],
                                speaker, owner=owner)
        checking = pool.submit(_alibi_check, stored, text, statement["id"], session, speaker)
        verified = verifying.result()
        found, alibi_error = checking.result()
    outcomes = verified["results"]

    for claim, outcome in zip(stored, outcomes):
        db.finish_claim(claim["id"], outcome["status"], outcome["reason"], outcome["details"])
    for finding in found:
        db.add_finding(session["case_id"], statement["id"], **finding)
        db.flag_for_finding(finding["claim_id"], f"Alibi check: {finding['explanation']}")

    new_records = _keep_records(verified, stored, session, statement["id"])

    results = db.get_claims(statement["id"])
    findings = db.get_findings(statement_id=statement["id"])
    followup_list, followup_error = [], None
    try:
        followup_list = followups.suggest(results, findings, speaker)
        db.set_followups(statement["id"], followup_list)
    except (errors.APIError, gemini_client.GeminiNotConfigured, ValueError):
        followup_error = "Follow-up questions could not be generated."
    return {**statement, "claims": results, "alibi_findings": findings, "followups": followup_list,
            "new_records": new_records, "alibi_error": alibi_error, "followup_error": followup_error}


@app.post("/sessions/start")
def start_session(body: StartSession, request: Request):
    _require_case(body.case_id, request)
    if body.subject_id is not None:
        subject = db.get_subject(body.subject_id)
        if subject is None or subject["case_id"] != body.case_id:
            raise HTTPException(404, f"person {body.subject_id} is not on case {body.case_id}")
        return {"session_id": db.create_session_for_subject(body.case_id, body.subject_id)["id"]}
    if not body.subject_name:
        raise HTTPException(422, "choose who is being interviewed")
    return {"session_id": db.create_session(body.case_id, body.subject_name)["id"]}


@app.post("/sessions/{session_id}/attachments")
def add_attachment(session_id: int, image: UploadFile, request: Request, caption: str | None = Form(None, max_length=1000)):
    """Save the image on the interview and file it as case evidence."""
    session = _require_session(session_id, request)
    if session["ended_at"]:
        raise HTTPException(409, "this interview has ended")
    content_type = image.content_type or ""
    suffix = IMAGE_TYPES.get(content_type)
    if suffix is None:
        raise HTTPException(415, "only PNG, JPEG, WebP or GIF images can be added")
    data = image.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "images must be 10 MB or smaller")
    if not SIGNATURES[content_type](data):
        raise HTTPException(415, "image does not match its declared file type")
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
def extract_attachment(session_id: int, attachment_id: int, request: Request):
    _require_session(session_id, request)
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
def list_cases(request: Request):
    return db.list_cases(request.state.account)


@app.post("/cases/{case_id}/subjects")
def add_subject(case_id: str, body: NewSubject, request: Request):
    _require_case(case_id, request)
    if not body.full_name.strip():
        raise HTTPException(422, "name is empty")
    if body.role not in db.VALID_ROLES:
        raise HTTPException(422, f"role must be one of {sorted(db.VALID_ROLES)}")
    person, existing = db.add_subject(case_id, body.model_dump())
    return {**person, "existing": existing}


@app.patch("/subjects/{subject_id}")
def update_subject(subject_id: int, body: SubjectChanges, request: Request):
    subject = db.get_subject(subject_id)
    if subject is None or not db.owns_case(subject["case_id"], request.state.account):
        raise HTTPException(404, f"person {subject_id} not found")
    if body.role is not None and body.role not in db.VALID_ROLES:
        raise HTTPException(422, f"role must be one of {sorted(db.VALID_ROLES)}")
    return db.update_subject(subject_id, body.model_dump(exclude_none=True))


def _transcribe_upload(audio: UploadFile) -> str:
    data = audio.file.read(security.MAX_AUDIO_BYTES + 1)
    if len(data) > security.MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio must be 20 MB or smaller")
    suffix = Path(audio.filename or "").suffix.lower()
    if suffix not in {".wav", ".webm", ".mp3", ".m4a", ".mp4", ".ogg", ".flac"}:
        suffix = ".webm"
    handle, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        try:
            return stt.transcribe(path)
        except Exception as exc:  # faster-whisper/PyAV raise several types on an undecodable file
            raise HTTPException(400, "could not transcribe audio") from exc
    finally:
        os.unlink(path)


@app.post("/sessions/{session_id}/transcribe")
def transcribe_only(session_id: int, audio: UploadFile, request: Request):
    """Speech-to-text only: nothing is stored and nothing goes to Gemini. The investigator
    reviews the text, then sends it to /statements."""
    session = _require_session(session_id, request)
    if session["ended_at"]:
        raise HTTPException(409, "this interview has ended")
    return {"transcript": _transcribe_upload(audio)}


@app.post("/sessions/{session_id}/statements")
def submit_statement(session_id: int, body: SubmitStatement, request: Request):
    session = _require_session(session_id, request)
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "statement text is empty")
    return run_pipeline(session, text, request.state.account)


@app.post("/sessions/{session_id}/audio")
def submit_audio(session_id: int, audio: UploadFile, request: Request):
    session = _require_session(session_id, request)
    if session["ended_at"]:
        raise HTTPException(409, "this interview has ended")
    transcript = _transcribe_upload(audio)

    if not transcript:
        return {"transcript": "", "claims": []}
    try:
        return {"transcript": transcript, **run_pipeline(session, transcript, request.state.account)}
    except HTTPException as exc:
        raise HTTPException(exc.status_code, f"{exc.detail} (transcript: {transcript})")


@app.get("/cases/{case_id}")
def get_case(case_id: str, request: Request):
    _require_case(case_id, request)
    return db.get_case(case_id)


@app.get("/sessions/{session_id}")
def get_session(session_id: int, request: Request):
    _require_session(session_id, request)
    return db.get_session_history(session_id)


@app.get("/cases/{case_id}/timeline")
def get_timeline(case_id: str, request: Request):
    _require_case(case_id, request)
    return timeline.build(case_id)


@app.get("/cases/{case_id}/findings")
def get_case_findings(case_id: str, request: Request):
    _require_case(case_id, request)
    return db.get_findings(case_id=case_id)


@app.post("/sessions/{session_id}/end")
def end_session(session_id: int, request: Request):
    _require_session(session_id, request)
    db.end_session(session_id)
    return db.get_session_row(session_id)


@app.post("/sessions/{session_id}/report")
def generate_report(session_id: int, request: Request):
    session = _require_session(session_id, request)
    if not session["ended_at"]:
        raise HTTPException(409, "end the interview before generating its report")
    return report.generate(session_id)


@app.get("/sessions/{session_id}/report")
def get_report(session_id: int, request: Request):
    session = _require_session(session_id, request)
    if session["report"] is None:
        raise HTTPException(404, "no report yet for this session")
    return session["report"]


@app.get("/sessions/{session_id}/report.docx")
def get_report_docx(session_id: int, request: Request):
    """Built in memory from the stored report and streamed; never written to disk here."""
    session = _require_session(session_id, request)
    if session["report"] is None:
        raise HTTPException(404, "generate the report first")
    data = report_docx.build(session["report"])
    safe_case_id = re.sub(r"[^A-Za-z0-9_-]", "_", session["case_id"])[:64]
    name = f"veritas-report-{safe_case_id}-session{session_id}.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
