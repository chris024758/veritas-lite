"""Run labeled timeline evals through the actual local statement API."""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import gc
import json
import math
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from run_selenium_tests import BACKEND, clean_test_data, start, wait_for_server

sys.path.insert(0, str(BACKEND))
import db


LABELS = ("PENDING", "CONSISTENT", "CONFLICT", "FLAGGED")
SCENARIOS = (
    ("Alex Vale", "Alder Workshop", "18:05"),
    ("Lee Arden", "Birch Studio", "18:20"),
    ("Casey Reed", "Cedar Depot", "18:35"),
    ("Drew Holt", "Elm Annex", "19:00"),
    ("Ari Shaw", "Fern Pavilion", "19:15"),
    ("Robin Lane", "Hazel Warehouse", "19:30"),
    ("Jamie Wren", "Juniper Lodge", "20:05"),
    ("Taylor Moss", "Maple Hall", "20:20"),
    ("Morgan Frost", "Oak Gallery", "20:35"),
    ("Sam Rivers", "Willow Market", "21:45"),
)
UNUSABLE_REASONS = (
    "verification did not complete",
    "did not return usable verdicts",
    "gave no verdict for this claim",
)


def fixtures():
    for index, (person, location, clock) in enumerate(SCENARIOS, start=1):
        hour, minute = map(int, clock.split(":"))
        later = (hour * 60 + minute + 35) % (24 * 60)
        later_clock = f"{later // 60:02}:{later % 60:02}"
        record_context = f"At {location}, the access record for {person}"
        records = (
            None,
            f"{record_context} confirms they were inside at {clock}.",
            f"{record_context} is complete and shows they were absent at {clock}. "
            f"Their first entry was at {later_clock}.",
            f"A witness at {location} remembers {person} arriving around {later_clock}. "
            "The witness had no clock and does not know their exact arrival time.",
        )
        for expected, record in zip(LABELS, records):
            # Matched sets vary only the evidence, so a guess from wording cannot score well.
            yield {"id": f"EVAL-{index:02}-{expected}", "person": person, "location": location,
                   "clock": clock, "statement": f"I was inside {location} at {clock}.",
                   "expected": expected, "record": record}


def seed_fixtures(path, cases):
    original_path = db.DB_PATH
    db.DB_PATH = path
    try:
        db.init_db()
        with closing(db.connect()) as connection, connection:
            for case in cases:
                connection.execute("INSERT INTO cases (id, name) VALUES (?, ?)",
                                   (case["id"], "Fictional timeline evaluation"))
                connection.execute("INSERT INTO subjects (case_id, full_name, role) VALUES (?, ?, ?)",
                                   (case["id"], case["person"], "Witness"))
                if case["record"]:
                    db.add_evidence(case["id"], "activity_record", case["record"], {},
                                    source="seed", connection=connection)
    finally:
        db.DB_PATH = original_path


def post(url, body, timeout):
    data = json.dumps(body).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def score_trial(case, result, elapsed):
    claims = result["claims"]
    for claim in claims:
        entities = claim.get("entities", {})
        claim["matches_reference"] = (
            claim.get("claim_type") == "TIMELINE"
            and entities.get("time_start") == case["clock"]
            and str(entities.get("location", "")).strip().casefold() == case["location"].casefold()
            and entities.get("time_approx") is not True
        )
    matching = next((claim for claim in claims if claim["matches_reference"]), None)
    failures = [] if claims else ["no_claims"]
    for claim in claims:
        reason = (claim.get("reason") or "").casefold()
        if any(marker in reason for marker in UNUSABLE_REASONS):
            failures.append("unusable_verification")
            break
    failures.extend(key for key in ("alibi_error", "followup_error") if result.get(key))
    verdict = matching.get("status") if matching else "MISSING"
    # Missing claims and unusable outputs count as failed verdicts in the end-to-end score.
    scored = verdict if verdict in LABELS and "unusable_verification" not in failures else "MISSING"
    unsupported = sum(claim.get("status") == "CONFLICT" and
                      (case["expected"] != "CONFLICT" or claim is not matching) for claim in claims)
    return {"elapsed_seconds": elapsed, "claims": claims, "extraction_match": matching is not None,
            "verdict": verdict, "scored_verdict": scored, "stage_failures": failures,
            "unsupported_conflict_claims": unsupported,
            "statement_verifier_calls": max((claim.get("details", {}).get("statement_model_calls", 0)
                                             for claim in claims), default=0),
            "grounding_review": None}


def trial(base_url, case, timeout):
    started = None
    try:
        session = post(base_url + "/sessions/start",
                       {"case_id": case["id"], "subject_name": case["person"]}, 15)
        started = time.perf_counter()
        result = post(f"{base_url}/sessions/{session['session_id']}/statements",
                      {"text": case["statement"]}, timeout)
        return score_trial(case, result, time.perf_counter() - started)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        # Keep the scorecard useful without logging raw provider error payloads.
        label = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
        return {"elapsed_seconds": time.perf_counter() - started if started is not None else None,
                "claims": [], "extraction_match": False, "verdict": "MISSING",
                "scored_verdict": "MISSING", "stage_failures": [label],
                "unsupported_conflict_claims": 0, "statement_verifier_calls": 0,
                "grounding_review": None}


