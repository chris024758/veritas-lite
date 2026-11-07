"""verification.py, batched per statement. Offline: the loop's plumbing against SCRIPTED fake
model responses (this proves dispatch and call accounting, NOT Gemini's behaviour).
Live (needs GEMINI_API_KEY, skipped with --offline): the alibi's claims verified in one batch."""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["VERITAS_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from google.genai import errors, types

import gemini_client
import seed
import verification

seed.seed()
CASE = "2026-PUN-0219"
SPEAKER = "Suresh Deshmukh (Suspect)"
ALIBI = ("I was at my cousin's housewarming in Hadapsar. Left around 9, rode to the shop to check "
         "the locks, reached around 9:40, then went straight home to Kothrud, got in by 9:50.")
# What gemini-3.5-flash-lite extracted from the alibi in the live test_02 run.
ALIBI_CLAIMS = [
    {"claim_type": "LOCATION", "text": "I was at my cousin's housewarming in Hadapsar.",
     "entities": {"location": "Hadapsar", "person": "cousin"}},
    {"claim_type": "ROUTE", "text": "I left Hadapsar around 9 and rode to the shop.",
     "entities": {"origin": "Hadapsar", "destination": "the shop", "claimed_minutes": 40, "time": "9"}},
    {"claim_type": "TIMELINE", "text": "I reached the shop around 9:40.",
     "entities": {"time": "9:40", "location": "the shop"}},
    {"claim_type": "ROUTE", "text": "I went from the shop to home in Kothrud.",
     "entities": {"origin": "the shop", "destination": "Kothrud", "claimed_minutes": 10, "time": "9:40"}},
    {"claim_type": "TIMELINE", "text": "I got in home in Kothrud by 9:50.",
     "entities": {"time": "9:50", "location": "Kothrud"}},
]
ROUTE_CLAIM, HOME_CLAIM = 3, 4  # zero-based indexes into ALIBI_CLAIMS


def response(*parts):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))])


def call(name, args):
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def text(value):
    return types.Part(text=value)


real_generate = gemini_client.generate


def scripted(responses):
    seen = []

    def fake(model, contents, config):
        seen.append((contents, config))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    gemini_client.generate = fake
    return seen


two_claims = [ALIBI_CLAIMS[ROUTE_CLAIM], ALIBI_CLAIMS[HOME_CLAIM]]

# 1. one round with two parallel calls, then verdicts citing them: each claim keeps only its calls
seen = scripted([
    response(call("search_case_file", {"query": "Suresh", "case_id": CASE}),
             call("check_route", {"origin": "FC Road, Pune", "destination": "Kothrud, Pune", "claimed_minutes": 10})),
    response(text(json.dumps({"verdicts": [
        {"claim": 1, "status": "FLAGGED", "reason": "scripted", "evidence_calls": [2]},
        {"claim": 2, "status": "conflict", "reason": "scripted", "evidence_calls": [1]},
    ]}))),
])
out = verification.verify_statement(two_claims, ALIBI, 1, CASE, SPEAKER)
print("scripted batch ->", [(o["status"], [c["name"] for c in o["details"]["tool_calls"]]) for o in out])
assert len(seen) == 2, "two claims must cost two model calls here, not four"
assert [o["status"] for o in out] == ["FLAGGED", "CONFLICT"]
assert [c["name"] for c in out[0]["details"]["tool_calls"]] == ["check_route"]
assert out[0]["details"]["tool_calls"][0]["result"]["actual_minutes"] > 10
assert [c["name"] for c in out[1]["details"]["tool_calls"]] == ["search_case_file"]
assert out[0]["details"]["statement_model_calls"] == 2
prompt = seen[0][0][0].parts[0].text
assert "[1] (ROUTE)" in prompt and "[2] (TIMELINE)" in prompt
responses_sent = [p.function_response.response for p in seen[1][0][2].parts]
assert [r["call_id"] for r in responses_sent] == [1, 2]
for _, config in seen:
    assert {d.name for d in config.tools[0].function_declarations} == {
        "search_case_file", "check_route", "web_search", "generate_image"}

