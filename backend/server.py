import json
import os
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from validator import validate_workflow

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()

app = FastAPI(title="Workflow Interpreter")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the selected provider client
if LLM_PROVIDER == "openai":
    from openai import OpenAI
    client = OpenAI()
elif LLM_PROVIDER == "kimi":
    import httpx
    NVIDIA_API_KEY = os.getenv("NVIDIA_API")
    NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
else:
    import anthropic
    client = anthropic.Anthropic()

# In-memory session store
sessions: dict[str, dict[str, Any]] = {}

LLM_MODELS = {
    "anthropic": "Claude Sonnet (claude-sonnet-4-20250514)",
    "openai": "GPT-4o",
    "kimi": "Kimi K2.5 (moonshotai/kimi-k2.5)",
}

LLM_MODEL_DISPLAY = LLM_MODELS.get(LLM_PROVIDER, LLM_PROVIDER)

# n8n instance config
N8N_HOST = os.getenv("N8N_HOST", "http://localhost:5678")
N8N_API_KEY = os.getenv("N8N_API_KEY", "")

SYSTEM_PROMPT = """You are an automation intent interpreter. You receive a JSON array of recorded web browser events captured while a user performed a task manually. Your job is to:

1. FIRST, analyze the full event sequence and extract the structural intent — what apps are involved, what data moves, in what order, what fields matter, where things end up. Extract maximum understanding from the evidence before asking anything.

2. Produce a structured intent object as valid JSON (no markdown, no code fences, just raw JSON):
{
  "intent_summary": "Plain English description of what the user wants automated",
  "trigger": {
    "description": "What kicks off this workflow",
    "app": "The source application",
    "event": "The triggering event type",
    "confidence": 0-1
  },
  "steps": [
    {
      "order": 1,
      "action": "What happens at this step",
      "app": "Which application",
      "operation": "Specific operation (read, write, update, send, etc.)",
      "data_fields": ["Which data fields are involved"],
      "confidence": 0-1
    }
  ],
  "data_flow": {
    "source_fields": ["Fields extracted from source"],
    "destination_fields": ["Fields written to destination"],
    "transformations": ["Any data transformations observed"]
  },
  "conditions": {
    "observed": ["Conditions visible in the recording"],
    "inferred": ["Conditions the LLM suspects but aren't confirmed"]
  },
  "unresolved_questions": [
    {
      "id": "q1",
      "question": "The clarifying question in plain, outcome-oriented language",
      "why": "Why this question matters for the automation",
      "options": ["Suggested answers if applicable"]
    }
  ],
  "overall_confidence": 0-1
}

3. Rules:
- Extract at least 70% of the intent from the recording evidence alone. Lean heavily on what you observe before asking questions.
- Frame all clarifying questions in outcome-oriented language, not technical jargon. Say "Do you want this to happen only for emails from new contacts?" not "Should the trigger filter on sender address uniqueness?"
- Keep unresolved_questions to a maximum of 3-5. Prioritize the most impactful unknowns.
- If you're fairly confident about something, state it in the intent and don't ask. Only ask about things that genuinely change the workflow structure or behavior.
- The user is non-technical. Write everything as if explaining to someone who has never seen an automation tool.
- IMPORTANT: Return ONLY the JSON object. No explanatory text, no markdown formatting."""


