# VERITAS-Lite redesign plan

## Context
The first build works: alibi check, follow-ups, 3D timeline and report. But it has two problems.

- **Colours:** red is used everywhere, so a real alert doesn't stand out.
- **Navigation:** the Interview / Timeline / Report tabs don't match how an investigator works.

The new design follows the demo:
1. Pick a case from a directory.
2. Look at its case file.
3. Open the interview page.
4. Add the person being questioned.
5. They give 2–3 statements, which demonstrate:
   - a clash with seeded evidence
   - a clash with their own earlier statement
   - a maps check
   - image generation
6. End the interview and generate a report (PDF or .docx).

The 3D timeline is a separate view inside the case and updates live.

**Decided**
- **Interviewee:** Suresh Deshmukh stays in the seed. In the interview, he is chosen from a list of the people involved in the case.
- **Adding people:** an **Add person** option is always available, in case Ramesh (or anyone else) becomes part of the demo.
- **Maps panel:** a dummy SVG for now.
- **Mic flow:** speech is turned into text and shown on screen before it is sent to the LLM.

---

## 1. Demo script (what the build must make reliable)
| Turn | Statement | Features shown |
|---|---|---|
| — | Select **Suresh Deshmukh** (Suspect) from the people involved in the case | Choosing who to interview |
| 1 | Housewarming in Hadapsar, rode to the shop at 9:40, home in Kothrud by 9:50 | **Maps check:** shop → Kothrud flagged. The maps panel pops up with actual vs claimed minutes. **Clash with evidence:** the witness record puts the scooter at the shop at 22:15. |
| 2 | "Actually I got home around 10:30" | **Clash with own statement:** turn 2 vs turn 1 (9:50 vs 10:30), with the clashing words highlighted |
| 3 (optional) | "My white Activa was parked at home all night" | **Clash with evidence:** the plate match at the shop. **Image generation** of the described vehicle, labelled "illustrative only". |
| — | End interview → Generate report | Report in PDF and .docx |

**Optional extra:** select or add **Ramesh Kulkarni** (Witness) and record one statement from him. The alibi check then treats his words as a witness account for later checks. The design supports this, but the demo doesn't depend on it.

**Every turn follows the same steps:**
1. Click the mic and speak.
2. Click stop.
3. The text appears in the centre.
4. Fix any wrong words if needed.
5. Click **Send** to check it.

## 2. Navigation and layout
```
Case directory ─► Case (breadcrumb: Cases › Jewellers theft)
                   ├─ Case file  (default)
                   ├─ Interview
                   └─ Timeline   (3D, case-wide)
```

**Top bar (always visible)**
- Breadcrumb
- Alibi-clash counter, peach only when there are clashes
- **New interview** shortcut: pick a case → pick or add a person → it opens the same interview page

**Case directory**
- Cards for each case: name, ID, status, people count, last activity.
- Seed the jewellers case plus 1–2 short placeholder cases. A placeholder case opens to a case file with no interviews and a clear empty message.

**Case file**
- Summary, incident window, evidence cards (the layered hover card, recoloured), and the list of people.
- A **Start interview** button on each person.
- There is no list of earlier interviews; the demo needs only one.

**Interview page**
- **Before it starts:** the centre shows the **"Who are you interviewing?"** panel. The mic is disabled until a person is chosen.
- **Interviewee panel:**
  - Cards for the people on the case: role, notes, and number of earlier interviews.
  - It lists **everyone involved in the case**, so for the demo you simply select Suresh. Ramesh is listed too.
  - **+ Add person** form: name, role (Suspect / Witness / Victim / Other), notes, and optional phone, vehicle, plate and relation to the case. A person added here can be interviewed straight away and is added to the case file and the timeline.
  - If the name matches someone already on the case (ignoring case), it offers that person instead of creating a duplicate.
  - Once the interview starts, the header shows `Jewellers theft › Suresh Deshmukh · Suspect`. Clicking it shows the person's details.
