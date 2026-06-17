# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Searches the mock listings dataset for items matching the description, optional size, and optional price ceiling. Returns the list of matched listings.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `description` (str): Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
- `size` (str): Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
- `max_price` (float): Maximum price (inclusive), or None to skip price filtering.

**What it returns:**
<!-- Describe the return value — what fields does a result contain? -->
A list of matching listing dicts, sorted by relevance (best match first).

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->
Returns an empty list if nothing matches — does NOT raise an exception.

---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Given a thrifted item and the user's wardrobe, suggests 1–2 complete outfits.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): A listing dict (the item the user is considering buying).
- `wardrobe` (dict): A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

**What it returns:**
<!-- Describe the return value -->
A non-empty string with outfit suggestions.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->
If the wardrobe is empty, offer general styling advice for the item rather than raising an exception or returning an empty string.

---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->

Generates a short, shareable outfit caption for the thrifted find.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->

- `outfit` (str): The outfit suggestion string from suggest_outfit().
- `new_item` (dict): The listing dict for the thrifted item.

**What it returns:**
<!-- Describe the return value -->

A 2–4 sentence string usable as an Instagram/TikTok caption.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->

If outfit is empty or missing, return a descriptive error message string — does NOT raise an exception.
---

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

This planning loop uses a resilient "retry with fallback" architecture so the agent does not break when the first search comes back empty. The agent watches the user's parsed search parameters, the result of each `search_listings` call, and its session memory — specifically a `reloop_count` and a `loosened` trail recording which filters have already been relaxed. Its behavior shifts entirely based on whether the current search finds an item.

Concrete branches:

1. **Parse the query** — extract `description`, `size`, and `max_price` from the natural-language input using regex (see `_parse_query` in `agent.py`). Store the result in `session["parsed"]`.
2. **Call `search_listings`** with the current params.
3. **If results are non-empty:** break out of the loop. Set `session["selected_item"] = results[0]`, then call `suggest_outfit`, then call `create_fit_card` — both read state from the session rather than from re-entered user input. Return the session.
4. **If results are empty:** increment `reloop_count`. If it exceeds `max_reloop`, set `session["error"]` to a message that names which filters were relaxed and return early — do NOT call `suggest_outfit` or `create_fit_card`.
5. **Otherwise, loosen one constraint** (in order: drop `max_price` first, then drop `size`), append what was dropped to `session["loosened"]`, and loop back to step 2. If no filter is left to relax, return with an informative error.

A plain retry would loop pointlessly because the dataset is deterministic — each retry actively widens the search instead, so the loop converges on either a match or a clean error. This design also satisfies the "Retry logic with fallback" stretch feature.

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

Information is passed between tools using a centralized Session State, which acts as the agent's short-term memory throughout its entire execution loop. Instead of tools passing data directly to one another in a rigid chain, they independently read from and write to this shared state. This session tracks everything the agent needs to orient itself, including the user's initial context and parameters, raw data pulled from external tools, internal LLM generations like styling advice, and control variables like your retry counter. The progression of data relies on a continuous read and write cycle: when a tool like your search function successfully finishes, it writes its results into the session memory rather than handing them straight to the next step. Then, when the outfit suggestion tool is triggered, it reads that saved item directly from the session, uses it to generate new advice, and writes its own output back into the shared state. By decoupling the tools and forcing them to communicate exclusively through this central memory, the pipeline remains incredibly stable, ensuring that if a step fails, the agent still has access to all previously saved data to attempt a recovery.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Tool returns `[]` (never raises). The planning loop loosens one constraint per retry (drop `max_price` → drop `size`), recording each step in `session["loosened"]`. If `reloop_count > max_reloop` or there are no filters left to relax, it sets `session["error"]` to a message naming what was tried and returns early without calling `suggest_outfit`/`create_fit_card`. |
| suggest_outfit | Wardrobe is empty | Detects `wardrobe["items"] == []` and routes to a "general styling advice" LLM prompt instead of the wardrobe-pairing prompt. Always returns a non-empty string. |
| create_fit_card | Outfit input is missing or incomplete | Guards against an empty or whitespace-only `outfit` string and returns a descriptive error string (e.g., `[fit card unavailable] No outfit was provided for "<item title>" — run suggest_outfit first, then try again.`). Never raises. |

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     Use ASCII art or a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html).
     Do NOT embed an image — graders need to read your diagram directly in the file;
     an embedded image or screenshot cannot be evaluated.
     You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->

