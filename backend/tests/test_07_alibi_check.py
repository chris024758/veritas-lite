"""alibi_check.py, followups.py, timeline.py offline: the model's reply is STUBBED, so this proves
the parsing, kind assignment and filtering around Gemini, not Gemini's judgement."""
import json
import os
import sys
import tempfile
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["VERITAS_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import alibi_check
import db
import followups
import gemini_client
import seed
import timeline

seed.seed(with_witness_interview=True)
seed.seed(with_witness_interview=True)  # the witness session must not be duplicated
CASE = "2026-PUN-0219"
case = db.get_case(CASE)
assert (case["incident_start"], case["incident_end"]) == ("21:30", "22:30")
prior = db.get_case_claims(CASE)
assert len(prior) == 4 and {c["speaker"] for c in prior} == {"Ramesh Kulkarni"}, prior
print("seed: one witness session with 4 claims, incident window set")

for banned in ["pune", "suresh", "ramesh", "kothrud", "hadapsar", "activa", "lakshmi", "mh12"]:
    for prompt in (alibi_check.INSTRUCTIONS, followups.INSTRUCTIONS):
        assert banned not in prompt.lower(), banned
print("instructions contain no case-specific names")

session = db.create_session(CASE, "Suresh Deshmukh")
session = db.get_session_row(session["id"])
own = db.add_statement(session["id"], "earlier")
own_claim = db.add_claim(own["id"], "TIMELINE", "Home by 9:50", {"location": "Kothrud", "time_start": "21:50"})
statement = db.add_statement(session["id"], "now")
new_claim = {"id": db.add_claim(statement["id"], "TIMELINE", "Home at 10:30", {"location": "Kothrud"}),
             "claim_type": "TIMELINE", "text": "Home at 10:30", "entities": {"location": "Kothrud"}}
prior = db.get_case_claims(CASE, exclude_statement_id=statement["id"])
witness_claim = next(c for c in prior if c["claim_type"] == "VEHICLE")
evidence = case["evidence"]

reply = {"findings": [
    {"claim": 1, "source": f"C{own_claim}", "severity": "high", "explanation": "time moved", "new_quote": "10:30", "prior_quote": "9:50"},
    {"claim": 1, "source": f"C{witness_claim['id']}", "severity": "HIGH", "explanation": "witness"},
    {"claim": 1, "source": f"E{evidence[2]['id']}", "severity": "WEIRD", "explanation": "record"},
    {"claim": 1, "source": f"E{evidence[2]['id']}", "severity": "HIGH", "explanation": "duplicate"},
    {"claim": 1, "source": "C999999", "severity": "HIGH", "explanation": "invented"},
    {"claim": 7, "source": f"C{own_claim}", "severity": "HIGH", "explanation": "no such claim"},
]}
real_generate = gemini_client.generate
sent = {}
def stub(model, contents, config):
    sent["prompt"], sent["config"] = contents, config
    return SimpleNamespace(parsed=None, text=json.dumps(reply))
gemini_client.generate = stub

found = alibi_check.check([new_claim], "now", "Suresh Deshmukh (Suspect)", session, prior, evidence)
print(json.dumps(found, indent=1))
assert sent["prompt"].startswith("ALIBI CHECK") and sent["config"].response_mime_type == "application/json"
assert f"C{own_claim} | Suresh Deshmukh (Suspect)" in sent["prompt"] and f"E{evidence[2]['id']} | witness_statement" in sent["prompt"]
assert [f["kind"] for f in found] == ["SELF", "WITNESS", "EVIDENCE"], "kinds come from who spoke, not the model"
assert found[0]["severity"] == "HIGH" and found[2]["severity"] == "MEDIUM", "severity normalised"
assert found[0]["other_claim_id"] == own_claim and found[2]["evidence_id"] == evidence[2]["id"]
print("alibi check: SELF/WITNESS/EVIDENCE assigned, invented sources and duplicates dropped")

assert alibi_check.check([], "x", "s", session, prior, evidence) == []
for finding in found:
    db.add_finding(CASE, statement["id"], **finding)
db.finish_claim(new_claim["id"], "CONSISTENT", "fine", {})
db.flag_for_finding(new_claim["id"], "Alibi check: time moved")
claim = db.get_claims(statement["id"])[0]
assert claim["status"] == "FLAGGED" and claim["reason"].endswith("Alibi check: time moved"), claim
stored = db.get_findings(statement_id=statement["id"])
assert stored[0]["source"]["speaker"] == "Suresh Deshmukh" and stored[2]["source"]["type"] == "evidence"
print("findings stored with both sides; CONSISTENT claim upgraded to FLAGGED")

reply = {"questions": [
    {"question": "Plain one?", "claims": [1], "rationale": "r", "from_finding": False},
    {"question": "From the finding?", "claims": [1, 9], "rationale": "r", "from_finding": True},
    {"question": "  ", "claims": [], "rationale": "", "from_finding": False},
    {"question": "Three?", "claims": [], "from_finding": False},
    {"question": "Four?", "claims": [], "from_finding": False},
]}
claims = db.get_claims(statement["id"])
questions = followups.suggest(claims, stored, "Suresh Deshmukh (Suspect)")
print(json.dumps(questions, indent=1))
assert sent["prompt"].startswith("FOLLOW-UP QUESTIONS")
assert len(questions) == 3 and questions[0]["question"] == "From the finding?"
assert questions[0]["targets_claim_ids"] == [new_claim["id"]], "unknown claim numbers dropped"
calm = [{**claims[0], "status": "CONSISTENT"}]
assert followups.suggest(calm, [], "s") == [], "nothing doubtful, no call"
print("follow-ups: findings first, capped at three, skipped when nothing is doubtful")
gemini_client.generate = real_generate

assert timeline.to_minutes("21:40") == 1300 and timeline.to_minutes("9:40 PM") == 1300
assert timeline.to_minutes("9:50") == 1310 and timeline.to_minutes("09:15") == 555
assert timeline.to_minutes("10 am") == 600 and timeline.to_minutes("nonsense") is None
assert timeline._gaps((0, 60), [(10, 20), (15, 30)]) == [[0, 10], [30, 60]]
view = timeline.build(CASE)
lanes = [lane["label"] for lane in view["lanes"]]
assert lanes == ["Case evidence", "Suresh Deshmukh", "Ramesh Kulkarni"], lanes
assert view["incident"] == {"start": 1290, "end": 1350}
assert len(view["links"]) == 3 and {l["to"][0] for l in view["links"]} == {"c", "e"}
assert any(e["id"] == f"c{new_claim['id']}" for e in view["untimed"]), "no time, no made-up position"
suspect_gaps = [g for g in view["gaps"] if g["lane"] == "s1"]
assert suspect_gaps and suspect_gaps[0]["start"] == 1290, view["gaps"]
print("timeline: suspect lane first, links, untimed tray, alibi gaps")
print("PASS test_07_alibi_check")
