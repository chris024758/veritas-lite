# VERITAS-Lite — Build Spec

This document is self-contained. It does not assume you have read the GitHub repo
`chris024758/veritas`, the slide deck, or any prior conversation. Everything needed to
implement this system is below: the exact case data to seed, the exact schema, the exact
tool contracts, the exact API shapes, and the exact build order. Where a decision was made
for a reason, the reason is stated inline so it isn't lost.

## 1. What this is

A minimal, from-scratch reimplementation of "VERITAS" — a system that takes a suspect/witness
statement from an interrogation, extracts factual claims from it, and checks those claims
against a case file and external reality (routes, web facts) using an LLM that calls tools on
its own initiative (Gemini native function calling), not a hand-written if/else dispatcher.

This is explicitly **not** a faithful rebuild of any existing prototype. It uses a new,
simpler demo case (see §3) so that correctness can be verified independently of any
pre-written "expected" answer.

### Core principle
One statement → extract claims → for each claim, an LLM decides which tool(s) to call to
verify it → store the verdict → show it in a UI. The LLM's tool-calling decision is the
verification logic; there is no hardcoded `if claim_type == "ROUTE": call_maps()` dispatch.

## 2. Explicit scope

**In scope:**
- Input via a short recorded audio clip, transcribed to text locally (STT), one clip per
  submission (not continuous/streaming).
- One Gemini call to extract structured claims from the transcribed text.
- A second Gemini call *per claim*, with four tools bound as native function-calling tools:
  `search_case_file`, `check_route`, `web_search`, `generate_image`. The model decides which
  tool(s), if any, to call for that specific claim.
- SQLite storage. No Elasticsearch, no vector index, no BM25 — claim comparison uses
  structured field matching (exact/fuzzy match on names, plates, locations, times extracted
  into typed fields), because the corpus size (one case, a handful of statements) never
  justifies a ranking/retrieval layer.
- One seeded demo case (§3) with exactly 2 named people (one suspect, one witness) plus a
  small evidence list.
- A React single-page frontend: case file panel + statement submission (text or audio) +
  a table of extracted claims with status and reason.
- A FastAPI backend exposing the endpoints in §8.

**Out of scope (do not build):**
- Continuous/live audio streaming (Gemini Live). One clip per turn is sufficient.
- Firestore, Elasticsearch, Arize Phoenix, any hosted vector DB.
- Multi-case support, authentication, deployment/hosting config.
- Document/photo upload analysis (separate from `generate_image`).
- A `check_event` tool (public venue/hours verification) — not needed for this case; do not
  build it unless asked.

## 3. The demo case (seed data)

Case: a jewellery shop theft in Pune, structurally similar to an "owner stages his own
burglary for the insurance payout" pattern, but written fresh for this build — do not search
for or reuse any other case's data.

**Case ID:** `2026-PUN-0219`
**Case name:** Shree Lakshmi Jewellers Theft
**Location:** Shree Lakshmi Jewellers, FC Road, Pune

**Incident narrative (store as a case-file "officer statement," role=OFFICER):**
> Responding to alarm trigger at 22:40 IST. Shree Lakshmi Jewellers, FC Road. Front shutter
> locked, no forced entry. Display cabinet open, no glass damage — opened with a key or pick
> tool. Rear service shutter found unlocked; lock itself undamaged, no scratching. Owner
> Suresh Deshmukh reports ₹3.2 lakh in gold jewellery missing, insurance claim filed same
> night. Owner's registered vehicle on file: white Honda Activa, plate MH12AB4521.

**Subjects (exactly 2 — do not add more):**

| full_name | role | notes |
|---|---|---|
| Suresh Deshmukh | SUSPECT | Shop owner. Has keys to every entry point. Person of interest — no forced entry is suspicious for a "break-in." |
| Ramesh Kulkarni | WITNESS | Runs the paan/cigarette stall next door. Eyewitness. |

