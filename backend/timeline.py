"""Case timeline: one shared clock axis, one lane per speaker plus an Evidence lane. Stories are
never merged; what matters is where lanes collide (alibi-check links) and which part of the
incident window a subject's own claims leave uncovered (alibi gaps)."""
import re

import db

POINT_COVER_MINUTES = 5  # a claim at one moment accounts for this long either side
MIN_GAP_MINUTES = 5
PAD_MINUTES = 20


def to_minutes(value: str | None) -> int | None:
    """Minutes after midnight. Accepts '21:40', '9:40 PM', '9 pm'. A bare '9:40' with no AM/PM
    is read as evening for hours 1-11, which suits this night-time case and is only a fallback:
    extraction is asked for 24-hour time_start/time_end."""
    if not value:
        return None
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?\s*m?\b", value.strip().lower())
    if not match:
        return None
    hours, minutes, half = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if hours > 23 or minutes > 59:
        return None
    if half == "p" and hours < 12:
        hours += 12
    elif half == "a" and hours == 12:
        hours = 0
    elif half is None and 1 <= hours <= 11 and not value.strip().startswith("0"):
        hours += 12
    return hours * 60 + minutes


def _claim_times(entities: dict) -> tuple[int | None, int | None]:
    start = to_minutes(entities.get("time_start")) if entities.get("time_start") else to_minutes(entities.get("time"))
    end = to_minutes(entities.get("time_end"))
    if start is not None and end is not None and end < start:
        start, end = end, start
    if start is None and end is not None:
        start, end = end, None
    return start, end


def _gaps(window: tuple[int, int], intervals: list[tuple[int, int]]) -> list[list[int]]:
    gaps, cursor = [], window[0]
    for start, end in sorted(intervals):
        if start > cursor and start - cursor >= MIN_GAP_MINUTES:
            gaps.append([cursor, min(start, window[1])])
        cursor = max(cursor, end)
        if cursor >= window[1]:
            break
    if window[1] - cursor >= MIN_GAP_MINUTES:
        gaps.append([cursor, window[1]])
    return [g for g in gaps if g[1] > g[0]]


def build(case_id: str) -> dict | None:
    case = db.get_case(case_id)
    if case is None:
        return None
    claims = db.get_case_claims(case_id)
    findings = db.get_findings(case_id=case_id)

    lanes = [{"id": "evidence", "label": "Case evidence", "role": "Evidence"}]
    lane_of_subject = {}
    roles = {s["id"]: s for s in case["subjects"]}
    speakers = []
    for claim in claims:
        key = f"s{claim['subject_id']}" if claim["subject_id"] is not None else f"session{claim['session_id']}"
        if key not in lane_of_subject:
            lane_of_subject[key] = key
            subject = roles.get(claim["subject_id"])
            speakers.append({"id": key, "label": claim["speaker"],
                             "role": subject["role"] if subject else "Unknown"})
        claim["lane"] = key
    # Suspects sit next to the evidence lane, witnesses behind them.
    speakers.sort(key=lambda lane: (lane["role"] != "Suspect", lane["role"] != "Witness"))
    lanes += speakers

    events, untimed = [], []
    for claim in claims:
        start, end = _claim_times(claim["entities"])
        event = {
            "id": f"c{claim['id']}", "kind": "claim", "claim_id": claim["id"], "lane": claim["lane"],
            "text": claim["text"], "claim_type": claim["claim_type"], "status": claim["status"],
            "reason": claim["reason"], "speaker": claim["speaker"], "session_id": claim["session_id"],
            "turn_index": claim["turn_index"], "start": start, "end": end,
            "approx": bool(claim["entities"].get("time_approx")),
        }
        (events if start is not None else untimed).append(event)
    for item in case["evidence"]:
        start = to_minutes(item["metadata"].get("time"))
        event = {
            "id": f"e{item['id']}", "kind": "evidence", "evidence_id": item["id"], "lane": "evidence",
            "text": item["description"], "evidence_type": item["evidence_type"], "status": "EVIDENCE",
            "speaker": "Case file", "start": start, "end": None, "approx": False,
        }
        (events if start is not None else untimed).append(event)

    links = [
        {
            "id": f["id"], "from": f"c{f['claim_id']}",
            "to": f"c{f['other_claim_id']}" if f["other_claim_id"] is not None else f"e{f['evidence_id']}",
            "kind": f["kind"], "severity": f["severity"], "explanation": f["explanation"],
            "new_quote": f["new_quote"], "prior_quote": f["prior_quote"],
        }
        for f in findings
    ]

    incident = None
    start, end = to_minutes(case.get("incident_start")), to_minutes(case.get("incident_end"))
    if start is not None and end is not None:
        incident = {"start": start, "end": end}

    gaps = []
    if incident:
        for lane in speakers:
            if lane["role"] != "Suspect":
                continue
            covered = [
                (e["start"], e["end"]) if e["end"] is not None
                else (e["start"] - POINT_COVER_MINUTES, e["start"] + POINT_COVER_MINUTES)
                for e in events if e["lane"] == lane["id"]
            ]
            for gap in _gaps((incident["start"], incident["end"]), covered):
                gaps.append({"lane": lane["id"], "start": gap[0], "end": gap[1]})

    times = [e["start"] for e in events] + [e["end"] for e in events if e["end"] is not None]
    if incident:
        times += [incident["start"], incident["end"]]
    axis = {"start": min(times) - PAD_MINUTES, "end": max(times) + PAD_MINUTES} if times else None

    return {"case_id": case_id, "lanes": lanes, "events": events, "untimed": untimed,
            "links": links, "incident": incident, "gaps": gaps, "axis": axis}