GENERATOR_PROMPT = """You are an n8n workflow generator. You receive a confirmed intent object describing what automation the user wants, and you produce a valid n8n workflow JSON that implements it.

You must output ONLY valid JSON (no markdown, no code fences, no explanatory text). The JSON must be a complete n8n workflow object.

## n8n Workflow JSON Structure

The workflow JSON has this top-level structure:
{
  "name": "Workflow Name",
  "nodes": [...],
  "connections": {...},
  "settings": { "executionOrder": "v1" }
}

### Node Structure
Each node in the "nodes" array:
{
  "parameters": { ... node-specific parameters ... },
  "name": "Human-readable name",
  "type": "n8n-nodes-base.nodeType",
  "typeVersion": 1,
  "position": [x, y]
}

### Connection Structure
Connections map source node names to their outputs:
{
  "Source Node Name": {
    "main": [
      [
        { "node": "Target Node Name", "type": "main", "index": 0 }
      ]
    ]
  }
}

## Common n8n Node Types Reference

| App / Function | Node Type | Trigger Type | typeVersion |
|---|---|---|---|
| Gmail (read) | n8n-nodes-base.gmail | n8n-nodes-base.gmailTrigger | 2 / 1 |
| Google Sheets | n8n-nodes-base.googleSheets | n8n-nodes-base.googleSheetsTrigger | 4 / 1 |
| Slack | n8n-nodes-base.slack | n8n-nodes-base.slackTrigger | 2 / 1 |
| HTTP Request | n8n-nodes-base.httpRequest | — | 4 |
| Webhook | — | n8n-nodes-base.webhook | 2 |
| IF condition | n8n-nodes-base.if | — | 2 |
| Set / Map data | n8n-nodes-base.set | — | 3 |
| Code / Function | n8n-nodes-base.code | — | 2 |
| Schedule | — | n8n-nodes-base.scheduleTrigger | 1 |
| Email (IMAP) | — | n8n-nodes-base.emailReadImap | 2 |
| Microsoft Outlook | n8n-nodes-base.microsoftOutlook | n8n-nodes-base.microsoftOutlookTrigger | 2 / 1 |
| Notion | n8n-nodes-base.notion | n8n-nodes-base.notionTrigger | 2 / 1 |
| Airtable | n8n-nodes-base.airtable | n8n-nodes-base.airtableTrigger | 2 / 1 |
| Trello | n8n-nodes-base.trello | n8n-nodes-base.trelloTrigger | 1 / 1 |
| HubSpot | n8n-nodes-base.hubspot | n8n-nodes-base.hubspotTrigger | 2 / 1 |
| Telegram | n8n-nodes-base.telegram | n8n-nodes-base.telegramTrigger | 1 / 1 |
| Discord | n8n-nodes-base.discord | — | 2 |
| Google Drive | n8n-nodes-base.googleDrive | n8n-nodes-base.googleDriveTrigger | 3 / 1 |
| Manual trigger | — | n8n-nodes-base.manualTrigger | 1 |
| Merge | n8n-nodes-base.merge | — | 3 |
| Split Out | n8n-nodes-base.splitOut | — | 1 |
| No Operation | n8n-nodes-base.noOp | — | 1 |

## Example Workflow (Gmail Trigger → Set → Google Sheets)

{
  "name": "Gmail to Google Sheets",
  "nodes": [
    {
      "parameters": {
        "pollTimes": { "item": [{ "mode": "everyMinute" }] },
        "filters": {}
      },
      "name": "Gmail Trigger",
      "type": "n8n-nodes-base.gmailTrigger",
      "typeVersion": 1,
      "position": [250, 300],
      "credentials": { "gmailOAuth2": { "id": "", "name": "" } }
    },
    {
      "parameters": {
        "assignments": {
          "assignments": [
            { "id": "1", "name": "sender", "value": "={{ $json.from.value[0].address }}", "type": "string" },
            { "id": "2", "name": "subject", "value": "={{ $json.subject }}", "type": "string" },
            { "id": "3", "name": "date", "value": "={{ $json.date }}", "type": "string" }
          ]
        }
      },
      "name": "Map Fields",
      "type": "n8n-nodes-base.set",
      "typeVersion": 3,
      "position": [450, 300]
    },
    {
      "parameters": {
        "operation": "append",
        "documentId": { "__rl": true, "value": "", "mode": "list" },
        "sheetName": { "__rl": true, "value": "", "mode": "list" },
        "columns": { "mappingMode": "autoMapInputData", "value": {} }
      },
      "name": "Google Sheets",
      "type": "n8n-nodes-base.googleSheets",
      "typeVersion": 4,
      "position": [650, 300],
      "credentials": { "googleSheetsOAuth2Api": { "id": "", "name": "" } }
    }
  ],
  "connections": {
    "Gmail Trigger": { "main": [[{ "node": "Map Fields", "type": "main", "index": 0 }]] },
    "Map Fields": { "main": [[{ "node": "Google Sheets", "type": "main", "index": 0 }]] }
  },
  "settings": { "executionOrder": "v1" }
}

## Rules

1. Always include a trigger node as the FIRST node in the nodes array.
2. Position nodes left-to-right: start at [250, 300], add 200px horizontally for each subsequent node.
3. Wire ALL connections correctly. Every non-trigger node must have an incoming connection.
4. Include Set nodes for data transformations when source and destination field names differ.
5. Use IF nodes (n8n-nodes-base.if) for any conditions in the intent.
6. Give every node a descriptive, user-friendly name.
7. For credential-dependent nodes, include a "credentials" object with empty id/name strings.
8. Use the latest typeVersion from the reference table above.
9. The output must be a single valid JSON object — the complete workflow.
10. If the intent involves apps not in the reference table, use n8n-nodes-base.httpRequest as a fallback and include a comment in the node name like "HTTP: AppName".
11. For n8n expression syntax, use: ={{ $json.fieldName }} to reference fields from the previous node."""


