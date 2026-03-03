"""
Script generation and heal prompt logic.
Builds prompts from intent + recording, calls LLM, validates syntax.
"""

import json

from llm import call_llm

# ── System Prompts ───────────────────────────────────────────

SCRIPT_GENERATION_PROMPT = """You are a Playwright automation script generator. You receive:
1. A user's intent — what they want automated
2. A recording — the actual browser events captured while the user did the task manually
3. An extract schema — what data fields to return

Your job is to write a complete, executable Python script using Playwright that replicates what the user did and extracts the specified data.

Output ONLY the Python script. No explanation, no markdown fences, just the code.

Requirements:
1. Use playwright.sync_api (synchronous Playwright)
2. The script must define a single function called `run(page, params)` that:
   - `page` is a Playwright Page object (already created by the executor — do NOT create a browser or page yourself)
   - `params` is a dict with dynamic values (search terms, URLs, etc.)
   - Returns {"status": "success", "data": [...]} where data is a list of dicts matching the extract schema
   - Returns {"status": "error", "error": "description"} on failure
3. Do NOT import playwright, create a browser, or create a page. The `page` argument is already a live Playwright page. Just use it directly.
4. You may import standard library modules (json, re, time, etc.) at the top of the script.
5. Use the recording events as your primary reference for navigation flow, selectors, and interaction patterns. The recording shows exactly what the user clicked, typed, and navigated to.
6. Prefer robust selectors in this priority order:
   - data-testid, aria-label, role attributes
   - Text content matching (page.get_by_text(), page.get_by_role())
   - CSS selectors with semantic class names
   - XPath only as last resort
7. Add reasonable timeouts and wait conditions. Web pages load asynchronously. Use page.wait_for_selector() or page.wait_for_load_state() where appropriate.
8. Handle common annoyances: cookie banners, notification popups, consent dialogs. Dismiss them if encountered using try/except.
9. If the task involves repeating across multiple items (e.g., multiple job listings), implement the loop with a configurable max_items from params (default to 10 if not provided).
10. Add try/except around fragile operations. Return partial data with an error note rather than crashing entirely.
11. Do not hardcode credentials or login steps. If the task requires authentication, the script should check if already logged in and raise a clear error if not.
12. Include brief comments explaining the key steps so the heal system can understand the script's structure.

Example output format:

import re

def run(page, params):
    max_items = params.get("max_items", 10)

    # Navigate to the target page
    page.goto("https://example.com")
    page.wait_for_load_state("networkidle")

    # Extract data
    data = []
    items = page.query_selector_all(".item")
    for item in items[:max_items]:
        title = item.query_selector(".title")
        data.append({
            "title": title.inner_text() if title else None,
        })

    return {"status": "success", "data": data}
"""

HEAL_PROMPT = """You are a Playwright script debugger and fixer. A previously working automation script has failed. You receive:
1. The failing script code
2. The error message and stack trace
3. The current page DOM (may be truncated)
4. The original intent and extract schema

Your job is to diagnose why the script failed and produce a fixed version.

Output ONLY the complete fixed Python script. No explanation, no markdown fences, just the code.

Common failure patterns and fixes:
- Selector changed: the website updated its CSS/HTML. Find the equivalent element using the DOM.
- Page layout changed: navigation flow is different. Adapt the script to the new flow.
- Timing issue: page loads slower. Add longer waits or wait for specific elements.
- New popup/modal: cookie consent, newsletter signup, login prompt. Add dismissal logic.
- Anti-bot detection: the site blocked the automation. Add stealth measures (slower interactions, random delays).
- Content structure changed: the data is still there but in different HTML elements. Update extraction logic.

Rules:
1. Keep the same function signature: run(page, params)
2. Keep the same output schema — the caller expects the same data format
3. Make minimal changes. Don't rewrite the entire script if only one selector broke.
4. Add a comment "# HEALED: [reason]" next to each line you changed
5. Do NOT import playwright, create a browser, or create a page. The `page` argument is already a live Playwright page.
6. If you cannot determine the fix from the available information, return the original script unchanged with a comment "# HEAL_FAILED: [reason]" at the top
"""


# ── Prompt Building ──────────────────────────────────────────


def build_generation_message(intent: dict, recording: list,
                             extract_schema: dict | None,
                             config: dict | None) -> str:
    """Build the user message for script generation."""
    parts = [
        "## Intent",
        json.dumps(intent, indent=2),
        "",
        "## Recording (browser events captured during manual execution)",
        json.dumps(recording, indent=2),
    ]
    if extract_schema:
        parts += ["", "## Extract Schema", json.dumps(extract_schema, indent=2)]
    if config:
        parts += ["", "## Configuration", json.dumps(config, indent=2)]
    return "\n".join(parts)


def build_heal_message(script_code: str, error: str,
                       dom_snapshot: str | None,
                       intent: dict,
                       extract_schema: dict | None) -> str:
    """Build the user message for script healing."""
    parts = [
        "## Failing Script",
        "```python",
        script_code,
        "```",
        "",
        "## Error",
        error,
    ]
    if dom_snapshot:
        # Truncate DOM to ~50KB to fit in context
        truncated = dom_snapshot[:50000]
        if len(dom_snapshot) > 50000:
            truncated += "\n... [DOM truncated] ..."
        parts += ["", "## Current Page DOM", truncated]
    parts += ["", "## Original Intent", json.dumps(intent, indent=2)]
    if extract_schema:
        parts += ["", "## Expected Output Schema", json.dumps(extract_schema, indent=2)]
    return "\n".join(parts)


# ── Generation Functions ─────────────────────────────────────


def generate_script(intent: dict, recording: list,
                    extract_schema: dict | None = None,
                    config: dict | None = None,
                    provider: str | None = None) -> str:
    """Generate a Playwright script from intent + recording.
    Returns the Python code as a string.
    Validates syntax and retries once on failure."""
    user_msg = build_generation_message(intent, recording, extract_schema, config)
    code = call_llm(SCRIPT_GENERATION_PROMPT, user_msg, provider)

    # Validate syntax
    try:
        compile(code, "<generated_script>", "exec")
        return code
    except SyntaxError as e:
        print(f"[Generator] Syntax error in generated script: {e}")
        # Retry with error context
        retry_msg = (
            f"{user_msg}\n\n"
            f"## IMPORTANT: Your previous attempt had a syntax error:\n"
            f"{e}\n\n"
            f"Please fix the syntax and output the corrected script."
        )
        code = call_llm(SCRIPT_GENERATION_PROMPT, retry_msg, provider)
        compile(code, "<generated_script>", "exec")  # let it raise if still broken
        return code


def generate_heal(script_code: str, error: str,
                  dom_snapshot: str | None,
                  intent: dict,
                  extract_schema: dict | None = None,
                  provider: str | None = None) -> str:
    """Generate a healed version of a failing script.
    Returns the patched Python code as a string."""
    user_msg = build_heal_message(script_code, error, dom_snapshot, intent, extract_schema)
    code = call_llm(HEAL_PROMPT, user_msg, provider)

    # Validate syntax
    try:
        compile(code, "<healed_script>", "exec")
        return code
    except SyntaxError as e:
        print(f"[Healer] Syntax error in healed script: {e}")
        retry_msg = (
            f"{user_msg}\n\n"
            f"## IMPORTANT: Your previous fix had a syntax error:\n"
            f"{e}\n\n"
            f"Please fix the syntax and output the corrected script."
        )
        code = call_llm(HEAL_PROMPT, retry_msg, provider)
        compile(code, "<healed_script>", "exec")
        return code
