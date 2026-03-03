"""
Playwright Browser Automation Microservice.

Standalone FastAPI service that generates, stores, executes,
and self-heals Playwright scripts. n8n calls this via HTTP Request nodes.
"""

import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import PLAYWRIGHT_SERVICE_PORT
import storage
from generator import generate_script
from executor import execute_script
from healer import attempt_heal


app = FastAPI(title="Playwright Automation Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    storage.init_db()
    print(f"[Playwright Service] Database initialized")
    print(f"[Playwright Service] Running on port {PLAYWRIGHT_SERVICE_PORT}")


# ── Request Models ───────────────────────────────────────────


class GenerateRequest(BaseModel):
    taskId: str
    intent: dict
    recording: list
    extract_schema: dict | None = None
    config: dict | None = None


class ExecuteRequest(BaseModel):
    params: dict | None = None


# ── Endpoints ────────────────────────────────────────────────


@app.post("/scripts/generate")
async def generate(req: GenerateRequest):
    """Generate a Playwright script from intent + recording."""
    script_id = str(uuid.uuid4())

    try:
        code = generate_script(
            intent=req.intent,
            recording=req.recording,
            extract_schema=req.extract_schema,
            config=req.config,
        )
    except SyntaxError as e:
        raise HTTPException(status_code=422, detail=f"LLM generated invalid Python after retry: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Script generation failed: {e}")

    storage.create_script(
        script_id=script_id,
        task_id=req.taskId,
        intent=req.intent,
        extract_schema=req.extract_schema,
        config=req.config,
        recording=req.recording,
        code=code,
    )

    return {
        "scriptId": script_id,
        "status": "ready",
        "endpoint": f"/scripts/{script_id}/execute",
        "version": 1,
    }


@app.post("/scripts/{script_id}/execute")
async def execute(script_id: str, req: ExecuteRequest | None = None):
    """Execute a stored script. Triggers self-heal on failure."""
    meta = storage.get_script(script_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Script {script_id} not found")

    code = storage.get_script_code(script_id)
    if not code:
        raise HTTPException(status_code=404, detail=f"Script file not found on disk")

    params = req.params if req else {}
    result = execute_script(code, params=params, script_id=script_id)

    if result["status"] == "success":
        # Log successful execution
        storage.log_execution(
            script_id=script_id,
            version=meta["current_version"],
            success=True,
            duration=result["duration_seconds"],
            items=len(result.get("data", [])),
            error=None,
        )
        return {
            "status": "success",
            "data": result.get("data", []),
            "metadata": {
                "items_extracted": len(result.get("data", [])),
                "duration_seconds": result["duration_seconds"],
                "script_version": meta["current_version"],
            },
        }

    # Execution failed — attempt self-heal
    print(f"[Service] Script {script_id} failed, triggering self-heal...")
    storage.log_execution(
        script_id=script_id,
        version=meta["current_version"],
        success=False,
        duration=result["duration_seconds"],
        items=None,
        error=result["error"][:500],
    )

    heal_result = attempt_heal(
        script_id=script_id,
        original_error=result["error"],
        dom_snapshot=result.get("dom_snapshot"),
        screenshot_path=result.get("screenshot_path"),
    )

    if heal_result["status"] == "success":
        return heal_result

    # Self-heal failed
    return JSONResponse(status_code=500, content=heal_result)


@app.get("/scripts/{script_id}")
async def get_script(script_id: str):
    """Get script details and stats."""
    meta = storage.get_script(script_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Script {script_id} not found")

    code = storage.get_script_code(script_id)
    stats = storage.get_script_stats(script_id)

    return {
        "scriptId": meta["script_id"],
        "taskId": meta["task_id"],
        "status": meta["status"],
        "current_version": meta["current_version"],
        "created_at": meta["created_at"],
        "updated_at": meta["updated_at"],
        "success_rate": stats["success_rate"],
        "total_executions": stats["total_executions"],
        "total_heals": stats["total_heals"],
        "script_code": code,
    }


@app.get("/scripts/{script_id}/history")
async def get_script_history(script_id: str):
    """Get execution and heal history."""
    meta = storage.get_script(script_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Script {script_id} not found")

    history = storage.get_script_history(script_id)
    return history


@app.delete("/scripts/{script_id}")
async def delete_script(script_id: str):
    """Delete a script and all its history."""
    meta = storage.get_script(script_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Script {script_id} not found")

    storage.delete_script(script_id)
    return JSONResponse(status_code=204, content=None)


@app.get("/scripts")
async def list_scripts():
    """List all scripts."""
    return storage.list_scripts()


@app.get("/health")
async def health():
    """Service health check."""
    pw_ok = False
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        browser.close()
        pw.stop()
        pw_ok = True
    except Exception as e:
        print(f"[Health] Playwright check failed: {e}")

    return {
        "status": "healthy" if pw_ok else "degraded",
        "playwright": pw_ok,
        "database": True,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PLAYWRIGHT_SERVICE_PORT)