REVIEW_PROMPT = """You are an n8n workflow reviewer. You receive a generated n8n workflow JSON and the original intent that it was built from. Your job is to check if the workflow correctly implements the intent and identify any issues.

Review the workflow for:
1. **Correctness**: Does the workflow actually do what the intent describes? Are the right node types used?
2. **Data flow**: Are fields mapped correctly between nodes? Do expressions reference the right fields (={{ $json.fieldName }})?
3. **Completeness**: Are any steps from the intent missing in the workflow?
4. **Node parameters**: Are parameters configured correctly for each node type? Are there obviously wrong or empty values that would cause failures?
5. **Connection logic**: Are all nodes connected in the right order? Is the trigger appropriate?
6. **Edge cases**: Are there conditions or error scenarios that should be handled but aren't?

Return ONLY a JSON object with this exact structure:
{
  "overall_score": 0.0 to 1.0,
  "verdict": "pass" | "warning" | "fail",
  "issues": [
    {
      "severity": "error" | "warning" | "info",
      "node": "Node Name or null",
      "message": "Clear description of the issue",
      "suggestion": "How to fix it"
    }
  ],
  "summary": "One-sentence overall assessment"
}

Rules:
- "pass" means the workflow looks correct and should work as intended (may have minor info-level notes)
- "warning" means the workflow will mostly work but has issues that could cause problems
- "fail" means the workflow has critical errors that will prevent it from working
- Be specific about which node has the issue and what exactly is wrong
- Keep suggestions actionable and concrete
- Don't flag missing credentials — those are expected to be set up separately
- Don't flag empty document/sheet IDs — those are filled in by the user in n8n
- IMPORTANT: Return ONLY the JSON object. No markdown, no code fences, no explanation."""


class InterpretRequest(BaseModel):
    events: list[dict[str, Any]]
    provider: str | None = None


class ClarifyRequest(BaseModel):
    sessionId: str
    answers: dict[str, str]


class GenerateRequest(BaseModel):
    sessionId: str


class DeployRequest(BaseModel):
    sessionId: str


# --- n8n API Helpers ---

