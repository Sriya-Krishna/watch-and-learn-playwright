"""
Self-heal orchestration.

When a script fails, the healer:
1. Loads script context (code, intent, extract_schema)
2. Sends error + DOM + screenshot to LLM for patching
3. Saves the patched version and retries execution
4. Repeats up to MAX_HEAL_ATTEMPTS times
5. Logs all heal attempts to SQLite
"""

from config import MAX_HEAL_ATTEMPTS
from generator import generate_heal
from executor import execute_script
import storage


def attempt_heal(script_id: str, original_error: str,
                 dom_snapshot: str | None,
                 screenshot_path: str | None,
                 provider: str | None = None) -> dict:
    """
    Attempt to heal a failing script.

    Returns:
        On success: {"status": "success", "data": [...], "metadata": {...}}
        On failure: {"status": "failed", "error": str, "heal_history": [...]}
    """
    meta = storage.get_script(script_id)
    if not meta:
        return {"status": "failed", "error": f"Script {script_id} not found", "heal_history": []}

    ctx = storage.get_script_context(script_id)
    intent = ctx["intent"]
    extract_schema = ctx["extract_schema"]

    current_version = meta["current_version"]
    current_code = storage.get_script_code(script_id)
    current_error = original_error
    current_dom = dom_snapshot

    storage.update_script_status(script_id, "healing")
    heal_history = []

    for attempt in range(MAX_HEAL_ATTEMPTS):
        print(f"[Healer] Attempt {attempt + 1}/{MAX_HEAL_ATTEMPTS} for script {script_id}")

        # Generate healed script
        try:
            healed_code = generate_heal(
                script_code=current_code,
                error=current_error,
                dom_snapshot=current_dom,
                intent=intent,
                extract_schema=extract_schema,
                provider=provider,
            )
        except Exception as e:
            print(f"[Healer] LLM heal generation failed: {e}")
            heal_history.append({
                "version": current_version + 1,
                "reason": f"LLM generation failed: {e}",
                "result": "failed",
            })
            continue

        # Save new version
        new_version = current_version + 1
        storage.save_new_version(script_id, healed_code, new_version)

        # Execute healed script
        result = execute_script(healed_code, params={}, script_id=script_id)

        if result["status"] == "success":
            # Heal succeeded
            storage.log_heal(
                script_id, current_version, new_version,
                current_error, f"Healed on attempt {attempt + 1}", success=True
            )
            storage.log_execution(
                script_id, new_version, success=True,
                duration=result["duration_seconds"],
                items=len(result.get("data", [])),
                error=None, healed=True
            )
            storage.update_script_status(script_id, "ready")

            heal_history.append({
                "version": new_version,
                "reason": "Script healed successfully",
                "result": "success",
            })

            return {
                "status": "success",
                "data": result.get("data", []),
                "metadata": {
                    "items_extracted": len(result.get("data", [])),
                    "duration_seconds": result["duration_seconds"],
                    "script_version": new_version,
                    "healed": True,
                    "heal_reason": f"Auto-healed on attempt {attempt + 1}",
                },
            }
        else:
            # Heal attempt failed — capture new context for next attempt
            storage.log_heal(
                script_id, current_version, new_version,
                current_error, f"Heal attempt {attempt + 1} failed: {result['error'][:200]}",
                success=False
            )
            heal_history.append({
                "version": new_version,
                "reason": result["error"][:200],
                "result": "failed",
            })
            current_version = new_version
            current_code = healed_code
            current_error = result["error"]
            current_dom = result.get("dom_snapshot")

    # All heal attempts exhausted
    storage.update_script_status(script_id, "failed")
    storage.log_execution(
        script_id, current_version, success=False,
        duration=0, items=None,
        error=f"Failed after {MAX_HEAL_ATTEMPTS} heal attempts",
        healed=True
    )

    return {
        "status": "failed",
        "error": f"Script failed after {MAX_HEAL_ATTEMPTS} heal attempts",
        "last_error": current_error[:500] if current_error else None,
        "heal_history": heal_history,
        "suggestion": "The target website may have changed significantly. Consider re-recording the workflow.",
    }
