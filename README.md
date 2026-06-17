# FitFindr

FitFindr is a multi-tool AI agent that helps users find secondhand pieces and figure out how to wear them. The agent takes a natural-language request (e.g. *"vintage graphic tee under $30"*), searches a mock listings dataset, suggests outfits that combine the find with the user's existing wardrobe, and generates a shareable Instagram/TikTok-style "fit card."

The interesting work is *not* in any single tool — it's in the planning loop that decides which tool to call next, how to react when the first search comes back empty, and how to keep state flowing between tools without re-prompting the user.

---

## What's Included

```
FitFindr-project/
├── agent.py                  # Planning loop + session state
├── tools.py                  # search_listings, suggest_outfit, create_fit_card
├── app.py                    # Gradio UI
├── tests/
│   └── test_tools.py         # pytest suite (failure modes covered)
├── data/
│   ├── listings.json         # 40 mock secondhand listings
│   └── wardrobe_schema.json  # Wardrobe format + example wardrobe
├── utils/
│   └── data_loader.py        # Helper functions for loading the data
├── planning.md               # Spec, planning loop, architecture diagram
└── requirements.txt          # Python dependencies
```

## Setup

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (get a free key at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

Then run it:
```bash
python app.py        # Gradio UI at the URL printed in the terminal
python agent.py      # CLI smoke test (happy path + no-results path)
pytest tests/        # 11-test failure-mode suite
```

---

## Tool Inventory

### `search_listings(description, size, max_price) → list[dict]`

**Purpose:** Search the mock listings dataset for items matching a free-text description, an optional size, and an optional price ceiling. Returns the matching listing dicts sorted by relevance (highest keyword overlap first).

**Inputs:**
- `description` (`str`) — keywords describing what the user is looking for (e.g., `"vintage graphic tee"`).
- `size` (`str | None`) — size string to filter by, or `None` to skip size filtering. Match is case-insensitive and substring-aware so `"M"` hits listings sized `"S/M"` or `"M (oversized)"`.
- `max_price` (`float | None`) — maximum price (inclusive), or `None` to skip price filtering.

**Returns:** `list[dict]`. Each listing dict has the keys `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`. Empty list when nothing matches.

### `suggest_outfit(new_item, wardrobe) → str`

**Purpose:** Given a thrifted item and the user's wardrobe, produce 1–2 complete outfit suggestions that refer to the wardrobe pieces by name. Falls back to general styling advice when the wardrobe is empty.

**Inputs:**
- `new_item` (`dict`) — a listing dict (the item the user is considering buying).
- `wardrobe` (`dict`) — a wardrobe dict with an `items` key containing a list of wardrobe item dicts. May be empty.

**Returns:** A non-empty `str` with the LLM-generated outfit advice.

### `create_fit_card(outfit, new_item) → str`

**Purpose:** Generate a casual, shareable 2–4-sentence caption for the thrifted find — the kind of thing someone would post under an OOTD. Uses `temperature=1.0` so repeated calls on the same inputs produce varying captions.

**Inputs:**
- `outfit` (`str`) — the outfit suggestion string from `suggest_outfit()`.
- `new_item` (`dict`) — the listing dict for the thrifted item.

**Returns:** A `str` caption mentioning the item title, price, and platform naturally. If `outfit` is empty or whitespace-only, returns a descriptive error string instead.

---

## How the Planning Loop Works

`run_agent(query, wardrobe, max_reloop=3)` in `agent.py` is the entry point. Its behavior is not a fixed sequence — it branches on what `search_listings` returns and adapts.

1. **Parse the query.** `_parse_query()` uses regex to pull `description`, `size`, and `max_price` out of the natural-language input. Result is stored in `session["parsed"]`. No LLM call here; the patterns handle common phrasings like *"under $30"*, *"<$30"*, *"size M"*, *"in size 8"*.
2. **Search.** Call `search_listings(description, size, max_price)` with the current parameters.
3. **If results are non-empty:** break out of the loop. Set `session["selected_item"] = results[0]`, then call `suggest_outfit`, then `create_fit_card`. Both downstream tools read their inputs from the session, not from re-entered user input. Return the session.
4. **If results are empty:** increment `session["reloop_count"]`. If it exceeds `max_reloop`, write a message to `session["error"]` that names which filters were tried and relaxed, and return early — **do not** call `suggest_outfit` or `create_fit_card`.
5. **Otherwise loosen one constraint and retry.** `_loosen()` drops `max_price` first; on the next failure it drops `size`; if neither is left to drop, it bails with an informative error. Each drop is appended to `session["loosened"]` so the user (and the Gradio panel) sees what changed.

Because the dataset is deterministic, a plain retry would loop pointlessly — each retry actively widens the search instead, so the loop always converges on a match or a clean error.

The Architecture section of `planning.md` has an ASCII diagram showing every branch, including the error returns.

---

## State Management

Tools never pass data directly to one another — they communicate through a single `session` dict that lives for the duration of one `run_agent()` call. The schema (see `_new_session` in `agent.py`):

| Key | Written by | Read by |
|---|---|---|
| `query` | caller | — (kept for debugging / error messages) |
| `parsed` | `_parse_query` | the planning loop |
| `search_results` | `search_listings` step | the planning loop |
| `selected_item` | the planning loop (`= results[0]`) | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | caller | `suggest_outfit` |
| `outfit_suggestion` | `suggest_outfit` step | `create_fit_card` |
| `fit_card` | `create_fit_card` step | the Gradio handler |
| `reloop_count` | retry branch | retry branch (terminates the loop) |
| `loosened` | retry branch | error message + Gradio UI ("Relaxed: …") |
| `error` | any early-return branch | the Gradio handler |

This decoupling is what makes the loop testable. Each tool can be called in isolation with hand-built inputs (see `tests/test_tools.py`), and the planning loop can be reasoned about by inspecting which session keys are populated at each point. On a successful run the session ends with `selected_item`, `outfit_suggestion`, and `fit_card` all populated and `error is None`; on a failed run, `error` is set and the three output fields stay `None`.

---

## Error Handling

Every tool handles its own failure mode without raising. The planning loop adds a second layer of recovery for the search step.

| Tool | Failure mode | Agent response |
|---|---|---|
| `search_listings` | No listings match the query | Tool returns `[]`, never raises. The planning loop loosens one filter per retry (drop `max_price` → drop `size`) and records each drop in `session["loosened"]`. After `max_reloop` failed loosenings — or if no filters remain to relax — it sets `session["error"]` to a message naming what was tried, and returns *without* calling `suggest_outfit` or `create_fit_card`. |
| `suggest_outfit` | `wardrobe["items"]` is empty | Detects the empty list before prompting and switches to a "general styling advice" LLM prompt. Always returns a non-empty string. |
| `create_fit_card` | `outfit` is empty or whitespace-only | Guards before the LLM call and returns a descriptive error string (`[fit card unavailable] No outfit was provided for "<item title>" — run suggest_outfit first, then try again.`). Never raises, never sends a wasted LLM call. |

### Concrete example from testing

Running the milestone-5 verification command:

```bash
python agent.py
```

produces this output on the no-results path (query: `"designer ballgown size XXS under $5"`):

```
Parsed: {'description': 'designer ballgown', 'size': 'XXS', 'max_price': 5.0}
Loosened: ['price ceiling ($5)', 'size filter (XXS)']
Error: No listings matched "designer ballgown size XXS under $5" and there are no
filters left to relax. Try different keywords.
Fit card is None: True
```

The agent tried the full query, dropped the $5 price ceiling on retry 1, dropped the XXS size filter on retry 2, ran out of filters to relax on retry 3, and exited cleanly with `fit_card == None`. `suggest_outfit` and `create_fit_card` were never called with empty input.

For a *recovery* case, the query `"vintage graphic tee under $5"` triggers one retry: the $5 ceiling is dropped, the keyword search finds the Y2K Baby Tee, and the run completes successfully — the Gradio UI prefixes the listing panel with `(Relaxed: price ceiling ($5) to find a match.)` so the user understands what changed.

---

## Interaction Walkthrough

**User query:** *"I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"*

**Step 1 — `_parse_query`** *(not a tool, but the first thing the loop does)*
- Input: the raw user string.
- Output: `parsed = {"description": "looking for a vintage graphic tee", "size": None, "max_price": 30.0}`.
- The free-text mention of "baggy jeans and chunky sneakers" is *not* parsed as size/price — it describes the user's wardrobe, which is supplied separately via the Gradio UI ("Example wardrobe" radio button).

**Step 2 — `search_listings`**
- Tool: `search_listings`
- Input: `description="looking for a vintage graphic tee"`, `size=None`, `max_price=30.0`
- Why this tool: parsed query is now structured; this is the first concrete data we need.
- Output: a non-empty list of graphic-tee listings sorted by keyword relevance. Top hit: `"Y2K Baby Tee — Butterfly Print"`, $18, depop. Written to `session["search_results"]` and `session["selected_item"] = results[0]`. `reloop_count` stays at 0.

**Step 3 — `suggest_outfit`**
- Tool: `suggest_outfit`
- Input: `new_item=session["selected_item"]` (the Y2K Baby Tee), `wardrobe=session["wardrobe"]` (the example wardrobe).
- Why this tool: we have a candidate item and a non-empty wardrobe, so we can ask the LLM for outfits that combine the new piece with named wardrobe items.
- Output: a 4–6 sentence outfit suggestion that names specific wardrobe pieces (e.g., *"Pair the Y2K Baby Tee with the Baggy straight-leg jeans and Chunky white sneakers…"*). Written to `session["outfit_suggestion"]`.

**Step 4 — `create_fit_card`**
- Tool: `create_fit_card`
- Input: `outfit=session["outfit_suggestion"]`, `new_item=session["selected_item"]`.
- Why this tool: we have a complete outfit and want a shareable caption.
- Output: a 2–4 sentence Instagram-style caption naming the item, $18, and depop (e.g., *"Just scored the cutest Y2K Baby Tee on depop for $18…"*). Written to `session["fit_card"]`.

**Final output to user:** the Gradio UI populates three panels — *Top listing found* (formatted card with title, price, platform, size, condition, brand, colors, description), *Outfit idea* (the `outfit_suggestion`), and *Your fit card* (the `fit_card`).

---

## Spec Reflection

**One way `planning.md` helped during implementation:** Writing the tool table (parameter names, types, return values, failure modes) *before* writing any code made the AI-driven implementation in Milestone 3 dramatically faster. Each tool was specced in one place, so prompting Claude was a matter of pasting one block and saying "implement this." I caught the size-matching detail (`"M"` should match `"S/M"`) in the spec, which meant the generated `search_listings` handled it on the first try instead of needing a follow-up.

**One divergence from the spec, and why:** My original Error Handling table said `create_fit_card` would "create a fit card from the information it has" when the `outfit` string was empty. The actual implementation returns a descriptive error string (`[fit card unavailable] No outfit was provided…`) instead. I changed direction because the docstring already mandated "return a descriptive error message string — do NOT raise" *and* Milestone 5's verification command (`print(create_fit_card('', results[0]))`) expects an error-shaped string. Quietly fabricating a caption from `new_item` alone would have hidden the upstream failure (empty `outfit`) instead of surfacing it, which is the wrong behavior for an agent trying to fail loudly and helpfully. I updated `planning.md`'s error-handling table to match.

---

## AI Usage

**1. Gemini Pro — understanding the minimal-example agent diagram (Milestone 2)**

I gave Gemini Pro the planning loop ASCII diagram provided in the project instructions and asked it to explain what the pattern was doing and how the session state worked. Gemini walked me through how the sequential pipeline differs from a ReAct loop, explained that the `results=[]` branch is an error gate that prevents wasted downstream calls, and suggested three ways to extend the pattern (HITL pause, evaluator node, dynamic planner LLM). I used this to tighten the Planning Loop section of `planning.md` before writing any code — specifically the idea of making every retry actively widen the search rather than repeating the same call.

**2. Claude Code — spec-driven `tools.py` implementation (Milestone 3)**

I gave Claude Code the three tool blocks from `planning.md` (inputs, return value, failure mode) and the `tools.py` docstrings, and asked it to implement each tool one at a time, raising questions before writing rather than guessing. The initial `search_listings` scorer used a fuzzy substring fallback that matched 30 of 40 listings for `"vintage graphic tee"` — too loose. I directed Claude to tighten it to exact token matches plus a length-≥5 prefix-overlap bonus, which brought relevant tees to the top. I also overrode the default `create_fit_card` behavior: Claude's first implementation would have fabricated a caption from item data alone when `outfit` was empty, but I redirected it to return a descriptive error string to match the docstring and Milestone 5's test expectation.

---