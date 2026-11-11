"""Small resilient web-search tool; it never turns a verification failure into a 500."""
from urllib.parse import quote_plus

import requests
from langchain_core.tools import tool


@tool
def web_search(query: str) -> dict:
    """Find public sources relevant to a factual query."""
    try:
        response = requests.get(
            f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1",
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        sources = [
            {"title": item.get("Text", "Source"), "uri": item.get("FirstURL")}
            for item in payload.get("RelatedTopics", [])[:3]
            if isinstance(item, dict) and item.get("FirstURL")
        ]
        return {"query": query, "answer": payload.get("AbstractText") or None, "sources": sources}
    except (requests.RequestException, ValueError) as exc:
        return {"query": query, "answer": None, "sources": [], "error": f"web search failed: {exc}"}