def n8n_check_connection() -> bool:
    """Check if n8n instance is reachable."""
    try:
        resp = httpx.get(
            f"{N8N_HOST}/api/v1/workflows",
            headers={"X-N8N-API-KEY": N8N_API_KEY},
            params={"limit": 1},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


def n8n_create_workflow(workflow: dict) -> dict:
    """Create a workflow on the n8n instance. Returns the n8n response."""
    resp = httpx.post(
        f"{N8N_HOST}/api/v1/workflows",
        headers={"X-N8N-API-KEY": N8N_API_KEY, "Content-Type": "application/json"},
        json=workflow,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def n8n_activate_workflow(workflow_id: str) -> dict:
    """Activate a workflow on the n8n instance."""
    resp = httpx.patch(
        f"{N8N_HOST}/api/v1/workflows/{workflow_id}",
        headers={"X-N8N-API-KEY": N8N_API_KEY, "Content-Type": "application/json"},
        json={"active": True},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _extract_credential_notes(workflow: dict) -> list[dict]:
    """Extract which credentials are needed from a workflow."""
    notes = []
    seen = set()
    for node in workflow.get("nodes", []):
        creds = node.get("credentials", {})
        for cred_type, cred_info in creds.items():
            if cred_type not in seen:
                seen.add(cred_type)
                notes.append({
                    "service": cred_type,
                    "node": node.get("name", "Unknown"),
                    "description": f"Required by '{node.get('name', '?')}' ({node.get('type', '?')})",
                    "status": "not_configured",
                })
    return notes


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()
    return text


def _call_anthropic(system: str, user_message: str) -> dict:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    text = _strip_code_fences(response.content[0].text)
    return json.loads(text)


def _call_openai(system: str, user_message: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )
    text = _strip_code_fences(response.choices[0].message.content)
    return json.loads(text)


def _call_kimi(system: str, user_message: str) -> dict:
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Accept": "text/event-stream",
    }
    payload = {
        "model": "moonshotai/kimi-k2.5",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": 16384,
        "temperature": 1.00,
        "top_p": 1.00,
        "stream": True,
        "chat_template_kwargs": {"thinking": True},
    }

    print(f"[Kimi] Calling NVIDIA API with model: {payload['model']}")
    reasoning_parts = []
    content_parts = []
    with httpx.stream("POST", NVIDIA_URL, headers=headers, json=payload, timeout=120) as response:
        response.raise_for_status()
        print(f"[Kimi] Stream connected — status {response.status_code}")
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:]  # strip "data: " prefix
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            delta = chunk["choices"][0].get("delta", {})
            if delta.get("reasoning_content"):
                reasoning_parts.append(delta["reasoning_content"])
            # Collect only the actual content, skip reasoning/thinking
            if delta.get("content"):
                content_parts.append(delta["content"])
                print(f"[Kimi] Content chunk: {delta['content'][:80]}")

    full_content = "".join(content_parts)
    full_reasoning = "".join(reasoning_parts)
    print(f"[Kimi] Thinking: {full_reasoning[:200]}...")
    print(f"[Kimi] Response ({len(full_content)} chars): {full_content[:200]}...")
    text = _strip_code_fences(full_content)
    return json.loads(text)


def call_llm(system: str, user_message: str, provider: str | None = None) -> dict:
    p = provider or LLM_PROVIDER
    if p == "openai":
        return _call_openai(system, user_message)
    if p == "kimi":
        return _call_kimi(system, user_message)
    return _call_anthropic(system, user_message)


@app.post("/interpret")
async def interpret(req: InterpretRequest):
    session_id = str(uuid.uuid4())
    provider = req.provider or LLM_PROVIDER
    model_display = LLM_MODELS.get(provider, provider)
    user_msg = f"Here are the recorded browser events to interpret:\n\n{json.dumps(req.events, indent=2)}"

    try:
        intent = call_llm(SYSTEM_PROMPT, user_msg, provider=provider)
    except (json.JSONDecodeError, IndexError) as e:
        raise HTTPException(status_code=502, detail=f"Failed to parse LLM response: {e}")

    has_questions = bool(intent.get("unresolved_questions"))
    sessions[session_id] = {
        "sessionId": session_id,
        "recording": req.events,
        "provider": provider,
        "interpretations": [intent],
        "currentIntent": intent,
        "generatedWorkflow": None,
        "validationResult": None,
        "n8nWorkflowId": None,
        "n8nUrl": None,
        "credentialNotes": [],
        "reviewResult": None,
        "status": "clarifying" if has_questions else "confirmed",
    }

    return {"sessionId": session_id, "intent": intent, "status": sessions[session_id]["status"]}


@app.post("/clarify")
async def clarify(req: ClarifyRequest):
    session = sessions.get(req.sessionId)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    additional_notes = req.answers.pop("_additional_notes", None)

    user_msg = (
        f"Original recorded events:\n{json.dumps(session['recording'], indent=2)}\n\n"
        f"Previous interpretation:\n{json.dumps(session['currentIntent'], indent=2)}\n\n"
        f"User's answers to clarifying questions:\n{json.dumps(req.answers, indent=2)}\n\n"
    )
    if additional_notes:
        user_msg += f"Additional notes from the user:\n{additional_notes}\n\n"
    user_msg += (
        "Please produce a refined intent object incorporating these answers and any additional user notes. "
        "Resolve the answered questions and only include new unresolved_questions if truly necessary."
    )

    try:
        intent = call_llm(SYSTEM_PROMPT, user_msg, provider=session.get("provider"))
    except (json.JSONDecodeError, IndexError) as e:
        raise HTTPException(status_code=502, detail=f"Failed to parse LLM response: {e}")

    session["interpretations"].append(intent)
    session["currentIntent"] = intent
    has_questions = bool(intent.get("unresolved_questions"))
    session["status"] = "clarifying" if has_questions else "confirmed"

    return {"sessionId": req.sessionId, "intent": intent, "status": session["status"]}


@app.get("/intent/{session_id}")
async def get_intent(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "sessionId": session_id,
        "intent": session["currentIntent"],
        "status": session["status"],
        "interpretationCount": len(session["interpretations"]),
    }


@app.post("/confirm/{session_id}")
async def confirm_intent(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session["status"] = "confirmed"
    return {"sessionId": session_id, "status": "confirmed", "intent": session["currentIntent"]}


@app.post("/generate")
async def generate_workflow(req: GenerateRequest):
    session = sessions.get(req.sessionId)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] != "confirmed":
        raise HTTPException(status_code=400, detail=f"Intent must be confirmed first (current: {session['status']})")

    session["status"] = "generating"
    intent = session["currentIntent"]
    user_msg = f"Generate an n8n workflow for this confirmed intent:\n\n{json.dumps(intent, indent=2)}"

    try:
        workflow = call_llm(GENERATOR_PROMPT, user_msg, provider=session.get("provider"))
    except (json.JSONDecodeError, IndexError) as e:
        session["status"] = "confirmed"
        raise HTTPException(status_code=502, detail=f"Failed to parse LLM workflow response: {e}")

    # Validate
    validation = validate_workflow(workflow)

    # If invalid, retry once with error context
    if not validation["valid"]:
        print(f"[Generator] First attempt invalid: {validation['errors']}")
        retry_msg = (
            f"{user_msg}\n\n"
            f"IMPORTANT: A previous attempt produced invalid JSON with these errors:\n"
            f"{json.dumps(validation['errors'], indent=2)}\n\n"
            f"Please fix these issues and produce a corrected workflow."
        )
        try:
            workflow = call_llm(GENERATOR_PROMPT, retry_msg, provider=session.get("provider"))
            validation = validate_workflow(workflow)
        except (json.JSONDecodeError, IndexError) as e:
            session["status"] = "confirmed"
            raise HTTPException(status_code=502, detail=f"Failed on retry: {e}")

    credential_notes = _extract_credential_notes(workflow)

    # LLM review: check if the workflow correctly implements the intent
    review_result = None
    try:
        review_msg = (
            f"## Original Intent\n{json.dumps(intent, indent=2)}\n\n"
            f"## Generated Workflow\n{json.dumps(workflow, indent=2)}"
        )
        review_result = call_llm(REVIEW_PROMPT, review_msg, provider=session.get("provider"))
        print(f"[Review] Verdict: {review_result.get('verdict', 'unknown')} — Score: {review_result.get('overall_score', '?')}")
    except Exception as e:
        print(f"[Review] LLM review failed (non-blocking): {e}")
        review_result = {"verdict": "unknown", "overall_score": None, "issues": [], "summary": f"Review unavailable: {e}"}

    session["generatedWorkflow"] = workflow
    session["validationResult"] = validation
    session["credentialNotes"] = credential_notes
    session["reviewResult"] = review_result
    session["status"] = "generated"

    return {
        "sessionId": req.sessionId,
        "workflow": workflow,
        "validationResult": validation,
        "credentialNotes": credential_notes,
        "reviewResult": review_result,
    }


@app.post("/deploy")
async def deploy_workflow(req: DeployRequest):
    session = sessions.get(req.sessionId)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.get("generatedWorkflow"):
        raise HTTPException(status_code=400, detail="No generated workflow to deploy")

    if not n8n_check_connection():
        raise HTTPException(status_code=503, detail="n8n instance is not reachable. Check N8N_HOST and N8N_API_KEY.")

    try:
        result = n8n_create_workflow(session["generatedWorkflow"])
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"n8n API error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to deploy: {e}")

    n8n_id = result.get("id")
    session["n8nWorkflowId"] = n8n_id
    session["n8nUrl"] = f"{N8N_HOST}/workflow/{n8n_id}"
    session["status"] = "deployed"

    return {
        "sessionId": req.sessionId,
        "n8nWorkflowId": n8n_id,
        "n8nUrl": session["n8nUrl"],
        "credentialNotes": session["credentialNotes"],
    }


