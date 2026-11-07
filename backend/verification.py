"""Gemini tool-calling loop over all of one statement's claims at once. All four tools are
bound on every call and the model chooses among them; there is no routing on claim_type."""
import json
import re

from google.genai import errors, types
from pydantic import BaseModel

import db
import gemini_client
from tools.case_file import search_case_file
from tools.image_gen import generate_image
from tools.routing import check_route
from tools.web_search import web_search

# Calls with tools enabled. One more tools-off call may follow to force the verdicts, so a
# statement costs at most MAX_TOOL_ROUNDS + 1 verification calls, whatever its claim count.
MAX_TOOL_ROUNDS = 3

TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="search_case_file",
        description=(
            "Look up this case's records: subjects, physical and witness evidence, and earlier "
            "statements and claims. Matches names, vehicle plates, descriptors, locations, and "
            "times by keyword. Also use it to find out what a vague reference such as "
            "'the shop' or 'the office' refers to."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords: names, plates, places, times."},
                "case_id": {"type": "string"},
            },
            "required": ["query", "case_id"],
        },
    ),
    types.FunctionDeclaration(
        name="check_route",
        description=(
            "Get the real distance and estimated travel time between two places and compare it "
            "to a claimed duration. Returns actual_minutes, gap_minutes (actual minus claimed), "
            "and exceeds_tolerance. Places must be specific enough to geocode, including the "
            "city, for example 'Area, City'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "claimed_minutes": {"type": "number"},
            },
            "required": ["origin", "destination"],
        },
    ),
    types.FunctionDeclaration(
        name="web_search",
        description=(
            "Search the web for a public fact, such as whether a venue or address is real, and "
            "get a short answer with sources."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    types.FunctionDeclaration(
        name="generate_image",
        description=(
            "Generate an illustrative image from a text description, for example a vehicle or "
            "scene described in the claim or records, to help an investigator picture it. "
            "Illustrative only: it is never evidence and never affects the verdict."
        ),
        parameters={
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
    ),
]

# Must stay generic: the case details arrive through tools, not through this prompt.
SYSTEM_PROMPT = """You verify the numbered claims from one person's statement in an investigation, using tools, and give a verdict for every claim. Choose for yourself which tools each claim needs, if any. You have only a few rounds of tool use, so in each round request every tool call you need at once: you can call several tools, and the same tool several times, in one turn. One result can inform several claims. Base verdicts only on what tools return, never on your own knowledge of places, travel times, or people.

Look for anything in the records that bears on each claim, including records that do not mention it directly. For a claim about where someone was at a time, compare it with any record of a matching person or vehicle at another place around or after that time. If a claim uses a vague place, find out what it refers to from the case records, and use the rest of the statement and the case location to make place names specific enough for a route lookup.

Verdicts:
- CONSISTENT: tool results support the claim and nothing contradicts it.
- FLAGGED: something makes the claim doubtful, for example a route check with exceeds_tolerance true, or a record that sits uneasily with the claim or only partly matches.
- CONFLICT: a record directly contradicts the claim.
- PENDING: the tools could not establish anything either way, for example nothing relevant was found.

When a route check informed a verdict, the reason must state actual_minutes and claimed_minutes, and mention the assumed speed if the result used one. When a record informed it, name that record and what it says. Do not treat a failed tool as evidence.

Every tool result carries a call_id. When you are finished, reply with only a JSON object holding one verdict per claim, listing the call_ids of the results that verdict relied on:
{"verdicts": [{"claim": <claim number>, "status": "<verdict>", "reason": "<one or two sentences>", "evidence_calls": [<call_id>, ...]}]}"""

VERDICT_REMINDER = (
    'Give your verdicts now as JSON only: {"verdicts": [{"claim": <claim number>, '
    '"status": "...", "reason": "...", "evidence_calls": [<call_id>, ...]}]}'
)


class Verdict(BaseModel):
    claim: int
    status: str
    reason: str
    evidence_calls: list[int] = []


class Verdicts(BaseModel):
    verdicts: list[Verdict]


def _dispatch(name: str, args: dict, case_id: str, statement_id: int) -> dict:
    try:
        if name == "search_case_file":
            # case_id and statement_id come from the session, not the model.
            return search_case_file(args.get("query", ""), case_id, exclude_statement_id=statement_id)
        if name == "check_route":
            return check_route(args["origin"], args["destination"], args.get("claimed_minutes"))
        if name == "web_search":
            return web_search(args["query"])
        if name == "generate_image":
            return generate_image(args["description"])
    except KeyError as exc:
        return {"error": f"missing argument {exc} for {name}"}
    return {"error": f"unknown tool {name}"}


def _parse_verdicts(text: str | None) -> dict[int, Verdict] | None:
    """Verdicts keyed by claim number, or None if the reply is not usable at all."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        parsed = Verdicts.model_validate_json(match.group(0))
    except ValueError:
        return None
    verdicts = {}
    for verdict in parsed.verdicts:
        verdict.status = verdict.status.strip().upper()
        if verdict.status in db.VALID_STATUSES:
            verdicts[verdict.claim] = verdict
    return verdicts


def _user_prompt(claims: list[dict], statement: str, case_id: str, speaker: str) -> str:
    lines = [
        f"[{number}] ({claim['claim_type']}) {claim['text']} | entities: "
        f"{json.dumps(claim['entities'], ensure_ascii=False)}"
        for number, claim in enumerate(claims, start=1)
    ]
    return (
        f"Case ID: {case_id}\n"
        f"Speaker: {speaker}\n"
        f"Full statement: {statement}\n"
        f"Claims to verify:\n" + "\n".join(lines)
    )


def verify_statement(claims: list[dict], statement: str, statement_id: int, case_id: str, speaker: str) -> list[dict]:
    """One {status, reason, details} per claim, in order. A Gemini failure leaves every claim
    PENDING; a claim the model gives no verdict for is PENDING on its own."""
    if not claims:
        return []
    tool_calls = []
    contents = [types.Content(role="user", parts=[types.Part(text=_user_prompt(claims, statement, case_id, speaker))])]
    model_calls = 0

    def config(allow_tools: bool) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
            tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO" if allow_tools else "NONE")
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def outcome(status: str, reason: str, evidence_calls: list[int]) -> dict:
        cited = [call for call in tool_calls if call["id"] in evidence_calls]
        details = {"tool_calls": cited, "statement_tool_calls": len(tool_calls), "statement_model_calls": model_calls}
        return {"status": status, "reason": reason, "details": details}

    try:
        response = None
        for _ in range(MAX_TOOL_ROUNDS):
            response = gemini_client.generate(gemini_client.MODEL, contents, config(True))
            model_calls += 1
            calls = response.function_calls or []
            if not calls:
                break
            contents.append(response.candidates[0].content)
            parts = []
            for call in calls:
                args = dict(call.args or {})
                output = _dispatch(call.name, args, case_id, statement_id)
                call_id = len(tool_calls) + 1
                tool_calls.append({"id": call_id, "name": call.name, "args": args, "result": output})
                parts.append(types.Part.from_function_response(
                    name=call.name, response={"call_id": call_id, "result": output}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            response = None  # ran out of rounds on a tool call: ask for the verdicts below

        verdicts = _parse_verdicts(response.text) if response is not None else None
        if verdicts is None:
            if response is not None and response.candidates and response.candidates[0].content:
                contents.append(response.candidates[0].content)
            contents.append(types.Content(role="user", parts=[types.Part(text=VERDICT_REMINDER)]))
            verdicts = _parse_verdicts(gemini_client.generate(gemini_client.MODEL, contents, config(False)).text)
            model_calls += 1
    except (errors.APIError, gemini_client.GeminiNotConfigured, ValueError) as exc:
        return [outcome("PENDING", f"Verification did not complete: {exc}", []) for _ in claims]

    if verdicts is None:
        return [outcome("PENDING", "The model did not return usable verdicts.", []) for _ in claims]
    results = []
    for number in range(1, len(claims) + 1):
        verdict = verdicts.get(number)
        if verdict is None:
            results.append(outcome("PENDING", "The model gave no verdict for this claim.", []))
        else:
            results.append(outcome(verdict.status, verdict.reason, verdict.evidence_calls))
    return results
