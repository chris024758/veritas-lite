"""The demo, end to end over real HTTP. Needs a FRESH run_fake_stack.py (demo seed, no
interviews). Gemini's decisions are SCRIPTED; everything else is real.

Flow: directory -> pick Suresh from the case's people -> turn 1 (maps check + evidence clash)
-> turn 2 (own-statement clash) -> turn 3 (vehicle: evidence clash + generated image)
-> end -> report -> .docx, which is written to a temp file, checked, then deleted."""
import io
import os
import sys
import tempfile

import requests
from docx import Document

sys.stdout.reconfigure(encoding="utf-8")
API = "http://localhost:8018"
CASE = "2026-PUN-0219"
TURN1 = ("I was at my cousin's housewarming in Hadapsar. Left around 9, rode to the shop to check "
         "the locks, reached around 9:40, then went straight home to Kothrud, got in by 9:50.")
TURN2 = "Actually, now I think about it, I only got home to Kothrud around 10:30."
TURN3 = "My white Activa was parked at home the whole night."
passed = 0


def check(label, condition, detail=""):
    global passed
    if not condition:
        raise SystemExit(f"FAIL {label}: {detail}")
    passed += 1
    print(f"ok   {label}" + (f"  [{detail}]" if detail else ""))


def post(path, **kwargs):
    return requests.post(f"{API}{path}", timeout=120, **kwargs)


# Directory and case file
cases = requests.get(f"{API}/cases").json()
check("directory lists the jewellers case and placeholders", [c["id"] for c in cases][0] == CASE and len(cases) == 3)
jewellers = cases[0]
check("jewellers case starts with no interviews", jewellers["interviews"] == 0 and jewellers["people"] == 2)
case = requests.get(f"{API}/cases/{CASE}").json()
suresh = next(s for s in case["subjects"] if s["full_name"] == "Suresh Deshmukh")
check("Suresh is on file with his scooter", suresh["role"] == "Suspect" and suresh["plate"] == "MH12 AB 4521")
stolen = next(e for e in case["evidence"] if e["evidence_type"] == "stolen_items")
check("stolen items seeded with details and images", len(stolen["items"]) == 4
      and all(i["image"] and i["value"] and i["weight"] for i in stolen["items"]), [i["name"] for i in stolen["items"]])
check("every jewellers record has an illustration", all(e["image"] for e in case["evidence"]))
check("illustrations are served", requests.get(API + stolen["items"][0]["image"]).headers["content-type"].startswith("image/svg"))

# People: add new, duplicates, validation
r = post(f"/cases/{CASE}/subjects", json={"full_name": "Anita Joshi", "role": "Witness", "notes": "Customer"})
anita = r.json()
check("add a new person", r.status_code == 200 and anita["existing"] is False and anita["interviews"] == 0)
r = post(f"/cases/{CASE}/subjects", json={"full_name": "  ramesh kulkarni ", "role": "Witness"})
check("duplicate name returns the existing person", r.json()["existing"] is True and r.json()["full_name"] == "Ramesh Kulkarni")
check("bad role 422", post(f"/cases/{CASE}/subjects", json={"full_name": "X", "role": "Boss"}).status_code == 422)
check("empty name 422", post(f"/cases/{CASE}/subjects", json={"full_name": "  "}).status_code == 422)
r = requests.patch(f"{API}/subjects/{anita['id']}", json={"role": "Other", "notes": "Was in the shop that evening"})
check("edit a person's role", r.json()["role"] == "Other" and r.json()["notes"].startswith("Was in"))
check("edit unknown person 404", requests.patch(f"{API}/subjects/999999", json={"role": "Other"}).status_code == 404)

# Starting an interview needs a person on this case
check("start with nobody 422", post("/sessions/start", json={"case_id": CASE}).status_code == 422)
check("start with someone from another case 404",
      post("/sessions/start", json={"case_id": "2026-PUN-0231", "subject_id": suresh["id"]}).status_code == 404)
other = post("/sessions/start", json={"case_id": CASE, "subject_id": anita["id"]})
check("a newly added person can be interviewed", other.status_code == 200)
session = post("/sessions/start", json={"case_id": CASE, "subject_id": suresh["id"]}).json()["session_id"]

# Speech-to-text only: nothing stored, nothing sent to Gemini
with open(os.path.join(os.path.dirname(__file__), "alibi_espeak.wav"), "rb") as f:
    r = post(f"/sessions/{session}/transcribe", files={"audio": ("clip.wav", f)})
check("transcribe returns text only", r.status_code == 200 and "housewarming" in r.json()["transcript"].lower(), r.json()["transcript"][:60])
check("transcribe stores no statement", requests.get(f"{API}/sessions/{session}").json()["statements"] == [])

