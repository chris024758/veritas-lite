"""FastAPI backend. Run seed.py once first, then: uvicorn main:app --port 8018"""
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google.genai import errors
from pydantic import BaseModel

import db
import extraction
import gemini_client
import stt
import verification
from tools.image_gen import OUTPUT_DIR

app = FastAPI(title="VERITAS-Lite")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)
OUTPUT_DIR.mkdir(exist_ok=True)
app.mount("/generated", StaticFiles(directory=OUTPUT_DIR), name="generated")


class StartSession(BaseModel):
    case_id: str
    subject_name: str


class SubmitStatement(BaseModel):
    text: str


def _speaker(session: dict) -> str:
    case = db.get_case(session["case_id"])
    for subject in case["subjects"]:
        if subject["id"] == session["subject_id"]:
            return f"{subject['full_name']} ({subject['role']})"
    return "Unknown (not on the case file)"


def _require_session(session_id: int) -> dict:
    session = db.get_session_row(session_id)
    if session is None:
        raise HTTPException(404, f"session {session_id} not found")
    return session


def run_pipeline(session: dict, text: str) -> dict:
    """Extract claims, then verify each with the tool-calling loop. Stores everything."""
    try:
        claims = extraction.extract_claims(text)
    except gemini_client.GeminiNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except (errors.APIError, ValueError) as exc:
        raise HTTPException(502, f"claim extraction failed: {exc}")

    statement = db.add_statement(session["id"], text)
    claim_ids = [
        db.add_claim(statement["id"], claim["claim_type"], claim["text"], claim["entities"])
        for claim in claims
    ]
    outcomes = verification.verify_statement(claims, text, statement["id"], session["case_id"], _speaker(session))
    for claim_id, outcome in zip(claim_ids, outcomes):
        db.finish_claim(claim_id, outcome["status"], outcome["reason"], outcome["details"])
    return {**statement, "claims": db.get_claims(statement["id"])}


@app.post("/sessions/start")
def start_session(body: StartSession):
    if db.get_case(body.case_id) is None:
        raise HTTPException(404, f"case {body.case_id} not found")
    return {"session_id": db.create_session(body.case_id, body.subject_name)["id"]}


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
    suffix = Path(audio.filename or "").suffix or ".webm"
    handle, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(audio.file.read())
        try:
            transcript = stt.transcribe(path)
        except Exception as exc:  # faster-whisper/PyAV raise several types on an undecodable file
            raise HTTPException(400, f"could not transcribe audio: {exc}")
    finally:
        os.unlink(path)

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
