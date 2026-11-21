"""The final demo, end to end over real HTTP. Needs a FRESH run_fake_stack.py (demo seed, no
interviews). Gemini's decisions are SCRIPTED; everything else is real.

1. Street cleaner (added live): a black SUV -> new case record with an illustration suggestion.
2. Suresh: the maps flag only, no clash with anything seeded.
3. Ramesh: "Suresh didn't come over" -> WITNESS clash; the ticket is filed as evidence
   without comparing it to statements.
Then end -> report -> .docx, written to a temp file, checked, then deleted."""
import os
import sys
import tempfile

import requests
from docx import Document

sys.stdout.reconfigure(encoding="utf-8")
API = "http://localhost:8018"
CASE = "2026-PUN-0219"
CLEANER = ("Around quarter past ten I was sweeping near the jewellers on FC Road. A black SUV was standing in "
           "the back lane with its engine running. It had a big round sticker on the rear glass, a red trident "
           "I think. Two men got in and it drove off towards Shivajinagar.")
SURESH = ("I was at my friend Ramesh's place in Hadapsar till about nine. Then I rode to the shop to check on "
          "things, left at 9:40, and was home in Kothrud by 9:50.")
RAMESH = ("No, Suresh didn't come over that evening. I wasn't even home. I was at the Indian Ocean concert in "
          "Pune on 21 November. Here's my ticket.")
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
       b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")
passed = 0


def check(label, condition, detail=""):
    global passed
    if not condition:
        raise SystemExit(f"FAIL {label}: {detail}")
    passed += 1
    print(f"ok   {label}" + (f"  [{detail}]" if detail else ""))


def post(path, **kwargs):
    return requests.post(f"{API}{path}", timeout=120, **kwargs)


def case_file():
    return requests.get(f"{API}/cases/{CASE}").json()


# Directory and seeded case file
cases = requests.get(f"{API}/cases").json()
check("directory lists the jewellers case and placeholders", [c["id"] for c in cases][0] == CASE and len(cases) == 3)
check("jewellers case starts with no interviews", cases[0]["interviews"] == 0 and cases[0]["people"] == 2)
case = case_file()
check("case has its incident date", case["incident_date"] == "2026-11-21")
check("seed holds on-site records only", [e["evidence_type"] for e in case["evidence"]]
      == ["rear_shutter_lock", "display_cabinet", "insurance_claim", "stolen_items"])
stolen = next(e for e in case["evidence"] if e["evidence_type"] == "stolen_items")
check("stolen items seeded with details and images", len(stolen["items"]) == 4 and all(i["image"] for i in stolen["items"]))
check("illustrations are served", requests.get(API + stolen["image"]).headers["content-type"].startswith("image/svg"))
people = {s["full_name"]: s for s in case["subjects"]}
check("Ramesh is Suresh's friend", people["Ramesh Kulkarni"]["notes"].startswith("Suresh's friend"))

# People
r = post(f"/cases/{CASE}/subjects", json={"full_name": "Ganesh Pawar", "role": "Witness", "notes": "Street cleaner, FC Road"})
cleaner = r.json()
check("add the street cleaner", r.status_code == 200 and cleaner["existing"] is False)
check("duplicate name returns the existing person",
      post(f"/cases/{CASE}/subjects", json={"full_name": "  ramesh kulkarni ", "role": "Witness"}).json()["existing"] is True)
check("bad role 422", post(f"/cases/{CASE}/subjects", json={"full_name": "X", "role": "Boss"}).status_code == 422)
check("start with nobody 422", post("/sessions/start", json={"case_id": CASE}).status_code == 422)

# 1. Street cleaner: the SUV becomes a case record with an illustration suggestion.
s1 = post("/sessions/start", json={"case_id": CASE, "subject_id": cleaner["id"]}).json()["session_id"]
body = post(f"/sessions/{s1}/statements", json={"text": CLEANER}).json()
records = body["new_records"]
check("cleaner's statement adds one case record", len(records) == 1, [r["evidence_type"] for r in records])
suv = records[0]
check("the record is a vehicle sighting from his statement", suv["evidence_type"] == "vehicle_sighting"
      and suv["source"] == "statement" and suv["subject_id"] == cleaner["id"] and suv["session_id"] == s1)
check("the record carries time and place", suv["metadata"]["time"] == "22:15" and "back lane" in suv["metadata"]["location"])
check("the record has a suggested prompt and awaits generation", suv["illustration_prompt"] and suv["image"] is None)
on_file = next(e for e in case_file()["evidence"] if e["id"] == suv["id"])
check("the case file shows who provided it", on_file["provided_by"] == "Ganesh Pawar")
check("no clashes for the cleaner", body["alibi_findings"] == [])
post(f"/sessions/{s1}/end")

