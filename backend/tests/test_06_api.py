"""Every endpoint and pipeline branch over real HTTP. Needs run_fake_stack.py running.
Usage: test_06_api.py <spoken_clip.wav>. Gemini's decisions are SCRIPTED; everything else is real."""
import json
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")
API = "http://localhost:8018"
FAKE = "http://127.0.0.1:8019"
CASE = "2026-PUN-0219"
ALIBI = ("I was at my cousin's housewarming in Hadapsar. Left around 9, rode to the shop to check "
         "the locks, reached around 9:40, then went straight home to Kothrud, got in by 9:50.")
UNRELATED = ("On Tuesday I took the 7:15 train from Mysuru to Bengaluru and reached by 9:45. Then we "
             "had lunch at MTR on Lalbagh Road. I saw a red Maruti van outside.")
passed = 0


def check(label, condition, detail=""):
    global passed
    if not condition:
        raise SystemExit(f"FAIL {label}: {detail}")
    passed += 1
    print(f"ok   {label}" + (f"  [{detail}]" if detail else ""))


def post_statement(session, text):
    return requests.post(f"{API}/sessions/{session}/statements", json={"text": text}, timeout=120)


def start(subject="Suresh Deshmukh"):
    r = requests.post(f"{API}/sessions/start", json={"case_id": CASE, "subject_name": subject})
    return r.json()["session_id"]


def tools_used(claim):
    return [c["name"] for c in claim["details"]["tool_calls"]]


# GET /cases/{id}
r = requests.get(f"{API}/cases/{CASE}")
body = r.json()
check("GET case 200", r.status_code == 200)
check("case has 2 subjects, 4 evidence", len(body["subjects"]) == 2 and len(body["evidence"]) == 4)
check("GET unknown case 404", requests.get(f"{API}/cases/NOPE").status_code == 404)

# POST /sessions/start
r = requests.post(f"{API}/sessions/start", json={"case_id": CASE, "subject_name": "Suresh Deshmukh"})
session = r.json()["session_id"]
check("start session returns id", r.status_code == 200 and isinstance(session, int), f"session {session}")
check("start unknown case 404", requests.post(f"{API}/sessions/start", json={"case_id": "X", "subject_name": "y"}).status_code == 404)
check("start missing field 422", requests.post(f"{API}/sessions/start", json={"case_id": CASE}).status_code == 422)
other = start("Nobody On File")
check("unknown subject session has no subject", requests.get(f"{API}/sessions/{other}").json()["subject_id"] is None)

# POST /sessions/{id}/statements: the alibi
r = post_statement(session, ALIBI)
body = r.json()
print(json.dumps([{k: c[k] for k in ("claim_type", "status", "reason", "text")} | {"tools": tools_used(c)}
                  for c in body["claims"]], indent=1, ensure_ascii=False))
check("alibi 200, 4 claims", r.status_code == 200 and len(body["claims"]) == 4)
route = next(c for c in body["claims"] if c["entities"].get("claimed_minutes") == 10)
result = route["details"]["tool_calls"][-1]["result"]
check("route claim FLAGGED", route["status"] == "FLAGGED", route["reason"])
check("route uses real OSRM distance", result["osrm_minutes"] > 0 and result["distance_km"] > 1, f"{result['distance_km']} km, source {result['source']}")
check("gap equals actual minus claimed", abs(result["gap_minutes"] - (result["actual_minutes"] - 10)) < 0.11, f"gap {result['gap_minutes']}")
check("vague 'the shop' resolved through the case file", result["origin_matched"] == "FC Road, Pune" and tools_used(route)[0] == "search_case_file")
leg = next(c for c in body["claims"] if c["entities"].get("claimed_minutes") == 40)
check("Hadapsar leg is not flagged", leg["status"] == "CONSISTENT", leg["reason"])
home = next(c for c in body["claims"] if c["entities"].get("time") == "9:50")
check("home-by-9:50 cross-ref CONFLICT from witness record", home["status"] == "CONFLICT" and "witness_statement" in home["reason"], home["reason"])
check("every alibi claim has a reason", all(c["reason"] for c in body["claims"]))

# Unrelated statement: other places and people, using web_search and generate_image
r = post_statement(session, UNRELATED)
body = r.json()
print(json.dumps([{k: c[k] for k in ("claim_type", "status", "reason")} | {"tools": tools_used(c)}
                  for c in body["claims"]], indent=1, ensure_ascii=False))
check("unrelated statement 200, 3 claims", r.status_code == 200 and len(body["claims"]) == 3)
train = body["claims"][0]["details"]["tool_calls"][-1]["result"]
check("long trip uses OSRM time, no urban speed", train["assumed_speed_kmh"] is None and train["distance_km"] > 100 and body["claims"][0]["status"] == "CONSISTENT", f"{train['actual_minutes']} min")
web = body["claims"][1]
check("web_search result and source reach the claim", tools_used(web) == ["web_search"] and web["details"]["tool_calls"][0]["result"]["sources"])
van = body["claims"][2]
image = van["details"]["tool_calls"][-1]["result"]
check("generate_image called, not a placeholder", image["placeholder"] is False)
r = requests.get(API + image["image_url"])
check("generated image is served as a PNG", r.status_code == 200 and r.content[:4] == b"\x89PNG", f"{len(r.content)} bytes")
check("unrelated vehicle finds nothing in the case file", van["status"] == "PENDING")

