"""check_route (live Nominatim/OSRM), search_case_file (seeded data), and the Gemini-backed
tools (live if GEMINI_API_KEY is set; otherwise only their no-key failure path)."""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["VERITAS_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import db
import gemini_client
import seed
from tools import routing
from tools.case_file import search_case_file
from tools.image_gen import generate_image
from tools.web_search import web_search

seed.seed()
CASE = "2026-PUN-0219"


def show(label, value):
    print(f"\n--- {label}")
    print(json.dumps(value, indent=1, ensure_ascii=False))


# check_route: the named test case
r = routing.check_route("Shree Lakshmi Jewellers, FC Road, Pune", "Kothrud, Pune", 10)
show("check_route shop -> Kothrud, claimed 10", r)
assert r["source"] == "osrm" and r["origin_matched"] == "FC Road, Pune"
assert r["osrm_minutes"] > 0 and r["actual_minutes"] > 0
assert r["exceeds_tolerance"] is True

r2 = routing.check_route("Shree Lakshmi Jewellers, FC Road, Pune", "Kothrud, Pune", 10)
print("\nsecond call source (cache):", r2["source"], "| same actual:", r2["actual_minutes"] == r["actual_minutes"])
assert r2["source"] == "osrm_cached" and r2["actual_minutes"] == r["actual_minutes"]

# non-hardcoded: a different route must give a different number
r3 = routing.check_route("Hadapsar, Pune", "FC Road, Pune", 40)
show("check_route Hadapsar -> FC Road, claimed 40", r3)
assert r3["actual_minutes"] != r["actual_minutes"]

r4 = routing.check_route("Mysuru Palace, Mysuru", "Lalbagh, Bengaluru", 30)
show("check_route unrelated cities, claimed 30", r4)
assert r4["distance_km"] > 100 and r4["exceeds_tolerance"] is True
assert r4["assumed_speed_kmh"] is None and r4["actual_minutes"] == r4["osrm_minutes"]
r4b = routing.check_route("Mysuru", "Bengaluru", 150)
show("check_route bare city names, claimed 150", r4b)
assert "error" not in r4b and r4b["exceeds_tolerance"] is False

r5 = routing.check_route("the shop", "Kothrud, Pune", 10)
show("check_route with an unresolvable place", r5)
assert "error" in r5

# straight-line fallback when OSRM is unreachable
real_url = routing.OSRM_URL
routing.OSRM_URL = "http://127.0.0.1:9/route/{a};{b}"
with db.connect() as c:
    c.execute("DELETE FROM geo_cache WHERE key LIKE 'route:%'")
r6 = routing.check_route("FC Road, Pune", "Kothrud, Pune", 10)
show("check_route with OSRM down", r6)
assert r6["source"] == "straight_line_fallback" and r6["osrm_minutes"] is None
routing.OSRM_URL = real_url

# search_case_file
s = search_case_file("Suresh Deshmukh", CASE)
print("\nSuresh ->", [x["full_name"] for x in s["subjects"]], [e["evidence_type"] for e in s["evidence"]])
assert "witness_statement" in [e["evidence_type"] for e in s["evidence"]]

s = search_case_file("white scooter near rear shutter", CASE)
print("scooter ->", [e["evidence_type"] for e in s["evidence"]])
assert "witness_statement" in [e["evidence_type"] for e in s["evidence"]]

s = search_case_file("MH124521", CASE)
s2 = search_case_file("MH12 AB 4521", CASE)
print("plate ->", [x["full_name"] for x in s2["subjects"]], [e["evidence_type"] for e in s2["evidence"]])
assert s2["evidence"] and s2["subjects"]

s = search_case_file("10:15", CASE)
print("10:15 ->", [e["evidence_type"] for e in s["evidence"]])
assert [e["evidence_type"] for e in s["evidence"]] == ["witness_statement"]

s = search_case_file("Anita Rao Mysuru train", CASE)
print("unrelated ->", s["subjects"], s["evidence"], s["prior_statements"])
assert not s["subjects"] and not s["evidence"]

# prior turns are searchable, the statement being verified is not
session = db.create_session(CASE, "Suresh Deshmukh")
stmt = db.add_statement(session["id"], "I parked at Hadapsar")
assert search_case_file("Hadapsar", CASE)["prior_statements"]
assert not search_case_file("Hadapsar", CASE, exclude_statement_id=stmt["id"])["prior_statements"]
print("prior statement searchable; current statement excluded")

# Gemini-backed tools
if gemini_client.has_key():
    w = web_search("Is MTR on Lalbagh Road in Bengaluru a real restaurant?")
    show("web_search (live grounding)", w)
    assert w["answer"] and w["sources"]
    i = generate_image("a white scooter parked near a shop's rear shutter at night")
    show("generate_image (live)", i)
    print("PASS test_03_tools (live)")
else:
    w = web_search("x")
    i = generate_image("a white scooter")
    print("\nno key -> web_search:", w, "\nno key -> generate_image:", i)
    assert w["error"] and i["placeholder"] is True
    print("PASS test_03_tools (Gemini-backed tools NOT exercised live: no key)")
