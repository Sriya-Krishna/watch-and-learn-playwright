"""
Script executor: runs LLM-generated Python in a Playwright browser.

The executor:
1. Launches a headless Chromium browser
2. exec()'s the script code to extract the `run` function
3. Calls run(page, params) with a timeout
4. Captures screenshot + DOM on failure for self-heal context
5. Cleans up browser resources
"""

import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from playwright.sync_api import sync_playwright

from config import PLAYWRIGHT_HEADLESS, PLAYWRIGHT_TIMEOUT, SCRIPT_STORAGE_PATH


def execute_script(script_code: str, params: dict | None = None,
                   timeout: int | None = None,
                   script_id: str | None = None) -> dict:
    """
    Execute a Playwright script and return the result.

    Returns:
        On success: {"status": "success", "data": [...], "duration_seconds": float}
        On failure: {"status": "error", "error": str, "duration_seconds": float,
                     "screenshot_path": str|None, "dom_snapshot": str|None}
    """
    params = params or {}
    timeout_ms = timeout or PLAYWRIGHT_TIMEOUT
    timeout_s = timeout_ms / 1000

    # Compile and extract the run() function
    try:
        namespace = {}
        exec(compile(script_code, "<script>", "exec"), namespace)
    except SyntaxError as e:
        return {
            "status": "error",
            "error": f"Script syntax error: {e}",
            "duration_seconds": 0,
            "screenshot_path": None,
            "dom_snapshot": None,
        }

    run_fn = namespace.get("run")
    if not callable(run_fn):
        return {
            "status": "error",
            "error": "Script does not define a callable `run(page, params)` function",
            "duration_seconds": 0,
            "screenshot_path": None,
            "dom_snapshot": None,
        }

    # Execute in Playwright browser
    start = time.time()
    playwright = None
    browser = None
    page = None
    screenshot_path = None
    dom_snapshot = None

    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        # Run the script function with a timeout
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_fn, page, params)
            try:
                result = future.result(timeout=timeout_s)
            except FuturesTimeout:
                raise TimeoutError(f"Script execution timed out after {timeout_s}s")

        duration = time.time() - start

        # Validate result format
        if not isinstance(result, dict) or "status" not in result:
            return {
                "status": "error",
                "error": f"Script returned invalid result (expected dict with 'status' key, got {type(result).__name__})",
                "duration_seconds": duration,
                "screenshot_path": None,
                "dom_snapshot": None,
            }

        if result["status"] == "success":
            return {
                "status": "success",
                "data": result.get("data", []),
                "duration_seconds": round(duration, 2),
            }
        else:
            # Script returned an error itself
            return {
                "status": "error",
                "error": result.get("error", "Unknown script error"),
                "duration_seconds": round(duration, 2),
                "screenshot_path": None,
                "dom_snapshot": None,
            }

    except Exception as e:
        duration = time.time() - start
        error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

        # Capture screenshot and DOM for heal context
        if page:
            try:
                if script_id:
                    ss_dir = os.path.join(SCRIPT_STORAGE_PATH, script_id)
                    os.makedirs(ss_dir, exist_ok=True)
                    screenshot_path = os.path.join(ss_dir, f"error_{int(time.time())}.png")
                    page.screenshot(path=screenshot_path, full_page=True)
                dom_snapshot = page.content()
            except Exception:
                pass  # page may already be in a bad state

        return {
            "status": "error",
            "error": error_msg,
            "duration_seconds": round(duration, 2),
            "screenshot_path": screenshot_path,
            "dom_snapshot": dom_snapshot,
        }

    finally:
        try:
            if page:
                page.close()
            if browser:
                browser.close()
            if playwright:
                playwright.stop()
        except Exception:
            pass
