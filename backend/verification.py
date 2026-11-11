"""LangGraph verification workflow where Groq chooses which tools to invoke."""
import json
import re
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel

import db
import groq_client
from tools.case_file import search_case_file
from tools.image_gen import generate_image
from tools.routing import check_route
from tools.web_search import web_search

MAX_TOOL_ROUNDS = 3

SYSTEM_PROMPT = """You verify interview claims against a case file and public facts. Decide which
tools, if any, are relevant; never invent tool results. The ONLY valid tool names are exactly
search_case_file, check_route, web_search, and generate_image. Never add spaces, suffixes, or
different capitalization. Use search_case_file for case evidence and check_route for a claimed
journey. Then return JSON only:
{"verdicts":[{"claim":1,"status":"CONSISTENT|FLAGGED|CONFLICT|PENDING","reason":"brief evidence-based reason"}]}.
PENDING means the available evidence was inconclusive."""


class Verdict(BaseModel):
    claim: int
    status: str
    reason: str


class Verdicts(BaseModel):
    verdicts: list[Verdict]


class VerificationState(TypedDict):
    # add_messages is required so each model/tool turn remains visible to the graph.
    messages: Annotated[list[BaseMessage], add_messages]


def _tools(case_id: str, statement_id: int):
    """Bind trusted case context in closures so the model cannot read another case."""
    @tool("search_case_file")
    def search_case_file_tool(query: str) -> dict:
        """Search prior subjects, statements, claims, and evidence in this case."""
        try:
            return search_case_file(query, case_id, exclude_statement_id=statement_id)
        except Exception as exc:
            return {"error": f"case-file search failed: {exc}"}

    @tool("check_route")
    def check_route_tool(origin: str, destination: str, claimed_minutes: float | None = None) -> dict:
        """Compare a claimed journey duration with an actual driving route."""
        try:
            return check_route(origin, destination, claimed_minutes)
        except Exception as exc:
            return {"error": f"route check failed: {exc}"}

    return [search_case_file_tool, check_route_tool, web_search, generate_image]


def _prompt(claims: list[dict], statement: str, case_id: str, speaker: str) -> str:
    numbered = "\n".join(
        f"[{index}] {claim['claim_type']}: {claim['text']} | entities={json.dumps(claim['entities'])}"
        for index, claim in enumerate(claims, 1)
    )
    return f"Case: {case_id}\nSpeaker: {speaker}\nStatement: {statement}\nClaims:\n{numbered}"


def _parse(text: str) -> dict[int, Verdict]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        values = Verdicts.model_validate_json(match.group())
    except ValueError:
        return {}
    return {item.claim: item for item in values.verdicts if item.status.upper() in db.VALID_STATUSES}


def verify_statement(claims: list[dict], statement: str, statement_id: int, case_id: str, speaker: str) -> list[dict]:
    """Run a bounded StateGraph; a provider/tool error leaves only this turn PENDING."""
    if not claims:
        return []
    selected_tools = _tools(case_id, statement_id)
    model = groq_client.get_model().bind_tools(selected_tools)

    def agent(state: VerificationState) -> dict:
        # The model remains the sole decision-maker for tool selection.
        return {"messages": [model.invoke(state["messages"])]}

    def route(state: VerificationState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else END

    graph = StateGraph(VerificationState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(selected_tools, handle_tool_errors=True))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    initial = {"messages": [SystemMessage(SYSTEM_PROMPT), HumanMessage(_prompt(claims, statement, case_id, speaker))]}
    try:
        final = graph.compile().invoke(initial, {"recursion_limit": MAX_TOOL_ROUNDS * 2 + 2})
    except Exception:
        # A provider-side tool-schema rejection is transient and should not dump its raw
        # response into every row of the interface.
        return [{"status": "PENDING", "reason": "Verification could not complete because the model issued an invalid tool call. Please retry the statement.", "details": {"tool_calls": []}} for _ in claims]

    final_text = next((m.content for m in reversed(final["messages"]) if isinstance(m, AIMessage) and not m.tool_calls), "")
    verdicts = _parse(str(final_text))
    calls, results = {}, {}
    for message in final["messages"]:
        if isinstance(message, AIMessage):
            calls.update({call["id"]: {"name": call["name"], "args": call.get("args", {})} for call in message.tool_calls})
        elif isinstance(message, ToolMessage):
            try:
                results[message.tool_call_id] = json.loads(message.content)
            except (TypeError, json.JSONDecodeError):
                results[message.tool_call_id] = {"result": str(message.content)}
    tool_calls = [{**call, "result": results.get(call_id, {})} for call_id, call in calls.items()]
    outcomes = []
    for index in range(1, len(claims) + 1):
        verdict = verdicts.get(index)
        if verdict is None:
            outcomes.append({"status": "PENDING", "reason": "The model returned no usable verdict for this claim.", "details": {"tool_calls": tool_calls}})
        else:
            outcomes.append({"status": verdict.status.upper(), "reason": verdict.reason, "details": {"tool_calls": tool_calls}})
    return outcomes