def fraction(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def summarize(rows):
    matrix = {label: dict.fromkeys((*LABELS, "MISSING"), 0) for label in LABELS}
    repeats = defaultdict(list)
    for row in rows:
        matrix[row["expected"]][row["scored_verdict"]] += 1
        repeats[row["id"]].append(row["scored_verdict"])
    scores = []
    for label in LABELS:
        actual = sum(counts[label] for counts in matrix.values())
        expected = sum(matrix[label].values())
        if expected:
            scores.append(2 * matrix[label][label] / (expected + actual))
    matched = sum(row["extraction_match"] for row in rows)
    predicted = sum(len(row["claims"]) for row in rows)
    latencies = sorted(row["elapsed_seconds"] for row in rows
                       if not row["stage_failures"] and row["elapsed_seconds"] is not None)
    repeated = [values for values in repeats.values() if len(values) > 1]
    negative = [row for row in rows if row["expected"] != "CONFLICT" and not row["stage_failures"]]
    return {"trials": len(rows), "extraction_precision": fraction(matched, predicted),
            "extraction_recall": fraction(matched, len(rows)),
            "extraction_f1": fraction(2 * matched, predicted + len(rows)),
            "verdict_accuracy": fraction(sum(matrix[label][label] for label in LABELS), len(rows)),
            "verdict_macro_f1": fraction(sum(scores), len(scores)), "confusion_matrix": matrix,
            "pipeline_success_rate": fraction(sum(not row["stage_failures"] for row in rows), len(rows)),
            "repeat_verdict_agreement": fraction(sum(len(set(values)) == 1 and values[0] != "MISSING"
                                                     for values in repeated), len(repeated)),
            "unsupported_conflict_claims": sum(row["unsupported_conflict_claims"] for row in rows),
            "false_conflict_rate": fraction(sum(bool(row["unsupported_conflict_claims"])
                                                for row in negative), len(negative)),
            "latency_samples": len(latencies),
            "p50_seconds": round(latencies[math.ceil(.50 * len(latencies)) - 1], 3) if latencies else None,
            "p95_seconds": round(latencies[math.ceil(.95 * len(latencies)) - 1], 3) if latencies else None,
            "statement_verifier_calls_mean": fraction(sum(row["statement_verifier_calls"] for row in rows), len(rows)),
            "stage_failure_counts": dict(Counter(failure for row in rows for failure in row["stage_failures"])),
            "grounding_review_needed": sum(bool(row["claims"]) for row in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Opt in to real provider calls.")
    parser.add_argument("--limit", type=int, default=4, help="Number of cases to run, up to 40.")
    parser.add_argument("--repeat", type=int, default=1, help="Fresh interviews per case.")
    parser.add_argument("--timeout", type=float, default=180, help="Seconds per statement request.")
    parser.add_argument("--output", type=Path, help="Path for a new JSON scorecard.")
    parser.add_argument("--label", help="Record the model or prompt version being evaluated.")
    args = parser.parse_args()
    if not 1 <= args.limit <= 40 or args.repeat < 1 or args.timeout <= 0:
        parser.error("Use --limit 1 to 40, --repeat at least 1, and a positive --timeout.")
    if args.output and args.output.exists():
        parser.error("--output must be a new file.")
    cases = list(fixtures())[:args.limit]
    with ExitStack() as stack:
        directory = tempfile.TemporaryDirectory(prefix="veritas-eval-")
        stack.callback(clean_test_data, directory)
        # SQLite transaction contexts can leave handles to collect before Windows removes the file.
        stack.callback(gc.collect)
        data = Path(directory.name)
        database = data / "eval.db"
        seed_fixtures(database, cases)
        if not args.live:
            print(json.dumps(cases, indent=2))
            return 0
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"
        env = dict(os.environ, VERITAS_DB=str(database), VERITAS_UPLOADS=str(data / "uploads"))
        log = data / "api.log"
        process = start(stack, [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                                "--port", str(port)], BACKEND, env, log)
        wait_for_server(process, f"{base_url}/cases/{cases[0]['id']}", log)
        rows = []
        for run in range(1, args.repeat + 1):
            for case in cases:
                row = {**case, "run": run, **trial(base_url, case, args.timeout)}
                rows.append(row)
                outcome = ", ".join(row["stage_failures"]) or row["scored_verdict"]
                print(f"{case['id']} run {run}: {outcome}", flush=True)
    metrics = summarize(rows)
    print(json.dumps(metrics, indent=2))
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            json.dump({"created_at": datetime.now(timezone.utc).isoformat(), "label": args.label, "metrics": metrics,
                       "trials": rows}, output, indent=2)
            output.write("\n")
    return 0 if not metrics["stage_failure_counts"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, URLError, RuntimeError) as exc:
        print(f"Eval setup failed: {exc}", file=sys.stderr)
        sys.exit(2)