**Suresh's alibi statement (the primary test input — feed this exact text to the pipeline
during testing):**
> "I was at my cousin's housewarming in Hadapsar. I left there around 9 PM, rode to the shop
> just to check the locks were okay, got there about 9:40, then went straight home to Kothrud
> — I was home by 9:50."

**Why this should be FLAGGED (do not hardcode this result — it must emerge from the tools):**
- FC Road (the shop) to Kothrud is realistically a 25–30 minute ride by two-wheeler at that
  time of night. Suresh's own timestamps (shop at 9:40, home by 9:50) claim 10 minutes. The
  `check_route` tool, given real geocoded coordinates and a real routing API, will return an
  actual travel time far longer than 10 minutes — that mismatch is the flag, computed live,
  not looked up from a table of "known" answers.

**Ramesh's witness statement (store as a case-file statement, role=WITNESS):**
> "I was closing up around 10:15 PM. Saw a man near the shop's back shutter, loading something
> into a bag on a white scooter. Couldn't see his face clearly, but the scooter looked like
> the one the shop owner rides — I think the plate started with MH12."

**Why this should also FLAG/CONFLICT:** Ramesh's sighting (10:15 PM, near the shop, vehicle
plate partially matching Suresh's registered Activa MH12AB4521) directly contradicts Suresh's
claim to have been home in Kothrud since 9:50 PM. This is a `search_case_file` cross-reference
hit (a claim extracted from Suresh's statement doesn't mention this, but the system should
surface Ramesh's prior statement as case-file context when Suresh's vehicle/location claims
are checked).

**Evidence records (seed these into the `evidence` table):**

| evidence_type | description | metadata |
|---|---|---|
| SCENE | Rear service shutter — lock intact, no scratching, no forced damage | `{"location": "rear shutter"}` |
| SCENE | Display cabinet — opened cleanly, no glass damage | `{"location": "display cabinet"}` |
| WITNESS_SIGHTING | Man near rear shutter loading a bag onto a white scooter, ~22:15 | `{"time": "22:15", "vehicle_color": "white", "vehicle_type": "scooter", "plate_partial": "MH12", "source": "Ramesh Kulkarni"}` |
| VEHICLE_RECORD | Owner's registered vehicle | `{"plate": "MH12AB4521", "color": "white", "type": "Honda Activa", "owner": "Suresh Deshmukh"}` |

**Second test statement — a from-scratch improvised line, used to prove the pipeline is not
hardcoded to Pune.** Do not pre-seed this; it's for the demo itself, invented live. Example to
have ready: *"I was at a cricket match at a stadium across town until it ended, then walked
straight to my friend's place ten minutes away."* This should extract a ROUTE and/or EVENT-ish
claim and get checked the same way, with no special-cased logic for it anywhere in the code.

## 4. Architecture

```
React UI
  → (record or type a statement)
  → POST /sessions/{id}/statements   (text)      OR
  → POST /sessions/{id}/audio        (audio file)
       ↓ [audio only] local STT (faster-whisper, "base" model) → transcript text
       ↓
FastAPI endpoint handler
       ↓
Gemini call #1: extract_claims(text) → list of typed claims
       ↓ (for each claim, sequentially)
Gemini call #2: tool-calling turn, 4 tools bound
   model may call zero, one, or multiple tools before returning a verdict
       ↓
verdict + reason written to SQLite (`claims` table)
       ↓
response JSON returned to UI (all claims + verdicts for this statement)
```

One process. No agent framework, no message queue, no background workers. Everything in
one FastAPI request-response cycle, synchronous from the UI's point of view (it's fine for
this to take a few seconds — there's no requirement to stream partial results for this
build).

## 5. Tech stack

- **Backend:** Python 3.11+, FastAPI, `uvicorn`.
- **LLM:** Google Gemini API (`google-genai` SDK), model: `gemini-2.5-flash` for extraction
  and tool-calling (use whichever current Gemini model supports native function calling and
  Google Search grounding — confirm against current Gemini API docs at build time, model
  names change).
- **STT:** `faster-whisper` (or `openai-whisper`), model size `base`, CPU inference. Runs
  locally, no API key, no network call.