@app.post("/activate")
async def activate_workflow(req: DeployRequest):
    session = sessions.get(req.sessionId)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.get("n8nWorkflowId"):
        raise HTTPException(status_code=400, detail="Workflow not deployed yet")

    try:
        n8n_activate_workflow(session["n8nWorkflowId"])
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"n8n API error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to activate: {e}")

    session["status"] = "active"
    return {"sessionId": req.sessionId, "active": True}


@app.get("/workflow/{session_id}")
async def get_workflow(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.get("generatedWorkflow"):
        raise HTTPException(status_code=404, detail="No workflow generated yet")
    return session["generatedWorkflow"]


@app.get("/workflow/{session_id}/download")
async def download_workflow(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.get("generatedWorkflow"):
        raise HTTPException(status_code=404, detail="No workflow generated yet")

    workflow_json = json.dumps(session["generatedWorkflow"], indent=2)
    name = session["generatedWorkflow"].get("name", "workflow").replace(" ", "-").lower()
    return JSONResponse(
        content=session["generatedWorkflow"],
        headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
    )


@app.get("/n8n/status")
async def n8n_status():
    connected = n8n_check_connection()
    return {"connected": connected, "host": N8N_HOST}


@app.get("/session/{session_id}", response_class=HTMLResponse)
async def session_page(request: Request, session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return templates.TemplateResponse(
        "session.html",
        {
            "request": request,
            "session_id": session_id,
            "status": session["status"],
            "intent_json": json.dumps(session["currentIntent"], indent=2),
            "workflow_json": json.dumps(session["generatedWorkflow"], indent=2) if session.get("generatedWorkflow") else "null",
            "validation_json": json.dumps(session.get("validationResult")) if session.get("validationResult") else "null",
            "credential_notes_json": json.dumps(session.get("credentialNotes", [])),
            "n8n_workflow_id": session.get("n8nWorkflowId") or "",
            "n8n_url": session.get("n8nUrl") or "",
            "model_name": LLM_MODELS.get(session.get("provider", LLM_PROVIDER), LLM_PROVIDER),
            "review_json": json.dumps(session.get("reviewResult")) if session.get("reviewResult") else "null",
        },
    )


@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "models": LLM_MODELS,
        "default_provider": LLM_PROVIDER,
    })


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
