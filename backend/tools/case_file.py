"""search_case_file: structured WHERE/LIKE lookup. No ranking, FTS, BM25 or embeddings.

Also covers the PRD's match_evidence, so the model sees one case-file tool."""
import json
import re

import db

STOPWORDS = {
    "the", "and", "for", "with", "was", "were", "that", "this", "from", "around", "about",
    "his", "her", "their", "has", "had", "did", "not", "are", "any", "who", "what", "when",
    "where", "which", "near", "into", "after", "before", "then", "also", "claim", "claims",
    "claimed", "statement", "statements", "case", "file", "record", "records", "evidence",
}


def _terms(query: str) -> list[str]:
    tokens = re.findall(r"\d{1,2}:\d{2}|[a-z0-9]+", query.lower())
    terms = [t for t in tokens if t not in STOPWORDS and (len(t) >= 3 or ":" in t)]
    return list(dict.fromkeys(terms))


def _like_clause(columns: list[str], terms: list[str]) -> tuple[str, list[str]]:
    """OR of per-term, per-column LIKEs. Spaces are ignored in the column so that a plate
    written without spaces still matches one stored with them."""
    clauses, params = [], []
    for term in terms:
        for column in columns:
            clauses.append(f"LOWER(REPLACE({column}, ' ', '')) LIKE ?")
            params.append(f"%{term}%")
    return " OR ".join(clauses), params


def search_case_file(query: str, case_id: str, exclude_statement_id: int | None = None) -> dict:
    """exclude_statement_id keeps a statement from being returned as support for itself."""
    terms = _terms(query)
    empty = {"query_terms": terms, "subjects": [], "evidence": [], "prior_statements": [], "prior_claims": []}
    if not terms:
        return empty

    exclude = exclude_statement_id if exclude_statement_id is not None else -1
    with db.connect() as conn:
        where, params = _like_clause(["full_name", "nicknames", "role", "notes"], terms)
        subjects = conn.execute(
            f"SELECT full_name, nicknames, role, notes FROM subjects WHERE case_id = ? AND ({where})",
            [case_id, *params],
        ).fetchall()

        where, params = _like_clause(["evidence_type", "description", "metadata_json"], terms)
        evidence = conn.execute(
            f"SELECT evidence_type, description, metadata_json FROM evidence WHERE case_id = ? AND ({where})",
            [case_id, *params],
        ).fetchall()

        where, params = _like_clause(["st.text"], terms)
        statements = conn.execute(
            f"""SELECT st.id, st.session_id, st.turn_index, st.text
                FROM statements st JOIN sessions se ON st.session_id = se.id
                WHERE se.case_id = ? AND st.id != ? AND ({where})""",
            [case_id, exclude, *params],
        ).fetchall()

        where, params = _like_clause(["c.text", "c.entities_json"], terms)
        claims = conn.execute(
            f"""SELECT c.claim_type, c.text, c.status, c.reason
                FROM claims c JOIN statements st ON c.statement_id = st.id
                JOIN sessions se ON st.session_id = se.id
                WHERE se.case_id = ? AND st.id != ? AND ({where})""",
            [case_id, exclude, *params],
        ).fetchall()

        case = conn.execute(
            "SELECT id, name, location FROM cases WHERE id = ?", (case_id,)
        ).fetchone()

    return {
        "query_terms": terms,
        "case": dict(case) if case else None,
        "subjects": [dict(r) for r in subjects],
        "evidence": [
            {"evidence_type": r["evidence_type"], "description": r["description"],
             "metadata": json.loads(r["metadata_json"])}
            for r in evidence
        ],
        "prior_statements": [dict(r) for r in statements],
        "prior_claims": [dict(r) for r in claims],
    }
