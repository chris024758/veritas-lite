"""stt.py on a real spoken clip. Usage: test_05_stt.py <audio file>"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stt

start = time.time()
text = stt.transcribe(sys.argv[1])
print(f"model={stt.MODEL_SIZE} took {time.time() - start:.1f}s")
print("transcript:", text)
assert "housewarming" in text.lower() or "house warming" in text.lower()
print("PASS test_05_stt")