# 2. prose instead of JSON: one tools-off retry
seen = scripted([response(text("Looks fine.")), response(text(
    '```json\n{"verdicts":[{"claim":1,"status":"consistent","reason":"r"},{"claim":2,"status":"PENDING","reason":"r"}]}\n```'))])
out = verification.verify_statement(two_claims, ALIBI, 1, CASE, SPEAKER)
print("scripted prose then JSON ->", [o["status"] for o in out])
assert [o["status"] for o in out] == ["CONSISTENT", "PENDING"]
assert seen[1][1].tool_config.function_calling_config.mode == "NONE"

# 3. a claim left out, and a claim with an invalid status: only those go PENDING
scripted([response(text('{"verdicts":[{"claim":1,"status":"FLAGGED","reason":"r"},{"claim":2,"status":"MAYBE","reason":"r"}]}'))])
out = verification.verify_statement(two_claims, ALIBI, 1, CASE, SPEAKER)
print("scripted partial ->", [(o["status"], o["reason"]) for o in out])
assert out[0]["status"] == "FLAGGED" and out[1]["status"] == "PENDING"

# 4. the model never stops calling tools: capped at MAX_TOOL_ROUNDS + 1 calls
loop = [response(call("search_case_file", {"query": "x", "case_id": CASE})) for _ in range(verification.MAX_TOOL_ROUNDS)]
seen = scripted(loop + [response(text('{"verdicts":[{"claim":1,"status":"PENDING","reason":"r"}]}'))])
out = verification.verify_statement(ALIBI_CLAIMS, ALIBI, 1, CASE, SPEAKER)
print("scripted endless tools -> model calls:", len(seen), "| statuses:", [o["status"] for o in out])
assert len(seen) == verification.MAX_TOOL_ROUNDS + 1
assert out[0]["status"] == "PENDING" and all(o["status"] == "PENDING" for o in out[1:])

# 5. Gemini fails: every claim PENDING, no crash
scripted([errors.ClientError(400, {"error": {"code": 400, "message": "scripted", "status": "INVALID_ARGUMENT"}})])
out = verification.verify_statement(two_claims, ALIBI, 1, CASE, SPEAKER)
print("scripted API error ->", [o["status"] for o in out])
assert all(o["status"] == "PENDING" and "did not complete" in o["reason"] for o in out)

# 6. no claims: no model call at all
seen = scripted([])
assert verification.verify_statement([], "I don't remember.", 1, CASE, SPEAKER) == [] and not seen

# 7. the prompts stay generic and do not route by claim type
prompt_text = verification.SYSTEM_PROMPT + " ".join(d.description for d in verification.TOOL_DECLARATIONS)
for banned in ["pune", "suresh", "ramesh", "kothrud", "hadapsar", "activa", "lakshmi", "mh12"]:
    assert banned not in prompt_text.lower(), banned
print("prompts contain no case-specific names")

gemini_client.generate = real_generate
if "--offline" in sys.argv or not gemini_client.has_key():
    print("PASS test_04_verification (scripted only). LIVE SKIPPED")
    sys.exit(0)

calls = []


def counting(model, contents, config):
    calls.append(model)
    return real_generate(model, contents, config)


gemini_client.generate = counting
out = verification.verify_statement(ALIBI_CLAIMS, ALIBI, 1, CASE, SPEAKER)
print(f"\nLIVE model={gemini_client.MODEL} | Gemini calls for verification: {len(calls)}")
for claim, o in zip(ALIBI_CLAIMS, out):
    tools = [(c["name"], c["args"]) for c in o["details"]["tool_calls"]]
    print(f"\n[{o['status']}] {claim['text']}\n  reason: {o['reason']}\n  tools: {json.dumps(tools, ensure_ascii=False)}")
assert len(calls) <= verification.MAX_TOOL_ROUNDS + 1
assert out[ROUTE_CLAIM]["status"] in ("FLAGGED", "CONFLICT"), "route claim not flagged"
assert out[HOME_CLAIM]["status"] in ("FLAGGED", "CONFLICT"), "home-by-9:50 claim not flagged"
print("PASS test_04_verification (live)")
