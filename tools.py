"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

_MODEL = "llama-3.3-70b-versatile"
_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "in", "on", "with", "to",
    "is", "it", "this", "that", "i", "im", "looking", "want", "need",
    "some", "any", "my", "me", "you", "are", "be", "under", "over",
    "size", "price", "cheap", "around",
}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOPWORDS]


def _size_matches(query_size: str, listing_size: str) -> bool:
    """Case-insensitive substring match — 'M' matches 'S/M', 'M (oversized)', etc."""
    if not query_size:
        return True
    if not listing_size:
        return False
    q = query_size.strip().lower()
    s = listing_size.strip().lower()
    if q in s:
        return True
    return q in re.split(r"[\s/()\-]+", s)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Returns a list of matching listing dicts, sorted by relevance (best match
    first). Returns an empty list if nothing matches — does NOT raise.
    """
    listings = load_listings()
    query_tokens = _tokenize(description)
    if not query_tokens and size is None and max_price is None:
        return []

    scored: list[tuple[float, dict]] = []
    for item in listings:
        if max_price is not None and item.get("price", 0) > max_price:
            continue
        if size is not None and not _size_matches(size, item.get("size", "")):
            continue

        haystack_parts = [
            item.get("title", ""),
            item.get("description", ""),
            item.get("category", ""),
            " ".join(item.get("style_tags", []) or []),
            " ".join(item.get("colors", []) or []),
            item.get("brand") or "",
        ]
        haystack_tokens = _tokenize(" ".join(haystack_parts))
        haystack_set = set(haystack_tokens)

        score = 0.0
        for qt in query_tokens:
            if qt in haystack_set:
                score += 2.0
            elif len(qt) >= 5:
                for ht in haystack_set:
                    if len(ht) >= 5 and (qt.startswith(ht) or ht.startswith(qt)):
                        score += 0.5
                        break

        if not query_tokens:
            score = 1.0

        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.
    Falls back to general styling advice when the wardrobe is empty.
    """
    client = _get_groq_client()

    item_summary = (
        f"- Title: {new_item.get('title', 'Unknown')}\n"
        f"- Category: {new_item.get('category', 'unknown')}\n"
        f"- Colors: {', '.join(new_item.get('colors', []) or []) or 'unspecified'}\n"
        f"- Style tags: {', '.join(new_item.get('style_tags', []) or []) or 'none'}\n"
        f"- Description: {new_item.get('description', '')}"
    )

    items = (wardrobe or {}).get("items", []) if isinstance(wardrobe, dict) else []

    if not items:
        prompt = (
            "You are a thrift-savvy stylist. The user just found this piece but "
            "hasn't told you what's in their closet yet:\n\n"
            f"{item_summary}\n\n"
            "Give general styling advice for this item: what pieces pair well with it, "
            "what vibe/aesthetic it fits, and 1–2 specific outfit ideas using generic "
            "wardrobe staples (e.g., 'dark wash jeans', 'white sneakers'). "
            "Keep it concise — 3–5 sentences."
        )
    else:
        wardrobe_lines = []
        for w in items:
            name = w.get("name", "unnamed piece")
            cat = w.get("category", "")
            colors = ", ".join(w.get("colors", []) or [])
            tags = ", ".join(w.get("style_tags", []) or [])
            wardrobe_lines.append(
                f"- {name} ({cat}; colors: {colors or 'n/a'}; tags: {tags or 'n/a'})"
            )
        wardrobe_block = "\n".join(wardrobe_lines)

        prompt = (
            "You are a thrift-savvy stylist. The user is considering this new piece:\n\n"
            f"{item_summary}\n\n"
            "Their current wardrobe:\n"
            f"{wardrobe_block}\n\n"
            "Suggest 1–2 complete outfits that combine the new piece with specific, "
            "named items from their wardrobe (refer to them by name). Each outfit "
            "should include a top, bottom, and shoes at minimum. Mention the overall "
            "vibe in a few words. Keep the whole response under 6 sentences."
        )

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=400,
    )
    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.
    Returns a descriptive error string (not an exception) if outfit is missing.
    """
    if not outfit or not outfit.strip():
        title = (new_item or {}).get("title", "this piece") if isinstance(new_item, dict) else "this piece"
        return (
            f"[fit card unavailable] No outfit was provided for \"{title}\" — "
            "run suggest_outfit first, then try again."
        )

    item = new_item or {}
    item_block = (
        f"Item: {item.get('title', 'thrifted piece')}\n"
        f"Price: ${item.get('price', '??')}\n"
        f"Platform: {item.get('platform', 'a resale app')}\n"
        f"Style tags: {', '.join(item.get('style_tags', []) or []) or 'none'}"
    )

    prompt = (
        "Write a casual Instagram/TikTok caption (2–4 sentences) for a thrifted "
        "outfit. Sound like a real person posting an OOTD, not a product listing. "
        "Mention the item name, the price, and the platform naturally — each once. "
        "Capture the vibe in specific words. Avoid hashtags unless they feel natural.\n\n"
        f"{item_block}\n\n"
        f"Outfit details:\n{outfit}\n\n"
        "Caption:"
    )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=1.0,
        max_tokens=200,
    )
    return response.choices[0].message.content.strip()
