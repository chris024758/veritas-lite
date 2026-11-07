"""db.py + seed.py: exact demo-case data, idempotent seed, status constraint."""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["VERITAS_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import db
import seed

seed.seed()
seed.seed()  # twice: must not duplicate
case = db.get_case("2026-PUN-0219")
print(json.dumps(case, indent=1, ensure_ascii=False))
with db.connect() as c:
    tables = sorted(r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
print("tables/counts:", counts)
assert counts["cases"] == 1 and counts["subjects"] == 2 and counts["evidence"] == 4
assert [s["full_name"] for s in case["subjects"]] == ["Suresh Deshmukh", "Ramesh Kulkarni"]

s = db.create_session("2026-PUN-0219", "suresh deshmukh")
assert s["subject_id"] == case["subjects"][0]["id"]
st = db.add_statement(s["id"], "x")
st2 = db.add_statement(s["id"], "y")
assert (st["turn_index"], st2["turn_index"]) == (0, 1)
cid = db.add_claim(st["id"], "ROUTE", "t", {"origin": "a"})
assert db.get_claims(st["id"])[0]["status"] == "PENDING"
db.finish_claim(cid, "FLAGGED", "r", {"k": 1})
print("claim after finish:", db.get_claims(st["id"])[0])
try:
    db.finish_claim(cid, "BOGUS", "r", {})
    raise SystemExit("bad status accepted")
except ValueError as e:
    print("rejected:", e)
print("PASS test_01_db_seed")
