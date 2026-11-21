"""TEST DOUBLE for the Gemini HTTP API. The real google-genai SDK talks to this through
GOOGLE_GEMINI_BASE_URL, so request building and response parsing are real. The model's
DECISIONS are scripted here: passing against this proves everything except Gemini's judgement.

Verdicts are computed from the real tool results sent back to it, not canned."""
import base64
import json
import re
import struct
import zlib

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
requests_seen: list[dict] = []
fired_once: set[str] = set()
clip_path: str | None = None

ALIBI_CLAIMS = [
    {"claim_type": "TIMELINE", "text": "Was at a cousin's housewarming in Hadapsar.",
     "entities": {"location": "Hadapsar"}},
    {"claim_type": "ROUTE", "text": "Rode from Hadapsar to the shop, leaving around 9 and reaching around 9:40.",
     "entities": {"origin": "Hadapsar", "destination": "the shop", "claimed_minutes": 40,
                  "time_start": "21:00", "time_end": "21:40", "time_approx": True}},
    {"claim_type": "ROUTE", "text": "Went from the shop to home in Kothrud between 9:40 and 9:50.",
     "entities": {"origin": "the shop", "destination": "Kothrud", "claimed_minutes": 10,
                  "time_start": "21:40", "time_end": "21:50"}},
    {"claim_type": "TIMELINE", "text": "Got home to Kothrud by 9:50.",
     "entities": {"location": "Kothrud", "time": "9:50", "time_start": "21:50"}},
]
# The demo's second turn: the subject moves their own arrival time.
SHIFT_CLAIMS = [
    {"claim_type": "TIMELINE", "text": "Got home to Kothrud around 10:30.",
     "entities": {"location": "Kothrud", "time": "10:30", "time_start": "22:30", "time_approx": True}},
]
UNRELATED_CLAIMS = [
    {"claim_type": "ROUTE", "text": "Took a train from Mysuru to Bengaluru between 7:15 and 9:45.",
     "entities": {"origin": "Mysuru", "destination": "Bengaluru", "claimed_minutes": 150}},
    {"claim_type": "LOCATION", "text": "Had lunch at MTR on Lalbagh Road.",
     "entities": {"location": "MTR, Lalbagh Road"}},
    {"claim_type": "VEHICLE", "text": "Saw a red Maruti van outside.",
     "entities": {"vehicle": "red Maruti van"}},
]
# The demo's optional third turn: the subject says the scooter never left home.
PARKED_CLAIMS = [
    {"claim_type": "VEHICLE", "text": "The white Activa was parked at home in Kothrud all night.",
     "entities": {"vehicle": "white Activa", "location": "home, Kothrud", "time": "all night",
                  "time_start": "21:00", "time_end": "23:59", "time_approx": True}},
]
PLACE_ALIASES ={"Hadapsar": "Hadapsar, Pune", "Kothrud": "Kothrud, Pune"}


def _ok(parts: list[dict], **extra) -> JSONResponse:
    candidate = {"content": {"role": "model", "parts": parts}, "finishReason": "STOP", **extra}
    return JSONResponse({"candidates": [candidate]})


def _error(code: int, status: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "status": status, "message": message}}, status_code=code)