# Zero checkable claims
for text in ("I don't remember.", "I do not remember anything."):
    r = post_statement(session, text)
    check(f"zero claims: {text!r}", r.status_code == 200 and r.json()["claims"] == [])

# Bad input
check("blank text 422", post_statement(session, "   ").status_code == 422)
check("missing text 422", requests.post(f"{API}/sessions/{session}/statements", json={}).status_code == 422)
check("non-JSON body 422", requests.post(f"{API}/sessions/{session}/statements", data="x", headers={"Content-Type": "application/json"}).status_code == 422)
check("unknown session 404", post_statement(999999, "x").status_code == 404)
big = post_statement(session, "Unicode ₹ मराठी 'quotes\"; DROP TABLE claims;-- %_")
check("SQL-looking and Unicode text is safe", big.status_code == 200 and requests.get(f"{API}/cases/{CASE}").status_code == 200)

# Failure paths: no crash, sensible status, nothing half-written
before = len(requests.get(f"{API}/sessions/{session}").json()["statements"])
r = post_statement(session, "TRIGGER_EXTRACT_400")
check("Gemini 400 on extraction gives 502", r.status_code == 502, r.json()["detail"][:70])
r = post_statement(session, "TRIGGER_MALFORMED")
check("malformed extraction JSON gives 502", r.status_code == 502, r.json()["detail"][:70])
check("failed extraction stores no statement", len(requests.get(f"{API}/sessions/{session}").json()["statements"]) == before)

t = time.time()
r = post_statement(session, "TRIGGER_429 second attempt succeeds")
check("429 retried then succeeds", r.status_code == 200 and time.time() - t >= 4, f"{time.time() - t:.1f}s")

r = post_statement(session, "TRIGGER_VERIFY_400")
claim = r.json()["claims"][0]
check("verification failure leaves that claim PENDING", r.status_code == 200 and claim["status"] == "PENDING" and "did not complete" in claim["reason"], claim["reason"][:70])
r = post_statement(session, "TRIGGER_PROSE")
check("prose answer triggers a tools-off retry", r.json()["claims"][0]["reason"] == "Verdict from the tools-off retry.", r.json()["claims"][0]["reason"])
r = post_statement(session, "TRIGGER_BAD_ARGS")
check("tool call with missing args reaches model as an error", "missing argument" in r.json()["claims"][0]["reason"], r.json()["claims"][0]["reason"])
r = post_statement(session, "TRIGGER_UNKNOWN_TOOL")
check("unknown tool reaches model as an error", "unknown tool" in r.json()["claims"][0]["reason"], r.json()["claims"][0]["reason"])

# Prior turns are visible; the current statement is not its own evidence
second = start()
post_statement(second, "Zebraquill statement one")
r = post_statement(second, "Zebraquill statement two")
result = r.json()["claims"][0]["details"]["tool_calls"][0]["result"]
check("search sees the prior turn but not the current one", len(result["prior_statements"]) == 1 and "one" in result["prior_statements"][0]["text"])

# POST /sessions/{id}/audio
clip = sys.argv[1]
with open(clip, "rb") as f:
    r = requests.post(f"{API}/sessions/{session}/audio", files={"audio": ("clip.wav", f)}, timeout=180)
body = r.json()
check("audio returns transcript and claims", r.status_code == 200 and "housewarming" in body["transcript"].lower() and body["claims"], body["transcript"][:70])
print("     audio claim statuses:", [c["status"] for c in body["claims"]])
r = requests.post(f"{API}/sessions/{session}/audio", files={"audio": ("bad.wav", b"not audio")})
check("undecodable audio 400", r.status_code == 400)
check("missing audio file 422", requests.post(f"{API}/sessions/{session}/audio").status_code == 422)
with open(clip, "rb") as f:
    check("audio on unknown session 404", requests.post(f"{API}/sessions/999999/audio", files={"audio": ("c.wav", f)}).status_code == 404)

# GET /sessions/{id}
history = requests.get(f"{API}/sessions/{session}").json()
turns = [s["turn_index"] for s in history["statements"]]
check("history turn numbers are sequential", turns == list(range(len(turns))), f"{len(turns)} turns")
check("history includes claims with status", history["statements"][0]["claims"][0]["status"] in ("CONSISTENT", "FLAGGED", "CONFLICT", "PENDING"))
check("GET unknown session 404", requests.get(f"{API}/sessions/999999").status_code == 404)

# What the real SDK actually sent
seen = requests.get(f"{FAKE}/_requests").json()
verification_calls = [q for q in seen if any("functionDeclarations" in t for t in q["body"].get("tools", []))]
names = {d["name"] for t in verification_calls[0]["body"]["tools"] for d in t["functionDeclarations"]}
check("all four tools bound on every verification call", len(verification_calls) > 10, f"{len(verification_calls)} calls, tools {sorted(names)}")
check("grounding request used googleSearch", any("googleSearch" in t for q in seen for t in q["body"].get("tools", [])))
check("image request used the image model", any("image" in q["model"] for q in seen))
print(f"\nPASS test_06_api: {passed} checks (Gemini decisions scripted)")