- **Storage:** SQLite via Python's built-in `sqlite3` module (or `sqlmodel`/`sqlalchemy` if
  preferred — no strong requirement either way, but keep it to one file-based DB, no server).
- **Routing/geocoding:** Nominatim (`https://nominatim.openstreetmap.org/search`) for
  geocoding, OSRM public demo server (`https://router.project-osrm.org/route/v1/driving/...`)
  for travel time. Both are free, no API key. **Set a descriptive `User-Agent` header on
  Nominatim requests** — their usage policy requires it and will block requests without one.
  Respect their ~1 request/second rate limit (add a small `time.sleep` or cache geocoded
  coordinates after first lookup).
- **Web search / image generation:** Gemini's own native Google Search grounding tool and
  Gemini's image-generation model — both billed through the same Gemini API key already in
  hand, no separate service or key.
- **Frontend:** React (Vite scaffold), plain `fetch`, no routing library, no state management
  library beyond `useState`/`useEffect`.

## 6. Data model (SQLite DDL)

```sql
CREATE TABLE cases (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE subjects (
    id                      TEXT PRIMARY KEY,
    case_id                 TEXT NOT NULL REFERENCES cases(id),
    full_name               TEXT NOT NULL,
    role                    TEXT NOT NULL,   -- SUSPECT | WITNESS | OFFICER
    notes                   TEXT,
    registered_vehicle_json TEXT             -- JSON: {"plate":..., "color":..., "type":...} or NULL
);

CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,     -- uuid4 string
    case_id     TEXT NOT NULL REFERENCES cases(id),
    subject_id  TEXT REFERENCES subjects(id),
    started_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE statements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    case_id     TEXT NOT NULL REFERENCES cases(id),
    subject_id  TEXT REFERENCES subjects(id),
    role        TEXT,                -- SUSPECT | WITNESS | OFFICER — who is speaking
    turn_index  INTEGER NOT NULL,
    text        TEXT NOT NULL,        -- the statement text (post-STT if audio)
    source      TEXT DEFAULT 'text',  -- 'text' | 'audio'
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE claims (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id    INTEGER NOT NULL REFERENCES statements(id),
    case_id         TEXT NOT NULL REFERENCES cases(id),
    claim_type      TEXT NOT NULL,    -- ROUTE | EVENT | PERSON | TIME | LOCATION | VEHICLE | OTHER
    text            TEXT NOT NULL,    -- exact claim span, as extracted
    entities_json   TEXT,             -- extracted structured fields, e.g. {"origin":..., "destination":..., "claimed_minutes":...}
    status          TEXT DEFAULT 'PENDING',  -- PENDING | CONSISTENT | FLAGGED | CONFLICT
    reason          TEXT,             -- human-readable verdict explanation
    tool_calls_json TEXT,             -- array of {tool, args, result} actually made for this claim — for debugging/demo transparency
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE evidence (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id),
    evidence_type   TEXT NOT NULL,    -- SCENE | WITNESS_SIGHTING | VEHICLE_RECORD
    description     TEXT NOT NULL,
    metadata_json   TEXT              -- JSON blob, shape varies by evidence_type (see §3 table)
);
```

Seed `cases`, `subjects`, and `evidence` from §3 once at startup (a `seed.py` script run
before `uvicorn`, or a startup event in FastAPI — either is fine, but it must be idempotent:
re-running the seed should not create duplicate rows. Easiest approach: `DELETE FROM X WHERE
case_id = '2026-PUN-0219'` then re-insert, same spirit as resetting to a clean demo state
before each run).

## 7. Tool definitions (Gemini native function calling)

These are the four tools bound to the Gemini model during the per-claim verification call.
Define them using the Gemini SDK's function-declaration format (consult the current
`google-genai` SDK docs for exact syntax — the shape below is the logical contract, not
necessarily byte-exact SDK syntax):

