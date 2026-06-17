"""
Tool tests — one or more cases per failure mode.

Run with: pytest tests/

The suggest_outfit and create_fit_card cases hit the Groq API. Set
GROQ_API_KEY in .env; tests are skipped if the key is missing.
"""

import os

import pytest

from tools import create_fit_card, search_listings, suggest_outfit
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe

needs_groq = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set",
)


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    assert all(isinstance(item, dict) and "title" in item for item in results)


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=25)
    assert all(item["price"] <= 25 for item in results)


def test_search_size_filter_case_insensitive():
    results = search_listings("tee", size="m", max_price=None)
    assert len(results) > 0
    for item in results:
        size = item["size"].lower()
        assert "m" in size


def test_search_sorted_by_relevance():
    results = search_listings("vintage graphic tee", size=None, max_price=None)
    top = results[0]
    title_tags = (top["title"] + " " + " ".join(top.get("style_tags", []))).lower()
    assert "tee" in title_tags or "graphic" in title_tags


# ── suggest_outfit ────────────────────────────────────────────────────────────

@needs_groq
def test_suggest_outfit_with_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(out, str)
    assert len(out.strip()) > 0


@needs_groq
def test_suggest_outfit_empty_wardrobe_returns_advice():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(out, str)
    assert len(out.strip()) > 0


# ── create_fit_card ───────────────────────────────────────────────────────────

@needs_groq
def test_create_fit_card_returns_caption():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    outfit = "Pair with baggy jeans and chunky sneakers for a Y2K streetwear vibe."
    card = create_fit_card(outfit, item)
    assert isinstance(card, str)
    assert len(card.strip()) > 0


def test_create_fit_card_empty_outfit_returns_error_string():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("", item)
    assert isinstance(card, str)
    assert "fit card unavailable" in card.lower() or "no outfit" in card.lower()


def test_create_fit_card_whitespace_outfit_returns_error_string():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("   \n\t  ", item)
    assert isinstance(card, str)
    assert "fit card unavailable" in card.lower() or "no outfit" in card.lower()


@needs_groq
def test_create_fit_card_varies_across_calls():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    outfit = "Pair with baggy jeans and chunky sneakers for a Y2K streetwear vibe."
    a = create_fit_card(outfit, item)
    b = create_fit_card(outfit, item)
    assert a != b, "fit card should vary across calls (raise temperature if it doesn't)"
