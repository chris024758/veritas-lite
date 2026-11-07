"""verification.py. Offline: the loop's plumbing against SCRIPTED fake model responses (this
proves dispatch and persistence-ready output, NOT Gemini's behaviour). Live: real tool choice."""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["VERITAS_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from google.genai import types

import gemini_client
import seed
import verification

seed.seed()
CASE = "2026-PUN-0219"
ALIBI = ("I was at my cousin's housewarming in Hadapsar. Left around 9, rode to the shop to check "
         "the locks, reached around 9:40, then went straight home to Kothrud, got in by 9:50.")
ROUTE_CLAIM = {"claim_type": "ROUTE", "text": "Went from the shop to home in Kothrud in 10 minutes.",
               "entities": {"origin": "the shop", "destination": "Kothrud", "claimed_minutes": 10}}
HOME_CLAIM = {"claim_type": "TIMELINE", "text": "Got home to Kothrud by 9:50.",
              "entities": {"location": "Kothrud", "time": "9:50"}}


def fn_response(name, args):
    part = types.Part(function_call=types.FunctionCall(name=name, args=args))
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))])


def text_response(text):
    part = types.Part(text=text)
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))])


real_generate = gemini_client.generate


def scripted(responses):
    seen = []

    def fake(model, contents, config):
        seen.append(config)
        return responses.pop(0)

    gemini_client.generate = fake
    return seen


# 1. tool call, then verdict: tool really runs, all four tools bound on every call
seen = scripted([
    fn_response("check_route", {"origin": "FC Road, Pune", "destination": "Kothrud, Pune", "claimed_minutes": 10}),
    text_response('{"status": "FLAGGED", "reason": "scripted"}'),
])
out = verification.verify_claim(ROUTE_CLAIM, ALIBI, 1, CASE, "Suresh Deshmukh (Suspect)")
print("scripted route ->", json.dumps(out, indent=1, ensure_ascii=False))
assert out["status"] == "FLAGGED" and out["details"]["tool_calls"][0]["result"]["actual_minutes"] > 10
for c in seen:
    assert {d.name for d in c.tools[0].function_declarations} == {
        "search_case_file", "check_route", "web_search", "generate_image"}

# 2. prose instead of JSON: asks again with tools off
seen = scripted([text_response("I think this is fine."), text_response('```json\n{"status":"consistent","reason":"r"}\n```')])
out = verification.verify_claim(HOME_CLAIM, ALIBI, 1, CASE, "x")
print("scripted prose then JSON ->", out["status"])
assert out["status"] == "CONSISTENT" and seen[1].tool_config.function_calling_config.mode == "NONE"

# 3. invalid verdict twice -> PENDING, no crash
scripted([text_response('{"status":"MAYBE","reason":"r"}'), text_response("still no")])
out = verification.verify_claim(HOME_CLAIM, ALIBI, 1, CASE, "x")
print("scripted invalid ->", out["status"], "|", out["reason"])
assert out["status"] == "PENDING"

# 4. model never stops calling tools -> bounded
scripted([fn_response("search_case_file", {"query": "x", "case_id": CASE}) for _ in range(verification.MAX_TOOL_ROUNDS)]
         + [text_response('{"status":"PENDING","reason":"r"}')])
out = verification.verify_claim(HOME_CLAIM, ALIBI, 1, CASE, "x")
print("scripted endless tools -> rounds:", len(out["details"]["tool_calls"]), out["status"])
assert len(out["details"]["tool_calls"]) == verification.MAX_TOOL_ROUNDS

# 5. the prompts stay generic and do not route by claim type
text = verification.SYSTEM_PROMPT + " ".join(d.description for d in verification.TOOL_DECLARATIONS)
for banned in ["pune", "suresh", "ramesh", "kothrud", "hadapsar", "activa", "lakshmi", "mh12"]:
    assert banned not in text.lower(), banned
print("prompts contain no case-specific names")

gemini_client.generate = real_generate
if not gemini_client.has_key():
    print("PASS test_04_verification (scripted only). LIVE SKIPPED: GEMINI_API_KEY not set")
    sys.exit(0)

for claim in (ROUTE_CLAIM, HOME_CLAIM):
    out = verification.verify_claim(claim, ALIBI, 1, CASE, "Suresh Deshmukh (Suspect)")
    print("\nLIVE", claim["text"], "\n", json.dumps(out, indent=1, ensure_ascii=False))
    assert out["status"] in ("FLAGGED", "CONFLICT"), out
print("PASS test_04_verification (live)")