def _png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    size = 64
    raw = b"".join(b"\x00" + bytes((96, 130, 170)) * size for _ in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _extraction(body: dict) -> JSONResponse:
    prompt = body["contents"][0]["parts"][0]["text"]
    config = body.get("generationConfig", {})
    if config.get("responseMimeType") != "application/json" or not (
        config.get("responseSchema") or config.get("responseJsonSchema")
    ):
        return _error(400, "INVALID_ARGUMENT", "extraction must request a JSON schema")
    statement = prompt.rsplit("Statement:\n", 1)[-1]

    if "TRIGGER_EXTRACT_400" in statement:
        return _error(400, "INVALID_ARGUMENT", "scripted bad request")
    if "TRIGGER_429" in statement and statement not in fired_once:
        fired_once.add(statement)
        return _error(429, "RESOURCE_EXHAUSTED", "scripted rate limit")
    if "TRIGGER_MALFORMED" in statement:
        return _ok([{"text": "this is not json"}])

    lowered = statement.lower()
    if "don't remember" in lowered or "do not remember" in lowered:
        claims = []
    elif "housewarming" in lowered:
        claims = ALIBI_CLAIMS
    elif "10:30" in lowered:
        claims = SHIFT_CLAIMS
    elif "parked" in lowered:
        claims = PARKED_CLAIMS
    elif "mysuru" in lowered:
        claims = UNRELATED_CLAIMS
    else:
        claims = [{"claim_type": "OTHER", "text": statement.strip(), "entities": {}}]
    return _ok([{"text": json.dumps({"claims": claims})}])


def _resolve(place: str, case: dict | None) -> str:
    if place.lower().startswith(("the ", "my ")) and case:
        return case["location"]
    return PLACE_ALIASES.get(place, place)


def _minutes_pm(clock: str) -> int:
    hours, minutes = map(int, clock.split(":"))
    return (hours + 12 if hours < 12 else hours) * 60 + minutes


def _plan(claim_type: str, claim_text: str, entities: dict, case_id: str, speaker: str, results: list) -> dict:
    """Next step for this claim: {"call": (name, args)} or {"verdict": (status, reason)}."""
    search = lambda q: ("search_case_file", {"query": q, "case_id": case_id})

    if claim_type == "ROUTE":
        if not results:
            return {"call": search(f"{entities['origin']} {entities['destination']}")}
        if len(results) == 1:
            case = results[0].get("case")
            return {"call": ("check_route", {
                "origin": _resolve(entities["origin"], case),
                "destination": _resolve(entities["destination"], case),
                "claimed_minutes": entities["claimed_minutes"],
            })}
        route = results[-1]
        if "error" in route:
            return {"verdict": ("PENDING", f"Route check failed: {route['error']}")}
        numbers = f"actual {route['actual_minutes']} min vs claimed {route['claimed_minutes']} min"
        if route["assumed_speed_kmh"]:
            numbers += f" at an assumed {route['assumed_speed_kmh']:.0f} km/h"
        if route["exceeds_tolerance"]:
            return {"verdict": ("FLAGGED", f"Route too short for the claimed time: {numbers}.")}
        return {"verdict": ("CONSISTENT", f"Claimed time is plausible: {numbers}.")}

    if claim_type == "TIMELINE":
        if not results:
            return {"call": search(speaker.split(" (")[0])}
        clock = entities.get("time")
        for item in results[0].get("evidence", []):
            when = item["metadata"].get("time")
            if clock and when and _minutes_pm(when) > _minutes_pm(clock):
                return {"verdict": ("CONFLICT", (
                    f"{item['evidence_type']} places a matching person and vehicle at "
                    f"{item['metadata'].get('location')} at {when}, after the claimed {clock}."
                ))}
        return {"verdict": ("PENDING", "No case record establishes this either way.")}

    if claim_type == "LOCATION":
        if not results:
            return {"call": ("web_search", {"query": f"Is {entities.get('location')} real?"})}
        if results[0].get("sources"):
            return {"verdict": ("CONSISTENT", f"Web search: {results[0]['answer']}")}
        return {"verdict": ("PENDING", "Web search returned nothing useful.")}

    if claim_type == "VEHICLE":
        if not results:
            return {"call": search(entities.get("vehicle", ""))}
        if len(results) == 1:
            return {"call": ("generate_image", {"description": entities.get("vehicle", claim_text)})}
        where = (entities.get("location") or "").lower()
        for item in results[0].get("evidence", []):
            seen_at = (item["metadata"].get("location") or "").lower()
            if where and seen_at and "kothrud" not in seen_at and item["metadata"].get("vehicle_descriptor"):
                return {"verdict": ("CONFLICT", (
                    f"{item['evidence_type']} places a matching {item['metadata']['vehicle_descriptor']} "
                    f"at {item['metadata']['location']} at {item['metadata'].get('time')}."))}
        return {"verdict": ("PENDING", "No case record mentions this vehicle.")}

    if not results:
        return {"call": search(claim_text)}
    found = results[0].get("evidence") or results[0].get("subjects")
    return {"verdict": ("FLAGGED", "Partly matches a case record.") if found
            else ("PENDING", "No case record establishes this either way.")}


def _verification(body: dict) -> JSONResponse:
    declared = {d["name"] for t in body["tools"] for d in t.get("functionDeclarations", [])}
    if declared != {"search_case_file", "check_route", "web_search", "generate_image"}:
        return _error(400, "INVALID_ARGUMENT", f"wrong tool set: {declared}")
    for declaration in (d for t in body["tools"] for d in t["functionDeclarations"]):
        if not declaration.get("parameters"):
            return _error(400, "INVALID_ARGUMENT", f"no parameters on {declaration['name']}")

    # Same rule as the real API: every function call answered by a response, in order.
    contents = body["contents"]
    results = []
    for i, turn in enumerate(contents):
        calls = [p["functionCall"]["name"] for p in turn["parts"] if "functionCall" in p]
        if not calls:
            continue
        following = contents[i + 1]["parts"] if i + 1 < len(contents) else []
        answers = [p["functionResponse"] for p in following if "functionResponse" in p]
        if [a["name"] for a in answers] != calls:
            return _error(400, "INVALID_ARGUMENT", "function call without a matching response")
        results.extend(a["response"]["result"] for a in answers)

    prompt = contents[0]["parts"][0]["text"]
    case_id = re.search(r"Case ID: (.*)", prompt).group(1)
    speaker = re.search(r"Speaker: (.*)", prompt).group(1)
    claims = {
        int(number): (claim_type, text, json.loads(entities))
        for number, claim_type, text, entities in re.findall(
            r"^\[(\d+)\] \((\w+)\) (.*?) \| entities: (\{.*\})$", prompt, re.MULTILINE)
    }
    if not claims:
        return _error(400, "INVALID_ARGUMENT", "no numbered claims in the prompt")
    if any("TRIGGER_VERIFY_400" in text for _, text, _ in claims.values()):
        return _error(400, "INVALID_ARGUMENT", "scripted verification failure")

    def step(number: int, results: list) -> dict:
        claim_type, text, entities = claims[number]
        for trigger, call in (("TRIGGER_BAD_ARGS", ("check_route", {})),
                              ("TRIGGER_UNKNOWN_TOOL", ("delete_everything", {}))):
            if trigger in text:
                return {"call": call} if not results else {"verdict": ("PENDING", f"Tool said: {results[0]['error']}")}
        return _plan(claim_type, text, entities, case_id, speaker, results)

    # Replay the conversation: each round, every unfinished claim made one call, in claim order.
    results = {number: [] for number in claims}
    cited = {number: [] for number in claims}
    turns = [t for t in contents if any("functionCall" in p for p in t["parts"])]
    answer_turns = [t for t in contents if any("functionResponse" in p for p in t["parts"])]
    for answers in answer_turns[:len(turns)]:
        waiting = [n for n in sorted(claims) if "call" in step(n, results[n])]
        responses = [p["functionResponse"]["response"] for p in answers["parts"] if "functionResponse" in p]
        if len(responses) != len(waiting):
            return _error(400, "INVALID_ARGUMENT", "replay mismatch")
        for number, response in zip(waiting, responses):
            results[number].append(response["result"])
            cited[number].append(response["call_id"])

    mode = body.get("toolConfig", {}).get("functionCallingConfig", {}).get("mode")
    prose = [n for n, (_, text, _) in claims.items() if "TRIGGER_PROSE" in text]
    if prose and mode != "NONE":
        return _ok([{"text": "It all looks fine to me."}])

    steps = {n: step(n, results[n]) for n in sorted(claims)}
    if mode != "NONE" and not prose:
        calls = [{"functionCall": {"name": s["call"][0], "args": s["call"][1]}} for s in steps.values() if "call" in s]
        if calls:
            return _ok(calls)

    verdicts = []
    for number, s in steps.items():
        if number in prose:
            status, reason = "PENDING", "Verdict from the tools-off retry."
        else:
            status, reason = s.get("verdict", ("PENDING", "Ran out of tool rounds."))
        verdicts.append({"claim": number, "status": status, "reason": reason, "evidence_calls": cited[number]})
    return _ok([{"text": json.dumps({"verdicts": verdicts})}])


def _json_request(body: dict) -> bool:
    config = body.get("generationConfig", {})
    return config.get("responseMimeType") == "application/json" and bool(
        config.get("responseSchema") or config.get("responseJsonSchema"))


def _clock(entities: dict) -> int | None:
    value = entities.get("time_start") or entities.get("time")
    return _minutes_pm(value) if value and ":" in value else None


def _alibi(prompt: str) -> JSONResponse:
    """Scripted alibi check. A new claim with a place and a time clashes with: the same
    speaker's earlier claim about the same place at another time (SELF); another person's
    claim placing a vehicle somewhere else within the hour after it; or a record doing so."""
    if "TRIGGER_ALIBI_400" in prompt:
        return _error(400, "INVALID_ARGUMENT", "scripted alibi-check failure")
    speaker = re.search(r"^Speaker: (.*?) \(", prompt, re.MULTILINE).group(1)
    new = re.findall(r"^\[(\d+)\] \((\w+)\) (.*?) \| entities: (\{.*\})$", prompt, re.MULTILINE)
    earlier = re.findall(r"^(C\d+) \| (.*?) \((\w+)\), turn \d+ \| \((\w+)\) (.*?) \| entities: (\{.*\})$",
                         prompt, re.MULTILINE)
    records = re.findall(r"^(E\d+) \| (\w+) \| (.*?) \| metadata: (\{.*\})$", prompt, re.MULTILINE)
    findings = []
    for number, _, text, raw in new:
        entities = json.loads(raw)
        when, where = _clock(entities), (entities.get("location") or "").lower()
        if when is None or not where:
            continue
        for ref, who, _, _, other_text, other_raw in earlier:
            other = json.loads(other_raw)
            other_when, other_where = _clock(other), (other.get("location") or "").lower()
            if other_when is None or not other_where:
                continue
            if who == speaker and other_where == where and abs(other_when - when) > 10:
                findings.append({"claim": int(number), "source": ref, "severity": "HIGH",
                                 "explanation": f"Earlier the speaker put this at {other['time_start']}, now at {entities['time_start']}.",
                                 "new_quote": entities.get("time"), "prior_quote": other.get("time")})
            elif who != speaker and other.get("vehicle") and other_where != where and 0 < other_when - when <= 60:
                findings.append({"claim": int(number), "source": ref, "severity": "HIGH",
                                 "explanation": f"{who} saw a {other['vehicle']} at {other['location']} at {other['time_start']}, after the claimed time.",
                                 "new_quote": entities.get("time"), "prior_quote": other.get("time")})
        for ref, kind, _, meta_raw in records:
            meta = json.loads(meta_raw)
            if entities.get("vehicle") and meta.get("vehicle_descriptor") and meta.get("location"):
                # The speaker's vehicle placed elsewhere during the span they claim for it.
                end = _minutes_pm(entities["time_end"]) if entities.get("time_end") else when
                if meta.get("time") and when <= _minutes_pm(meta["time"]) <= end:
                    findings.append({"claim": int(number), "source": ref, "severity": "HIGH",
                                     "explanation": f"{kind} places a matching {meta['vehicle_descriptor']} at {meta['location']} at {meta['time']}.",
                                     "new_quote": "parked at home", "prior_quote": meta["time"]})
                continue
            if meta.get("time") and meta.get("location") and 0 < _minutes_pm(meta["time"]) - when <= 60:
                findings.append({"claim": int(number), "source": ref, "severity": "HIGH",
                                 "explanation": f"{kind} places a matching person and vehicle at {meta['location']} at {meta['time']}.",
                                 "new_quote": entities.get("time"), "prior_quote": meta["time"]})
    return _ok([{"text": json.dumps({"findings": findings})}])


def _followups(prompt: str) -> JSONResponse:
    claims = dict(re.findall(r"^\[(\d+)\] \w+ \(\w+\) (.*?) \| reason:", prompt, re.MULTILINE))
    doubtful = re.findall(r"^\[(\d+)\] (?:FLAGGED|CONFLICT) ", prompt, re.MULTILINE)
    from_findings = list(dict.fromkeys(re.findall(r"^- claim \[(\d+)\]", prompt, re.MULTILINE)))
    questions = [{"question": f"Who can confirm this: \"{claims[n]}\"?", "claims": [int(n)],
                  "rationale": "It clashes with another account.", "from_finding": True} for n in from_findings]
    questions += [{"question": f"Can you go over this again: \"{claims[n]}\"?", "claims": [int(n)],
                   "rationale": "The check left it doubtful.", "from_finding": False}
                  for n in doubtful if n not in from_findings]
    return _ok([{"text": json.dumps({"questions": questions})}])


def _report(prompt: str) -> JSONResponse:
    if "TRIGGER_REPORT_400" in prompt:
        return _error(400, "INVALID_ARGUMENT", "scripted report failure")
    findings = len(re.findall(r"^- (SELF|WITNESS|EVIDENCE) ", prompt, re.MULTILINE))
    turns = len(re.findall(r"^T\d+: ", prompt, re.MULTILINE))
    return _ok([{"text": json.dumps({
        "overview": f"Scripted summary of {turns} turns with {findings} alibi-check findings.",
        "key_findings": [f"{findings} alibi-check findings"], "unresolved": ["Scripted item"],
        "next_steps": ["Scripted next step"],
    })}])


@app.post("/{version}/models/{model}:generateContent")
async def generate(version: str, model: str, request: Request):
    body = await request.json()
    requests_seen.append({"model": model, "body": body})
    tools = body.get("tools", [])

    if "image" in model:
        data = base64.b64encode(_png()).decode()
        return _ok([{"inlineData": {"mimeType": "image/png", "data": data}}])
    if any("googleSearch" in t for t in tools):
        return _ok(
            [{"text": "Yes, it is a long-established restaurant at that address (scripted)."}],
            groundingMetadata={"groundingChunks": [
                {"web": {"uri": "https://example.com/source", "title": "example.com"}}
            ]},
        )
    if any("functionDeclarations" in t for t in tools):
        return _verification(body)
    prompt = body["contents"][0]["parts"][0]["text"]
    for marker, handler in (("ALIBI CHECK", _alibi), ("FOLLOW-UP QUESTIONS", _followups), ("INTERVIEW REPORT", _report)):
        if prompt.startswith(marker):
            if not _json_request(body):
                return _error(400, "INVALID_ARGUMENT", f"{marker} must request a JSON schema")
            return handler(prompt)
    return _extraction(body)


@app.get("/_requests")
def seen():
    return requests_seen


@app.get("/_clip")
def clip():
    """Serves a spoken WAV so the UI's recorder can be fed real speech in the browser test."""
    return FileResponse(clip_path, media_type="audio/wav")