# Turn 1: maps check + evidence clash
body = post(f"/sessions/{session}/statements", json={"text": TURN1}).json()
route = next(c for c in body["claims"] if c["entities"].get("claimed_minutes") == 10)
result = route["details"]["tool_calls"][-1]["result"]
check("turn 1 maps check flags shop -> Kothrud", route["status"] == "FLAGGED" and result["exceeds_tolerance"], route["reason"])
check("maps panel has from, to, distance, minutes, gap",
      all(k in result for k in ("origin", "destination", "distance_km", "actual_minutes", "claimed_minutes", "gap_minutes")))
check("turn 1 clashes with the evidence", [f["kind"] for f in body["alibi_findings"]] == ["EVIDENCE"])
sent = requests.get("http://127.0.0.1:8019/_requests").json()
alibi_prompts = [q["body"]["contents"][0]["parts"][0]["text"] for q in sent
                 if q["body"]["contents"][0]["parts"][0].get("text", "").startswith("ALIBI CHECK")]
check("the speaker line sent to Gemini carries the plate", "plate: MH12 AB 4521" in alibi_prompts[-1])

# Turn 2: own-statement clash
body = post(f"/sessions/{session}/statements", json={"text": TURN2}).json()
check("turn 2 clashes with turn 1", [f["kind"] for f in body["alibi_findings"]] == ["SELF"]
      and body["alibi_findings"][0]["source"]["turn_index"] == 0)

# Turn 3: vehicle clash with evidence + generated image
body = post(f"/sessions/{session}/statements", json={"text": TURN3}).json()
vehicle = body["claims"][0]
images = [c for c in vehicle["details"]["tool_calls"] if c["name"] == "generate_image"]
check("turn 3 vehicle claim is a CONFLICT", vehicle["status"] == "CONFLICT", vehicle["reason"])
check("turn 3 has a generated image", images and images[0]["result"]["image_url"], images[0]["result"]["image_url"] if images else "")
check("turn 3 clashes with the evidence", [f["kind"] for f in body["alibi_findings"]] == ["EVIDENCE"])

# Images added during the interview: stored and shown, not checked
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
       b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")
r = post(f"/sessions/{session}/attachments", files={"image": ("receipt.png", PNG, "image/png")}, data={"caption": "Fuel receipt"})
upload = r.json()
check("upload an image", r.status_code == 200 and upload["after_turn"] == 3 and upload["caption"] == "Fuel receipt")
check("uploaded image is served", requests.get(API + upload["url"]).content == PNG)
check("non-image upload 415", post(f"/sessions/{session}/attachments", files={"image": ("a.txt", b"hi", "text/plain")}).status_code == 415)
check("history lists the image", requests.get(f"{API}/sessions/{session}").json()["attachments"][0]["id"] == upload["id"])

# Directory counts follow
check("directory counts the interviews", requests.get(f"{API}/cases").json()[0]["interviews"] == 2)

# End, report, .docx
post(f"/sessions/{session}/end")
with open(os.path.join(os.path.dirname(__file__), "alibi_espeak.wav"), "rb") as f:
    check("transcribe on an ended interview 409", post(f"/sessions/{session}/transcribe", files={"audio": ("c.wav", f)}).status_code == 409)
check("docx before report 404", requests.get(f"{API}/sessions/{session}/report.docx").status_code == 404)
report = post(f"/sessions/{session}/report").json()
check("report has the three findings and the image", len(report["alibi_findings"]) == 3 and len(report["attachments"]) == 1)
check("image upload after end 409", post(f"/sessions/{session}/attachments", files={"image": ("r.png", PNG, "image/png")}).status_code == 409)
r = requests.get(f"{API}/sessions/{session}/report.docx")
check("docx served as Word", r.status_code == 200 and "wordprocessingml" in r.headers["content-type"]
      and "attachment" in r.headers["content-disposition"])

handle, path = tempfile.mkstemp(suffix=".docx")
try:
    with os.fdopen(handle, "wb") as out:
        out.write(r.content)
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs) + "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    check("docx has the case, subject and summary", "Shree Lakshmi Jewellers theft" in text
          and "Suresh Deshmukh" in text and "Scripted summary" in text)
    check("docx has findings and claims", "Alibi-check findings (3)" in text and "Got home to Kothrud by 9:50." in text
          and "CONFLICT" in text and "Fuel receipt" in text)
finally:
    os.remove(path)
check("test docx deleted", not os.path.exists(path))
print(f"\nPASS test_09_demo_flow: {passed} checks (Gemini decisions scripted)")
