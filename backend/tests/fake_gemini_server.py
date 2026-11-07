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
     "entities": {"origin": "Hadapsar", "destination": "the shop", "claimed_minutes": 40}},
    {"claim_type": "ROUTE", "text": "Went from the shop to home in Kothrud between 9:40 and 9:50.",
     "entities": {"origin": "the shop", "destination": "Kothrud", "claimed_minutes": 10}},
    {"claim_type": "TIMELINE", "text": "Got home to Kothrud by 9:50.",
     "entities": {"location": "Kothrud", "time": "9:50"}},
]
UNRELATED_CLAIMS = [
    {"claim_type": "ROUTE", "text": "Took a train from Mysuru to Bengaluru between 7:15 and 9:45.",
     "entities": {"origin": "Mysuru", "destination": "Bengaluru", "claimed_minutes": 150}},
    {"claim_type": "LOCATION", "text": "Had lunch at MTR on Lalbagh Road.",
     "entities": {"location": "MTR, Lalbagh Road"}},
    {"claim_type": "VEHICLE", "text": "Saw a red Maruti van outside.",
     "entities": {"vehicle": "red Maruti van"}},
]
PLACE_ALIASES = {"Hadapsar": "Hadapsar, Pune", "Kothrud": "Kothrud, Pune"}


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
    claim_type, claim_text = re.search(r"Claim to verify \((\w+)\): (.*)", prompt).groups()
    entities = json.loads(re.search(r"Extracted entities: (.*)", prompt).group(1))

    if "TRIGGER_VERIFY_400" in claim_text:
        return _error(400, "INVALID_ARGUMENT", "scripted verification failure")
    mode = body.get("toolConfig", {}).get("functionCallingConfig", {}).get("mode")
    if "TRIGGER_PROSE" in claim_text:
        if mode == "NONE":
            return _ok([{"text": json.dumps({"status": "PENDING", "reason": "Verdict from the tools-off retry."})}])
        return _ok([{"text": "It looks fine to me."}])
    if "TRIGGER_BAD_ARGS" in claim_text and not results:
        return _ok([{"functionCall": {"name": "check_route", "args": {"origin": "only origin"[:0]}}}])
    if "TRIGGER_UNKNOWN_TOOL" in claim_text and not results:
        return _ok([{"functionCall": {"name": "delete_everything", "args": {}}}])
    if "TRIGGER_BAD_ARGS" in claim_text or "TRIGGER_UNKNOWN_TOOL" in claim_text:
        return _ok([{"text": json.dumps({"status": "PENDING", "reason": f"Tool said: {results[0]['error']}"})}])

    step = _plan(claim_type, claim_text, entities, case_id, speaker, results)
    if "verdict" in step:
        status, reason = step["verdict"]
        return _ok([{"text": json.dumps({"status": status, "reason": reason})}])
    name, args = step["call"]
    return _ok([{"functionCall": {"name": name, "args": args}}])


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
    return _extraction(body)


@app.get("/_requests")
def seen():
    return requests_seen


@app.get("/_clip")
def clip():
    """Serves a spoken WAV so the UI's recorder can be fed real speech in the browser test."""
    return FileResponse(clip_path, media_type="audio/wav")