### `search_case_file`
```json
{
  "name": "search_case_file",
  "description": "Search this case's prior statements, subjects, and evidence for anything relevant to a claim — names, vehicle plates, locations, prior timestamps. Use this to check if a claim is contradicted by or corroborated by something already on file for this case.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "What to look for, e.g. a name, a vehicle plate, a location, or a short description of the fact to check."}
    },
    "required": ["query"]
  }
}
```
**Implementation:** run a SQL query against `subjects`, `statements`, and `evidence` for the
current `case_id`, matching `query` against relevant text columns with `LIKE '%...%'` (case-
insensitive) plus a fuzzy fallback (Python's `difflib.SequenceMatcher`, threshold ~0.6) for
near-matches (e.g. a partial plate "MH12" matching a full plate "MH12AB4521"). Return the
matching rows' text as a JSON list back to the model as the tool's result.

### `check_route`
```json
{
  "name": "check_route",
  "description": "Check whether a claimed travel time between two places is realistic, using real-world geocoding and routing data.",
  "parameters": {
    "type": "object",
    "properties": {
      "origin": {"type": "string", "description": "Starting place name or address."},
      "destination": {"type": "string", "description": "Ending place name or address."},
      "claimed_minutes": {"type": "number", "description": "How many minutes the subject claimed this took."}
    },
    "required": ["origin", "destination", "claimed_minutes"]
  }
}
```
**Implementation:**
1. Geocode `origin` and `destination` via Nominatim:
   `GET https://nominatim.openstreetmap.org/search?q={place}&format=json&limit=1`
   Header: `User-Agent: veritas-lite-demo/1.0 (contact: <your email>)`
   Cache the (place → lat/lon) mapping in a small in-memory dict or a SQLite table keyed on
   the place string, to avoid re-geocoding the same places repeatedly and to stay under the
   ~1 req/sec Nominatim rate limit.
2. Get route duration via OSRM:
   `GET https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false`
   Read `routes[0].duration` (seconds), convert to minutes.
3. Compare `actual_minutes` to `claimed_minutes`. Return
   `{"actual_minutes": ..., "claimed_minutes": ..., "gap_minutes": ..., "plausible": bool}`
   — pick a threshold for "plausible" (e.g. claimed within actual_minutes × 1.5, or within a
   flat ±10 minutes, whichever is simpler to justify) and apply it consistently, not
   case-by-case.

### `web_search`
Use Gemini's **native Google Search grounding tool** for this rather than writing a custom
web-search function — bind `google_search` as a tool alongside the three custom ones in the
same Gemini call (check current SDK docs for exact syntax, e.g.
`types.Tool(google_search=types.GoogleSearch())` in the `google-genai` Python SDK as of early
2026). No custom implementation needed; Gemini handles the search and returns grounded text
plus citations.

### `generate_image`
```json
{
  "name": "generate_image",
  "description": "Generate a quick illustrative image from a text description. This is a demonstration tool for showing tool-calling across different action types — it is not used as forensic evidence and its output should never be treated as a verified fact.",
  "parameters": {
    "type": "object",
    "properties": {
      "description": {"type": "string", "description": "What to generate, e.g. a description of a person or scene mentioned in a claim."}
    },
    "required": ["description"]
  }
}
```
**Implementation:** call Gemini's image-generation model with the description, return the
resulting image (base64 or a saved file path) as the tool result. If generation fails or is
blocked by safety filters, return a clear placeholder result (`{"success": false, "note":
"image generation unavailable"}`) rather than crashing the claim-verification turn — a failed
image-gen call should never block the rest of that claim's verdict.

**Important constraint on all four tools:** the model decides whether to call them per claim.
Do not write code that forces `check_route` to run on every `ROUTE`-typed claim — bind all
four tools on every per-claim call and let Gemini's own reasoning decide. If in practice the
model never calls a tool it obviously should, that's useful information for the demo script
(see §11), not something to patch around with manual routing — manual routing is exactly the
approach this build is deliberately avoiding.

## 8. Claim extraction

One Gemini call, **before** the tool-calling loop. System prompt (use this close to verbatim
— it's intentionally generic, not tuned to the Pune case, so it generalizes to the live
improvised statement in §3):

```
You are a claim extractor for an investigative-interview system. Given a statement from a
suspect, witness, or officer, extract a list of discrete, independently checkable factual
claims. Ignore vague or unverifiable statements (opinions, feelings, uncertain guesses).

For each claim, output:
- "text": the exact words from the statement that make this claim
- "claim_type": one of ROUTE, EVENT, PERSON, TIME, LOCATION, VEHICLE, OTHER
- "entities": a flat object of the relevant structured fields for that claim_type, e.g.
  for ROUTE: {"origin":, "destination":, "claimed_minutes":, "departure_time":, "arrival_time":}
  for VEHICLE: {"plate":, "color":, "type":}
  for PERSON: {"name":, "relationship":}
  for TIME: {"time":, "date":}
  for LOCATION: {"place":}
  for EVENT: {"name":, "date":}

A single sentence describing travel between two places with a time reference should be ONE
ROUTE claim with both origin/destination/time in its entities, not separate TIME and LOCATION
claims.

Return a JSON array only, no other text.

Statement: "{statement_text}"
```

This prompt is deliberately case-agnostic — it names no people, places, or vehicle plates
from the Pune case. That's load-bearing for the "prove it's not hardcoded" requirement in §3.

## 9. Per-claim verification loop (pseudocode)

```python
def verify_claim(claim: dict, case_id: str) -> dict:
    system_instruction = (
        "You are verifying one factual claim from an interview statement against a case "
        "file and real-world facts. You have four tools available: search_case_file, "
        "check_route, google_search, and generate_image. Call whichever tools are relevant "
        "to check this specific claim — you may call none, one, or several. Then respond "
        "with a JSON verdict: {\"status\": \"CONSISTENT\"|\"FLAGGED\"|\"CONFLICT\", "
        "\"reason\": \"<one or two sentences explaining the verdict, citing what the tools "
        "returned>\"}."
    )
    response = gemini_client.generate_content(
        model="gemini-2.5-flash",
        contents=[f"Claim: {claim['text']}\nType: {claim['claim_type']}\nEntities: {claim['entities']}"],
        tools=[search_case_file_tool, check_route_tool, google_search_tool, generate_image_tool],
        system_instruction=system_instruction,
    )
    # Handle the tool-calling loop: Gemini may return function_call parts; execute the
    # named Python function with the given args, feed the result back as a function_response
    # part, and continue the conversation turn until Gemini returns a final text response
    # with no more function calls. (Consult the google-genai SDK's documented pattern for
    # multi-turn function calling — this loop structure is standard across Gemini SDK
    # versions but exact method names change; check current docs at build time.)
    # ...
    verdict = parse_json(final_response.text)
    log_tool_calls = [...]  # every (tool_name, args, result) pair actually invoked
    return {
        "status": verdict["status"],
        "reason": verdict["reason"],
        "tool_calls": log_tool_calls,
    }
```

Store `tool_calls` in `claims.tool_calls_json` — this is what lets the demo show "here's the
tool the model actually chose to call," which is the point being demonstrated.

## 10. API endpoints

### `POST /sessions/start`
Request:
```json
{"case_id": "2026-PUN-0219", "subject_name": "Suresh Deshmukh"}
```
Response:
```json
{"session_id": "<uuid4>"}
```

### `POST /sessions/{session_id}/statements`
Request:
```json
{"text": "I was at my cousin's housewarming in Hadapsar. I left there around 9 PM..."}
```
Response:
```json
{
  "statement_id": 12,
  "claims": [
    {
      "id": 34,
      "text": "rode to the shop... got there about 9:40, then went straight home... by 9:50",
      "claim_type": "ROUTE",
      "status": "FLAGGED",
      "reason": "Actual travel time between the shop and Kothrud is approximately 27 minutes by road; the claimed 10 minutes is implausible.",
      "tool_calls": [
        {"tool": "check_route", "args": {"origin": "...", "destination": "...", "claimed_minutes": 10}, "result": {"actual_minutes": 27, "gap_minutes": 17, "plausible": false}}
      ]
    }
  ]
}
```

### `POST /sessions/{session_id}/audio`
Multipart form, field `audio` = the recorded clip (webm/wav/mp3). Runs local STT, then the
same pipeline as the text endpoint. Response: same shape as above, plus a top-level
`"transcript"` field with the STT output.

### `GET /cases/{case_id}`
Response:
```json
{
  "case_id": "2026-PUN-0219",
  "name": "Shree Lakshmi Jewellers Theft",
  "subjects": [{"full_name": "Suresh Deshmukh", "role": "SUSPECT", "notes": "..."}, ...],
  "evidence": [{"evidence_type": "SCENE", "description": "...", "metadata": {...}}, ...]
}
```

### `GET /sessions/{session_id}`
Response: full statement + claim history for that session (array of statements, each with
its nested claims), same claim shape as the `/statements` response above.

## 11. Frontend

React + Vite. One screen, two columns.

**Left column — Case File Panel.** On mount, `GET /cases/2026-PUN-0219`, render:
- Case name + ID
- A short list of subjects (name, role, notes)
- A short list of evidence (type, description)

**Right column — Interview Panel.**
- A textarea with a "Submit statement" button → `POST /sessions/{id}/statements`.
- A microphone/record button (use the browser's `MediaRecorder` API, record to a `webm`
  blob, POST it as multipart form data) → `POST /sessions/{id}/audio`. If `MediaRecorder` or
  mic permission is unavailable, the text path must still work standalone — don't make audio
  a hard dependency for the rest of the UI.
- Below the input: a running list of submitted statements (the session transcript so far).
- Below that: a **Claims table** — one row per claim across the whole session so far, columns:
  claim text (truncated), type, status (colored badge: green=CONSISTENT, amber=FLAGGED,
  red=CONFLICT), reason. Clicking a row expands to show the `tool_calls` actually made for
  that claim (tool name + args + result) — this is the part that visibly proves tool-calling
  happened, so don't skip it even though it's not strictly needed for the "claim got flagged"
  headline result.

On session start, call `POST /sessions/start` with `case_id: "2026-PUN-0219"` and whatever
subject name the user picks (default to "Suresh Deshmukh" for the primary demo path).

## 12. Environment / config

```
GEMINI_API_KEY=<the key already in hand>
WHISPER_MODEL_SIZE=base
NOMINATIM_USER_AGENT=veritas-lite-demo/1.0 (contact: <your email>)
DB_PATH=./veritas_lite.db
```
No `GOOGLE_MAPS_API_KEY`, no Elasticsearch config, no Firestore config — none of those are
used in this build.

## 13. Suggested folder structure

```
veritas-lite/
├── backend/
│   ├── main.py              # FastAPI app, route handlers
│   ├── config.py            # env var loading
│   ├── db.py                 # sqlite connection + schema creation
│   ├── seed.py                # seeds §3's case data, idempotent
│   ├── extraction.py          # §8: extract_claims()
│   ├── verification.py        # §9: verify_claim(), the tool-calling loop
│   ├── tools/
│   │   ├── case_file.py       # search_case_file implementation
│   │   ├── routing.py          # check_route implementation (Nominatim + OSRM)
│   │   └── image_gen.py        # generate_image implementation
│   └── stt.py                  # local Whisper transcription
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── CaseFilePanel.jsx
│   │   ├── InterviewPanel.jsx
│   │   └── ClaimsTable.jsx
│   └── (standard Vite scaffold files)
├── requirements.txt
└── .env
```

## 14. Build order

1. `db.py` + `seed.py` — create the schema from §6, seed the case data from §3. Verify by
   querying SQLite directly (`sqlite3 veritas_lite.db "select * from subjects;"`) before
   writing any API code.
2. `extraction.py` — wire the Gemini call from §8. Test it standalone against Suresh's alibi
   text (§3) from a Python REPL/script; confirm it returns a ROUTE claim with sane entities,
   before building anything else on top of it.
3. `tools/routing.py` — implement `check_route` against real Nominatim + OSRM calls. Test it
   standalone with `("Shree Lakshmi Jewellers, FC Road, Pune", "Kothrud, Pune", 10)` and
   confirm it returns a real actual_minutes figure and flags implausibility.
4. `tools/case_file.py` — implement `search_case_file` against the seeded SQLite data. Test
   standalone with a query like `"MH12"` and confirm it surfaces Ramesh's witness sighting.
5. `verification.py` — wire the full tool-calling loop (§9) with all four tools bound. Test
   it standalone by passing the ROUTE claim extracted in step 2 and confirming the model
   calls `check_route` and returns a FLAGGED verdict with a sane reason.
6. `main.py` — FastAPI endpoints (§10), wiring steps 1–5 together. Test via `curl` end to end
   before touching the frontend: start a session, submit Suresh's statement, confirm a
   FLAGGED route claim comes back in the response JSON.
7. `stt.py` + the `/sessions/{id}/audio` endpoint. Test with a short self-recorded clip of the
   same alibi text.
8. Frontend: `CaseFilePanel` first (simplest, read-only), then `InterviewPanel` text
   submission, then the `ClaimsTable`, then the audio-record button last.
9. End-to-end test: run the full demo script (§11's claims table check, §3's two test
   statements) through the actual UI, not just curl.

Steps 1–6 are backend-only and curl-testable — get them right before writing any React code.
This is the natural checkpoint for confirming the pipeline actually works before investing
time in UI polish.

## 15. Acceptance criteria

- [ ] Submitting Suresh's exact alibi statement (§3) via `POST /sessions/{id}/statements`
      produces at least one claim with `status: "FLAGGED"` or `"CONFLICT"`, and that claim's
      `tool_calls` array contains a real `check_route` call with a non-hardcoded
      `actual_minutes` value (confirm it's not always the same number regardless of input —
      change the claimed places and confirm the actual_minutes changes too).
- [ ] The same statement, when checked against Ramesh's witness sighting, surfaces that
      sighting via a `search_case_file` call (verify this either by inspecting `tool_calls`
      or by confirming the verdict's `reason` text references the vehicle/timing conflict).
- [ ] A second, improvised statement about an unrelated scenario (different places, names,
      times — written live, not pre-seeded) also produces extracted claims and a verdict,
      proving the extraction prompt and verification loop are not hardcoded to the Pune case.
- [ ] At least one demo run shows `web_search` or `generate_image` actually being called
      (even if not on the primary flagged claim) — confirms all four tools are reachable, not
      just the two the main scenario happens to need.
- [ ] A statement with no checkable claims (e.g. "I don't remember anything") does not crash
      the pipeline — it should return an empty or near-empty claims list, not a 500 error.
- [ ] The Case File panel correctly shows both subjects and all four evidence records.

## 16. Known risks (and what to do about them, don't just note them)

- **OSRM public demo server has no SLA** and can be slow or briefly unavailable. Cache
  geocoded coordinates after first lookup (§7) so retries don't re-hit Nominatim unnecessarily.
  If OSRM itself is down during the actual demo, have a backup plan: a straight-line-distance
  × average-speed estimate as a manual fallback value you can swap in, not a silent crash.
- **Nominatim's ~1 req/sec policy** — don't geocode the same place twice in one demo run;
  cache by place string.
- **Gemini tool-calling may occasionally pick an unexpected tool or no tool at all** for a
  claim that seems like it obviously needs one. This is a real property of letting the model
  decide — don't "fix" it by silently forcing a tool call in code, since that defeats the
  point. If it happens during the actual demo, it's a legitimate, explainable result ("the
  model judged this claim didn't need external verification"), not a bug to hide.
- **`generate_image` may be blocked by safety filters** or return a low-quality result. Treat
  any failure here as non-blocking — catch it, log it, continue the claim's verdict without
  the image. Never let this tool's failure take down the whole request.