- **Centre:** kept plain, with only the conversation.
  - The transcript: the question asked, when one was picked, then the answer.
  - The voice visualiser: an orb or waveform driven by the live mic level (Web Audio `AnalyserNode`), with the state underneath (Ready / Listening / Checking).
  - **Speech is shown as text before anything is sent:**
    1. **Click the mic.** While you speak, the browser's speech recognition shows rough captions live (Chrome and Edge only).
    2. **Click stop.** The clip goes to Whisper for **speech-to-text only**. No claims are extracted and nothing goes to Gemini yet.
    3. **Review.** Whisper's transcript appears in the centre as an editable draft, marked "Not sent yet".
    4. **Send.** Only when you click **Send** does the text go to the LLM to extract and check claims. **Discard** throws the draft away.
  - A small "type instead" link for typed answers, which go through the same review → Send step.
  - A sentence that clashed gets a subtle peach underline in the transcript.
- **Side panel:**
  - Alert banner and the Then vs Now cards.
  - The **Ask next** follow-up questions.
  - A collapsible card per claim showing its verdict and any generated image.
  - **Maps panel:**
    - **When it appears:** it pops up whenever a location or time claim was checked against real-world data, meaning a route check ran.
    - **What it shows:**
      - From and to
      - Distance
      - Actual vs claimed minutes, and the gap
      - A **dummy SVG map** with two pins and a curved route line, coloured peach when the trip was flagged.
    - **Later:** the dummy SVG will be replaced by a real Google Maps view; the panel's data stays the same.
- **One person per interview.** Choosing a different person asks to end the current interview first.
- **After End interview:** the mic area becomes **Generate report**. The report opens in a panel with **Export PDF** and **Download .docx**. There is no Report tab.

**Timeline**
- **Stays the same:** it's a separate full view, the 3D model from v1 (time across, one lane per person, an Evidence lane, arcs, incident window, alibi gaps), and it never pops up during the interview.
- **Live updates:** it refreshes after every statement and when you switch to it. New points drop into place while it's open.

## 3. Colours: navy and peach
| Token | Colour | Use |
|---|---|---|
| `--bg` | `#1b1f30` | Page |
| `--surface` | `#2d3250` | Panels, cards |
| `--surface-2` | `#424769` | Raised surfaces, inputs, borders |
| `--muted` | `#676f9d` | Secondary text (large only), icons, inactive tabs |
| `--text` | `#ffffff` | Main text |
| `--alert` | `#f9b17a` | **Alerts only** |

- **Peach is for alerts only:**
  - **Conflict / alibi clash:** solid peach.
  - **Flagged:** peach outline.
- **Other statuses:**
  - **Consistent:** white outline with ✓.
  - **Pending:** muted, with a shimmer.
- **Buttons** are white or outlined, never peach.
- **Restyled from red to the new palette:** glass panels, the loader (navy, white and a touch of peach), the notched flag popover (peach), the evidence hover card, and the timeline arcs and incident box (peach).
- **Printed and .docx report:** white page, navy text, peach only on the clashing words.

## 4. Backend changes
- **People**
  - `POST /cases/{id}/subjects`: name, role, notes, phone, vehicle, plate, relation. It returns the existing person on a case-insensitive name match (with `existing: true`).
  - `PATCH /subjects/{id}`: change role or notes.
  - The `subjects` table gains `phone`, `vehicle`, `plate` and `relation`, added through the existing `MIGRATIONS` list in `db.py`.
- **Sessions:** `POST /sessions/start` takes `subject_id`; `subject_name` is still accepted for the existing tests. A session can no longer start with an unknown speaker.
- **Cases:** `GET /cases` lists the cases for the directory, with people and interview counts.
- **Seed (`seed.py`)**
  - Keep Suresh (Suspect) and Ramesh (Witness), and all the evidence.
  - Make the seeded Ramesh interview optional behind a `--with-witness-interview` flag (off for the demo).
  - Add 1–2 placeholder cases.