```text
User query
    │
    ▼
_parse_query → Session: parsed = {description, size, max_price}
    │
    ▼
Planning Loop (reloop_count = 0, loosened = []) ◄────────────────────────┐
    │                                                                    │
    ├─► search_listings(description, size, max_price)                    │
    │       │                                                            │
    │       │ results == []                                              │
    │       ├──► reloop_count += 1                                       │
    │       │       │                                                    │
    │       │       ├──► reloop_count > max_reloop ──► [ERROR] return    │
    │       │       │                                                    │
    │       │       └──► _loosen(params): drop max_price, else drop size │
    │       │              │                                             │
    │       │              ├──► nothing left to drop ──► [ERROR] return  │
    │       │              │                                             │
    │       │              └──► Session: loosened.append(<what>) ────────┘
    │       │
    │       │ results == [item, ...]
    │       ▼
    │   Session: search_results = results
    │   Session: selected_item  = results[0]
    │       │
    ├─► suggest_outfit(selected_item, wardrobe)
    │       │   (reads selected_item + wardrobe from Session)
    │       │   (if wardrobe['items'] == []: LLM general-advice prompt)
    │   Session: outfit_suggestion = "..."
    │       │
    └─► create_fit_card(outfit_suggestion, selected_item)
            │   (reads outfit_suggestion + selected_item from Session)
            │   (if outfit blank: return error string, no LLM call)
        Session: fit_card = "..."
            │
            ▼
        Return session
```

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**
I will do spec-driven coding through Claude Code to complete each tool and specifically review the code to see how the failure modes are or can be handled. I will ask it to reference requirements.txt and the docstrings, and I will ask it to question me about anything vague before writing the code. I will write out the test cases using Claude Code.

**Milestone 4 — Planning loop and state management:**
I will again use Claude Code (in tandem with Gemini Pro if needed) to generate user queries to test accuracy of the state management of my agent.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 0 — parse:**
`_parse_query("I'm looking for a vintage graphic tee under $30...")` runs the regex parser and writes into Session: `parsed = {"description": "looking for a vintage graphic tee", "size": None, "max_price": 30.0}`. The free-text mention of "baggy jeans and chunky sneakers" is not parsed — the user's actual wardrobe is selected separately (the example wardrobe in the Gradio UI).

**Step 1 — search:**
`search_listings(description="looking for a vintage graphic tee", size=None, max_price=30.0)` is called. It returns a non-empty list of graphic-tee listings sorted by keyword relevance. The top hit (e.g., "Y2K Baby Tee — Butterfly Print, $18") is written to `Session.selected_item`. No retry needed; `reloop_count` stays at 0.

**Step 2 — suggest_outfit:**
`suggest_outfit(new_item=Session.selected_item, wardrobe=Session.wardrobe)` is called. The wardrobe is the example-wardrobe dict (containing "Baggy straight-leg jeans, dark wash" and "Chunky white sneakers" among others). The tool sends the item + named wardrobe pieces to Groq and writes the response to `Session.outfit_suggestion`.

**Step 3 — create_fit_card:**
`create_fit_card(outfit=Session.outfit_suggestion, new_item=Session.selected_item)` is called. The outfit string is non-empty, so the tool builds a casual-caption prompt with the item title, price, and platform and asks Groq for a 2–4 sentence caption at `temperature=1.0`. The result is written to `Session.fit_card` and the session is returned to the Gradio handler.

**Final output to user:**
<!-- What does the user actually see at the end? -->
Your New Fit: Faded 90s Skater Graphic Tee\n**Price:** $24.50\n\n**How to wear it:**\nThe washed charcoal color of the tee will pair perfectly with your baggy jeans for a classic Y2K streetwear silhouette. Let the tee drape naturally untucked, and let your chunky sneakers anchor the oversized proportions.

