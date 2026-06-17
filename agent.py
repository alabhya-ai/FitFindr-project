"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Usage:
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import create_fit_card, search_listings, suggest_outfit


# ── query parsing ─────────────────────────────────────────────────────────────

_PRICE_PATTERNS = [
    re.compile(r"\bunder\s+\$?(\d+(?:\.\d+)?)\b", re.I),
    re.compile(r"\bbelow\s+\$?(\d+(?:\.\d+)?)\b", re.I),
    re.compile(r"\bless\s+than\s+\$?(\d+(?:\.\d+)?)\b", re.I),
    re.compile(r"<\s*\$?(\d+(?:\.\d+)?)", re.I),
    re.compile(r"\$(\d+(?:\.\d+)?)\s*(?:max|or\s+less)?", re.I),
    re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:dollars?|bucks?)\s*(?:or\s+less|max)?\b", re.I),
]
_SIZE_PATTERN = re.compile(
    r"\b(?:in\s+)?size[:\s]+([XSMLxsml]+|\d{1,2}(?:\.\d)?)\b",
    re.I,
)


def _parse_query(query: str) -> dict:
    """
    Extract `description`, `size`, and `max_price` from a natural-language query.

    Uses regex — no LLM call. Anything left after stripping price/size patterns
    becomes the description, which is then passed to search_listings' keyword
    scorer.
    """
    text = query or ""
    max_price = None
    size = None

    for pat in _PRICE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                max_price = float(m.group(1))
                text = pat.sub("", text, count=1)
                break
            except ValueError:
                pass

    m = _SIZE_PATTERN.search(text)
    if m:
        size = m.group(1).upper() if m.group(1).isalpha() else m.group(1)
        text = _SIZE_PATTERN.sub("", text, count=1)

    description = re.sub(r"\s+", " ", text).strip(" ,.\n\t")
    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """Fresh session dict — single source of truth for one interaction."""
    return {
        "query": query,
        "parsed": {},
        "search_results": [],
        "selected_item": None,
        "wardrobe": wardrobe,
        "outfit_suggestion": None,
        "fit_card": None,
        "reloop_count": 0,
        "loosened": [],            # human-readable trail of what was relaxed
        "error": None,
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def _loosen(params: dict) -> tuple[dict, str | None]:
    """
    Drop the most restrictive constraint still active.
    Order: max_price → size → (nothing left to loosen).
    Returns (new_params, what_was_dropped) — what_was_dropped is None if
    nothing further can be relaxed.
    """
    if params.get("max_price") is not None:
        return {**params, "max_price": None}, f"price ceiling (${params['max_price']:g})"
    if params.get("size") is not None:
        return {**params, "size": None}, f"size filter ({params['size']})"
    return params, None


def run_agent(query: str, wardrobe: dict, max_reloop: int = 3) -> dict:
    """
    Run the FitFindr planning loop for one user interaction and return the
    completed session dict.

    Branches:
      - search_listings empty → loosen one constraint, retry. After
        `max_reloop` failed loosenings, set session["error"] and return early
        WITHOUT calling suggest_outfit / create_fit_card.
      - search_listings hits → store top result, then unconditionally call
        suggest_outfit and create_fit_card with state from the session.
    """
    session = _new_session(query, wardrobe)

    if not query or not query.strip():
        session["error"] = "Please describe what you're looking for."
        return session

    session["parsed"] = _parse_query(query)
    params = dict(session["parsed"])

    while True:
        results = search_listings(
            description=params["description"],
            size=params["size"],
            max_price=params["max_price"],
        )
        if results:
            session["search_results"] = results
            break

        session["reloop_count"] += 1
        if session["reloop_count"] > max_reloop:
            session["error"] = (
                f"No listings matched \"{query}\" even after relaxing "
                f"{', '.join(session['loosened']) or 'the filters'}. "
                "Try different keywords or a broader description."
            )
            return session

        params, dropped = _loosen(params)
        if dropped is None:
            session["error"] = (
                f"No listings matched \"{query}\" and there are no filters left "
                "to relax. Try different keywords."
            )
            return session
        session["loosened"].append(dropped)

    session["selected_item"] = session["search_results"][0]
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Parsed: {session['parsed']}")
        print(f"Found: {session['selected_item']['title']}")
        if session["loosened"]:
            print(f"Loosened: {session['loosened']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Parsed: {session2['parsed']}")
    print(f"Loosened: {session2['loosened']}")
    print(f"Error: {session2['error']}")
    print(f"Fit card is None: {session2['fit_card'] is None}")
