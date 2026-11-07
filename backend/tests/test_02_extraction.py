"""extraction.py. Offline: prompt is generic, parsing works on a stubbed response.
Live (needs GEMINI_API_KEY): the alibi, an unrelated statement, and a zero-claim statement."""
import json
import os
import sys
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import extraction
import gemini_client

for banned in ["pune", "suresh", "ramesh", "kothrud", "hadapsar", "fc road", "activa", "lakshmi", "mh12"]:
    assert banned not in extraction.EXTRACTION_PROMPT.lower(), banned
print("offline: prompt contains no case-specific names")

real_generate = gemini_client.generate
gemini_client.generate = lambda *a, **k: SimpleNamespace(
    parsed=None,
    text='{"claims":[{"claim_type":"ROUTE","text":"t","entities":{"origin":"a","destination":"b","claimed_minutes":10}}]}',
)
stub = extraction.extract_claims("anything")
print("offline: stubbed parse ->", stub)
assert stub[0]["entities"]["claimed_minutes"] == 10
gemini_client.generate = real_generate

if not gemini_client.has_key():
    print("LIVE SKIPPED: GEMINI_API_KEY not set")
    sys.exit(0)

ALIBI = ("I was at my cousin's housewarming in Hadapsar. Left around 9, rode to the shop to check "
         "the locks, reached around 9:40, then went straight home to Kothrud, got in by 9:50.")
UNRELATED = ("On Tuesday I took the 7:15 train from Mysuru to Bengaluru with my colleague Anita Rao "
             "and we reached by 9:45. Then we had lunch at MTR on Lalbagh Road.")
print("model:", gemini_client.MODEL)
for label, text in [("alibi", ALIBI), ("unrelated", UNRELATED), ("zero", "I don't remember.")]:
    claims = extraction.extract_claims(text)
    print(f"\n--- {label}: {len(claims)} claims")
    print(json.dumps(claims, indent=1, ensure_ascii=False))
    if label == "zero":
        assert claims == []
    else:
        routes = [c for c in claims if c["claim_type"] == "ROUTE"]
        assert routes, "expected a ROUTE claim"
    if label == "alibi":
        assert any(r["entities"].get("claimed_minutes") == 10 for r in routes), "expected the 10-minute leg"
print("PASS test_02_extraction (live)")
