"""Runs the REAL backend on :8018 against the fake Gemini on :8019, with a throwaway database.
Usage: run_fake_stack.py [spoken_clip.wav]"""
import os
import sys
import tempfile
import threading
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]

os.environ["VERITAS_DB"] = os.path.join(tempfile.mkdtemp(), "fake_stack.db")
os.environ["GEMINI_API_KEY"] = "fake-test-key"
os.environ["GOOGLE_GEMINI_BASE_URL"] = "http://127.0.0.1:8019"

import uvicorn

import fake_gemini_server
import seed

if len(sys.argv) > 1:
    fake_gemini_server.clip_path = sys.argv[1]
seed.seed()
threading.Thread(
    target=uvicorn.run,
    args=(fake_gemini_server.app,),
    kwargs={"host": "127.0.0.1", "port": 8019, "log_level": "warning"},
    daemon=True,
).start()

import main

uvicorn.run(main.app, port=8018, log_level="info")
