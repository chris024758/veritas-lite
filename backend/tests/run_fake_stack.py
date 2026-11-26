"""Runs the REAL backend on :8018 against the fake Gemini on :8019, with a throwaway database.
Usage: run_fake_stack.py [spoken_clip.wav]"""
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]

_tmp = tempfile.mkdtemp()
os.environ["VERITAS_DB"] = os.path.join(_tmp, "fake_stack.db")
os.environ["VERITAS_UPLOADS"] = os.path.join(_tmp, "uploads")
os.environ["VERITAS_GENERATED"] = os.path.join(_tmp, "generated")
os.environ["GEMINI_API_KEY"] = "fake-test-key"
os.environ["GOOGLE_GEMINI_BASE_URL"] = "http://127.0.0.1:8019"
os.environ["CLOUDFLARE_ACCOUNT_ID"] = "fake-account"
os.environ["CLOUDFLARE_API_TOKEN"] = "fake-token"

import uvicorn

import fake_gemini_server
from auth_test_helpers import seed_demo

if len(sys.argv) > 1:
    fake_gemini_server.clip_path = sys.argv[1]
seed_demo()
threading.Thread(
    target=uvicorn.run,
    args=(fake_gemini_server.app,),
    kwargs={"host": "127.0.0.1", "port": 8019, "log_level": "warning"},
    daemon=True,
).start()

import main

main.security.TOOL_LIMIT = 120  # The dedicated security tests cover throttling.
with patch("tools.image_gen._cloudflare_generate", return_value=b"\xff\xd8\xfftest\xff\xd9"):
    uvicorn.run(main.app, port=8018, log_level="info", proxy_headers=False)
