"""Alibi check, follow-ups, timeline and the end-of-interview report over real HTTP.
Needs run_fake_stack.py running (fresh: it seeds a throwaway database). Gemini's decisions are
SCRIPTED; everything else is real."""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
API = "http://localhost:8018"
FAKE = "http://127.0.0.1:8019"
CASE = "2026-PUN-0219"
ALIBI = ("I was at my cousin's housewarming in Hadapsar. Left around 9, rode to the shop to check "
         "the locks, reached around 9:40, then went straight home to Kothrud, got in by 9:50.")
SHIFT = "Actually, now I think about it, I only got home to Kothrud around 10:30."
passed = 0


def check(label, condition, detail=""):
    global passed
    if not condition:
        raise SystemExit(f"FAIL {label}: {detail}")
    passed += 1
    print(f"ok   {label}" + (f"  [{detail}]" if detail else ""))


def post(path, **kwargs):
    return requests.post(f"{API}{path}", timeout=120, **kwargs)


session = post("/sessions/start", json={"case_id": CASE, "subject_name": "Suresh Deshmukh"}).json()["session_id"]

# Turn 1: the alibi clashes with the seeded witness and the witness record
body = post(f"/sessions/{session}/statements", json={"text": ALIBI}).json()
findings = body["alibi_findings"]
kinds = sorted(f["kind"] for f in findings)
# The demo seed has no earlier interviews, so turn 1 clashes with the case record only;
# WITNESS findings are covered offline in test_07.
check("alibi gives an EVIDENCE finding on turn 1", kinds == ["EVIDENCE"], kinds)
home = next(c for c in body["claims"] if c["entities"].get("time") == "9:50")
check("the finding is on the home-by-9:50 claim", {f["claim"]["id"] for f in findings} == {home["id"]})
check("the finding quotes both sides", findings[0]["new_quote"] and findings[0]["prior_quote"], findings[0]["explanation"])
check("evidence finding points at the record", next(f for f in findings if f["kind"] == "EVIDENCE")["source"]["evidence_type"] == "witness_statement")
check("follow-ups returned, finding questions first", body["followups"] and body["followups"][0]["from_finding"],
      body["followups"][0]["question"] if body["followups"] else "")
check("follow-ups target real claim ids", all(i in {c["id"] for c in body["claims"]} for q in body["followups"] for i in q["targets_claim_ids"]))
check("no alibi or follow-up errors", body["alibi_error"] is None and body["followup_error"] is None)

# Turn 2: the subject moves their own time
body = post(f"/sessions/{session}/statements", json={"text": SHIFT}).json()
findings = body["alibi_findings"]
check("time shift gives a SELF finding", [f["kind"] for f in findings] == ["SELF"], [f["kind"] for f in findings])
claim = body["claims"][0]
check("SELF finding upgrades a PENDING claim to FLAGGED", claim["status"] == "FLAGGED" and "Alibi check" in claim["reason"], claim["reason"])
check("SELF finding quotes then and now", findings[0]["prior_quote"] == "9:50" and findings[0]["new_quote"] == "10:30")

# Alibi-check failure keeps the statement
body = post(f"/sessions/{session}/statements", json={"text": "TRIGGER_ALIBI_400 something"}).json()
check("failed alibi check still returns verdicts", body["claims"] and body["alibi_error"] and body["alibi_findings"] == [], body["alibi_error"][:60])

# History and case-wide findings
history = requests.get(f"{API}/sessions/{session}").json()
check("history carries findings and follow-ups per turn",
      len(history["statements"][0]["alibi_findings"]) == 1 and history["statements"][0]["followups"])
check("case findings list both", len(requests.get(f"{API}/cases/{CASE}/findings").json()) == 2)

# Timeline
view = requests.get(f"{API}/cases/{CASE}/timeline").json()
check("timeline lanes: evidence, suspect", [l["role"] for l in view["lanes"]] == ["Evidence", "Suspect"])
check("timeline has the incident window", view["incident"] == {"start": 1290, "end": 1350})
route = next(e for e in view["events"] if e["text"].startswith("Rode from Hadapsar"))
check("a journey is a range bar", (route["start"], route["end"], route["approx"]) == (1260, 1300, True))
check("timeline links match findings", len(view["links"]) == 2)
check("suspect has an alibi gap inside the window", any(g["lane"] == "s1" for g in view["gaps"]), view["gaps"])
check("evidence with a time is on the evidence lane", any(e["lane"] == "evidence" and e["start"] == 1335 for e in view["events"]))
check("timeline unknown case 404", requests.get(f"{API}/cases/NOPE/timeline").status_code == 404)

# Report
check("report before ending is 409", post(f"/sessions/{session}/report").status_code == 409)
check("GET report before generating is 404", requests.get(f"{API}/sessions/{session}/report").status_code == 404)
r = post(f"/sessions/{session}/end")
check("end interview sets ended_at", r.status_code == 200 and r.json()["ended_at"])
check("statement after end is 409", post(f"/sessions/{session}/statements", json={"text": SHIFT}).status_code == 409)
r = post(f"/sessions/{session}/report")
report = r.json()
check("report generated", r.status_code == 200 and report["summary"]["overview"].startswith("Scripted summary"), report["summary"]["overview"])
check("report has findings, tally and turns", len(report["alibi_findings"]) == 2 and report["tally"]["CONFLICT"] >= 1 and len(report["statements"]) == 3)
check("report leaves illustrative images out", all(e["tool"] != "generate_image" for s in report["statements"] for c in s["claims"] for e in c["evidence"]))
check("GET report returns the stored one", requests.get(f"{API}/sessions/{session}/report").json()["summary"] == report["summary"])
check("end unknown session 404", post("/sessions/999999/end").status_code == 404)

# A failed summary still leaves a structured report
other = post("/sessions/start", json={"case_id": CASE, "subject_name": "Suresh Deshmukh"}).json()["session_id"]
post(f"/sessions/{other}/statements", json={"text": "TRIGGER_REPORT_400 statement"})
post(f"/sessions/{other}/end")
report = post(f"/sessions/{other}/report").json()
check("failed summary keeps the structured report", report["summary"] is None and report["summary_error"] and len(report["statements"]) == 1)
print(f"\nPASS test_08_features_api: {passed} checks (Gemini decisions scripted)")