- **People added live:** a plate or vehicle entered when adding a person must reach the checks, so `_speaker()` in `main.py` includes it in the speaker line.
- **Speech-to-text only:** new endpoint `POST /sessions/{id}/transcribe`.
  - It runs Whisper and returns `{transcript}` only, with no extraction or verification.
  - The reviewed text then goes through the existing `POST /sessions/{id}/statements`.
  - The current `/audio` endpoint, which transcribes and checks in one go, stays for the existing tests but the UI no longer uses it.
- **Maps check:** `check_route` is unchanged. The maps panel uses its existing result fields (from, to, distance, actual and claimed minutes, gap). No route geometry is needed while the map is a dummy SVG.
- **Image generation:** add a rule to the verification prompt: for a VEHICLE claim describing a vehicle, call `generate_image` once. Teach the fake server the same rule.
- **Report as .docx**
  - New `report_docx.py` uses **`python-docx`**, a new entry in `requirements.txt`.
  - `GET /sessions/{id}/report.docx` builds the file in memory and streams it as a download. Nothing is written to disk on the server.
  - **The test** writes the .docx to a temporary file, checks it contains the summary, findings and claims, then deletes it.
  - The report is generated after the interview ends, as now.
- **Rehearsal mode:** the existing `backend-fake-gemini` launch entry, with the fake server's scripts updated for all three demo turns, the Add person step and the vehicle image.

## 5. Frontend changes
- **Routing:** a tiny hash router (`#/cases`, `#/case/:id`, `#/case/:id/interview`, `#/case/:id/timeline`), with no new dependency.
- **New components**
  - `CaseDirectory.jsx`, `CaseFile.jsx`
  - `IntervieweePanel.jsx` (picker and Add person form)
  - `VoiceStage.jsx` (orb or waveform, live captions, recorder, and the editable "Not sent yet" draft with Send and Discard)
  - `SidePanel.jsx` (alerts, Then vs Now, Ask next, claim cards)
  - `MapsPanel.jsx`: the pop-up maps check with the dummy SVG map. No new dependency.
  - `ReportPanel.jsx` (replaces the Report tab)
- **Reworked components:** `App.jsx` (top bar and routes), `InterviewPanel.jsx` (split into the voice stage and the side panel), `ClaimsTable.jsx` (claims become cards in the side panel), `styles.css` (new colours), `Timeline3D.jsx` (colours and the live refresh).
- **Unchanged:** `AlibiAlert`, `FollowUps`, `FlagPopover`, `EvidenceCard` and `VeritasLoader` keep their logic and are only recoloured.

## 6. Tests
- `test_01`: updated seed counts (placeholder cases added).
- `test_05` / `test_06`: `/transcribe` returns the transcript and stores nothing.
- **New `test_09_demo_flow.py`, run against the fake stack**, covers the full demo:
  - Select Suresh by ID, start the interview, then submit turns 1, 2 and 3. It checks:
    - the evidence clash and the flagged route, with the fields the maps panel needs
    - the clash with his own earlier statement
    - the image on the vehicle claim
  - End the interview, generate the report, then download the .docx to a temporary file, check its contents and delete it.
  - Adding a new person (for example "Anita Joshi", Witness) works, and they can be interviewed straight away.
  - Adding a duplicate name returns the existing person.
  - Starting an interview with no person is rejected.
- **Browser walkthrough:** the same flow, plus the timeline updating while it's open, both colour checks (alerts are the only peach on screen), and print preview.

## 7. Build order
1. Backend: people endpoints, seed changes, `GET /cases`, sessions started by person ID, `/transcribe`, update existing tests.
2. Backend: the image-generation rule, report .docx, fake server scripts, `test_09`.
3. Frontend: navy and peach colours, router, case directory and case file.
4. Frontend: interview page (interviewee panel, voice stage with review before Send, side panel, maps panel, report panel).
5. Frontend: timeline colours and live refresh, remove the old tabs.
6. Full demo run on the fake stack, then once against real Gemini.

## Notes
- **Live captions:** they use the browser's speech recognition, which works in Chrome and Edge only. In other browsers, there are no captions while recording, but Whisper's text still appears for review before Send.
- **Real Google Maps:** a later change. It will need a Maps API key, and `check_route` will need to return the route's geometry.