# 2. Suresh: the maps flag, nothing else
s2 = post("/sessions/start", json={"case_id": CASE, "subject_id": people["Suresh Deshmukh"]["id"]}).json()["session_id"]
body = post(f"/sessions/{s2}/statements", json={"text": SURESH}).json()
route = next(c for c in body["claims"] if c["entities"].get("claimed_minutes") == 10)
result = route["details"]["tool_calls"][-1]["result"]
check("maps check flags shop -> Kothrud", route["status"] == "FLAGGED" and result["exceeds_tolerance"], route["reason"])
check("maps panel has from, to, distance, minutes, gap",
      all(k in result for k in ("origin", "destination", "distance_km", "actual_minutes", "claimed_minutes", "gap_minutes")))
check("Suresh's interview raises no clash", body["alibi_findings"] == [])
check("a suspect adds no case records", body["new_records"] == [])
at_ramesh = next(c for c in body["claims"] if "Ramesh's place" in c["text"])
post(f"/sessions/{s2}/end")

# 3. Ramesh: the clash with Suresh, then the ticket
s3 = post("/sessions/start", json={"case_id": CASE, "subject_id": people["Ramesh Kulkarni"]["id"]}).json()["session_id"]
body = post(f"/sessions/{s3}/statements", json={"text": RAMESH}).json()
findings = body["alibi_findings"]
check("Ramesh's statement clashes with Suresh's (WITNESS)", [f["kind"] for f in findings] == ["WITNESS"]
      and findings[0]["source"]["id"] == at_ramesh["id"], findings[0]["explanation"] if findings else "")
check("Ramesh adds no case record by speaking", body["new_records"] == [])
status_before_upload = next(c["status"] for c in requests.get(f"{API}/sessions/{s2}").json()["statements"][0]["claims"]
                            if c["id"] == at_ramesh["id"])

r = post(f"/sessions/{s3}/attachments", files={"image": ("ticket.png", PNG, "image/png")}, data={"caption": "Concert ticket"})
upload = r.json()
check("ticket uploaded", r.status_code == 200, r.text)
ticket = upload["evidence"]
check("ticket filed as a record with its photo", ticket["source"] == "upload" and ticket["image_kind"] == "photo"
      and ticket["image"] == upload["url"] and ticket["metadata"]["caption"] == "Concert ticket")
suresh_claim = next(c for c in requests.get(f"{API}/sessions/{s2}").json()["statements"][0]["claims"] if c["id"] == at_ramesh["id"])
check("ticket does not change Suresh's claim status", suresh_claim["status"] == status_before_upload, suresh_claim["reason"])
history = requests.get(f"{API}/sessions/{s3}").json()
check("the upload is linked to its record", history["attachments"][0]["evidence_id"] == ticket["id"])

r = post(f"/sessions/{s3}/attachments", files={"image": ("old.png", PNG, "image/png")})
check("an image without a caption is filed by filename", r.json()["evidence"]["description"] == "old.png")
check("non-image upload 415", post(f"/sessions/{s3}/attachments", files={"image": ("a.txt", b"hi", "text/plain")}).status_code == 415)

# Timeline: the SUV has a time, the ticket is untimed, and only the witness clash is linked.
view = requests.get(f"{API}/cases/{CASE}/timeline").json()
lane = {e["id"]: e for e in view["events"] if e["lane"] == "evidence"}
check("SUV and ticket are on the evidence lane", lane[f"e{suv['id']}"]["start"] == 1335
      and any(e["id"] == f"e{ticket['id']}" and e["lane"] == "evidence" for e in view["untimed"]))
check("only the witness clash is linked", len(view["links"]) == 1 and view["links"][0]["kind"] == "WITNESS")

# Report and .docx for Ramesh's interview
post(f"/sessions/{s3}/end")
check("upload after end 409", post(f"/sessions/{s3}/attachments", files={"image": ("r.png", PNG, "image/png")}).status_code == 409)
report = post(f"/sessions/{s3}/report").json()
check("report has the witness clash and the uploads", len(report["alibi_findings"]) == 1 and len(report["attachments"]) == 2)
r = requests.get(f"{API}/sessions/{s3}/report.docx")
check("docx served as Word", r.status_code == 200 and "wordprocessingml" in r.headers["content-type"])
handle, path = tempfile.mkstemp(suffix=".docx")
try:
    with os.fdopen(handle, "wb") as out:
        out.write(r.content)
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    check("docx has the subject, summary and findings", "Ramesh Kulkarni" in text and "Scripted summary" in text
          and "Alibi-check findings (1)" in text and "Concert ticket" in text)
finally:
    os.remove(path)
check("test docx deleted", not os.path.exists(path))
print(f"\nPASS test_09_demo_flow: {passed} checks (Gemini decisions scripted)")
