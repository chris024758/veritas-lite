"""web_search: Gemini's native Google Search grounding, behind a function tool.

Gemini is bound with function tools on the verification call, so grounding runs as its
own Gemini call here and the model sees an ordinary function result."""
from google.genai import errors, types

import gemini_client


def web_search(query: str, *, cited_only: bool = False) -> dict:
    try:
        response = gemini_client.generate(
            gemini_client.MODEL,
            f"Answer briefly from a web search, in at most three sentences: {query}",
            types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
    except (errors.APIError, gemini_client.GeminiNotConfigured) as exc:
        return {"query": query, "answer": None, "sources": [], "error": str(exc)}

    sources = []
    candidate = response.candidates[0] if response.candidates else None
    metadata = candidate.grounding_metadata if candidate else None
    cited_indices = set()
    if cited_only and metadata:
        for support in metadata.grounding_supports or []:
            cited_indices.update(support.grounding_chunk_indices or [])
    for index, chunk in enumerate((metadata.grounding_chunks or []) if metadata else []):
        if chunk.web and (not cited_only or index in cited_indices):
            sources.append({"title": chunk.web.title, "uri": chunk.web.uri})
    return {"query": query, "answer": response.text, "sources": sources}
