"""Per-claim Gemini tool-calling loop. All four tools are bound on every call and the model
chooses among them; there is no routing on claim_type."""
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

MAX_TOOL_ROUNDS = 5

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
SYSTEM_PROMPT = """You verify one claim from a person's statement in an investigation, using tools. Choose for yourself which tools the claim needs, if any, and call as many as are useful. Base the verdict only on what tools return, never on your own knowledge of places, travel times, or people.

Look for anything in the records that bears on the claim, including records that do not mention it directly. For a claim about where someone was at a time, compare it with any record of a matching person or vehicle at another place around or after that time. If a claim uses a vague place, find out what it refers to from the case records, and use the rest of the statement and the case location to make place names specific enough for a route lookup.

Verdicts:
- CONSISTENT: tool results support the claim and nothing contradicts it.
- FLAGGED: something makes the claim doubtful, for example a route check with exceeds_tolerance true, or a record that sits uneasily with the claim or only partly matches.
- CONFLICT: a record directly contradicts the claim.
- PENDING: the tools could not establish anything either way, for example nothing relevant was found.

When a route check informed the verdict, the reason must state actual_minutes and claimed_minutes, and mention the assumed speed if the result used one. When a record informed it, name that record and what it says. Do not treat a failed tool as evidence.

When you are finished, reply with only a JSON object: {"status": "<verdict>", "reason": "<one or two sentences>"}"""

VERDICT_REMINDER = 'Give your verdict now as JSON only: {"status": "...", "reason": "..."}'


class Verdict(BaseModel):
    status: str
    reason: str


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


def _parse_verdict(text: str | None) -> Verdict | None:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        verdict = Verdict.model_validate_json(match.group(0))
    except ValueError:
        return None
    verdict.status = verdict.status.strip().upper()
    return verdict if verdict.status in db.VALID_STATUSES else None


def _user_prompt(claim: dict, statement: str, case_id: str, speaker: str) -> str:
    return (
        f"Case ID: {case_id}\n"
        f"Speaker: {speaker}\n"
        f"Full statement: {statement}\n"
        f"Claim to verify ({claim['claim_type']}): {claim['text']}\n"
        f"Extracted entities: {json.dumps(claim['entities'], ensure_ascii=False)}"
    )


def verify_claim(claim: dict, statement: str, statement_id: int, case_id: str, speaker: str) -> dict:
    """Returns {status, reason, details}. A Gemini failure leaves the claim PENDING."""
    tool_calls = []
    contents = [types.Content(role="user", parts=[types.Part(text=_user_prompt(claim, statement, case_id, speaker))])]

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

    def result(status: str, reason: str) -> dict:
        return {"status": status, "reason": reason, "details": {"tool_calls": tool_calls}}

    try:
        response = None
        for _ in range(MAX_TOOL_ROUNDS):
            response = gemini_client.generate(gemini_client.MODEL, contents, config(True))
            calls = response.function_calls or []
            if not calls:
                break
            contents.append(response.candidates[0].content)
            parts = []
            for call in calls:
                args = dict(call.args or {})
                output = _dispatch(call.name, args, case_id, statement_id)
                tool_calls.append({"name": call.name, "args": args, "result": output})
                parts.append(types.Part.from_function_response(name=call.name, response={"result": output}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            response = None  # ran out of rounds on a tool call: ask for the verdict below

        verdict = _parse_verdict(response.text) if response is not None else None
        if verdict is None:
            if response is not None and response.candidates and response.candidates[0].content:
                contents.append(response.candidates[0].content)
            contents.append(types.Content(role="user", parts=[types.Part(text=VERDICT_REMINDER)]))
            verdict = _parse_verdict(gemini_client.generate(gemini_client.MODEL, contents, config(False)).text)
    except (errors.APIError, gemini_client.GeminiNotConfigured, ValueError) as exc:
        return result("PENDING", f"Verification did not complete: {exc}")

    if verdict is None:
        return result("PENDING", "The model did not return a usable verdict.")
    return result(verdict.status, verdict.reason)
