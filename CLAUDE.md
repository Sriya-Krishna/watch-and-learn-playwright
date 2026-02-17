# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Two-component system: a Chrome extension that records browser actions, and a FastAPI backend that interprets recordings into structured automation intents using LLMs, generates n8n workflows, and deploys them. This is a POC — no auth, no database, no tests, no deployment.

## Commands

### Backend
```bash
# Install dependencies
cd backend && pip install -r requirements.txt

# Run the server (port 8000)
cd backend && python server.py

# Or with uvicorn directly
cd backend && uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

### Chrome Extension
No build step. Load unpacked from `chrome-extension/` directory in `chrome://extensions` with Developer mode enabled.

## Architecture

```
Chrome Extension (content.js → background.js → chrome.storage.local)
        ↓ POST /interpret
FastAPI Backend (server.py) → LLM Provider (Anthropic / OpenAI / Kimi)
        ↓
Session created in-memory → /session/{id} serves 5-step wizard UI
        ↓ POST /clarify (loop) → POST /confirm/{id}
Confirmed intent → POST /generate → n8n workflow JSON
        ↓ POST /deploy → n8n REST API
        ↓ POST /activate
Live workflow on n8n instance
```

### Chrome Extension (`chrome-extension/`)
- **content.js**: Injected at `document_start` into all pages. Captures click, input (debounced 800ms), formSubmit, copy, paste, and navigation events. Monkey-patches `history.pushState`/`replaceState` for SPA navigation detection. All DOM listeners use capture phase.
- **background.js**: Service worker. Relays start/stop to content scripts, appends events to `chrome.storage.local`, captures tab/window focus events independently via Chrome APIs.
- **popup.js**: Reads events from storage on stop. Sends to `http://localhost:8000/interpret` (hardcoded). Opens session page in new tab.

### Backend (`backend/`)
Single-file server (`server.py`). Sessions stored in a Python dict — lost on restart.

**Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Upload page — paste/upload JSON, select model |
| `POST` | `/interpret` | `{ events, provider? }` → LLM → creates session |
| `POST` | `/clarify` | `{ sessionId, answers }` → LLM refinement |
| `GET` | `/intent/{id}` | Current intent state |
| `POST` | `/confirm/{id}` | Force confirm |
| `POST` | `/generate` | `{ sessionId }` → LLM generates n8n workflow JSON, validates, stores |
| `POST` | `/deploy` | `{ sessionId }` → pushes workflow to n8n via REST API |
| `POST` | `/activate` | `{ sessionId }` → activates workflow on n8n |
| `GET` | `/workflow/{id}` | Returns generated workflow JSON |
| `GET` | `/workflow/{id}/download` | Downloads workflow as .json file |
| `GET` | `/n8n/status` | Checks n8n instance connectivity |
| `GET` | `/session/{id}` | 5-step wizard UI |

**Files:** `server.py` (main server), `validator.py` (workflow structural validation).

**Templates:** `session.html` (5-step wizard: intent → clarify → generate → deploy → active), `upload.html` (paste/upload/drag-drop with model dropdown).

## n8n Integration

Configured via `N8N_HOST` and `N8N_API_KEY` in `backend/.env`. Uses n8n REST API v1 directly via `httpx`.

- `n8n_check_connection()` — GET `/api/v1/workflows?limit=1`
- `n8n_create_workflow()` — POST `/api/v1/workflows`
- `n8n_activate_workflow()` — PATCH `/api/v1/workflows/{id}` with `{"active": true}`

n8n connection is optional — if unreachable, the UI hides deploy/activate and shows download-only.

**Start n8n locally:** `npx n8n start` (runs on port 5678). Generate API key: Settings → API → Create API Key.

## Workflow Generation

`GENERATOR_PROMPT` in server.py instructs the LLM to produce valid n8n workflow JSON. Includes a node type reference table and a complete example workflow. The `/generate` endpoint validates the output with `validator.py` and retries once if invalid.

Session statuses: `clarifying` → `confirmed` → `generating` → `generated` → `deployed` → `active`.

## LLM Provider System

Configured via `LLM_PROVIDER` in `backend/.env`. The provider's client is initialized at module load.

| Provider | Model | Client | Key env var |
|----------|-------|--------|-------------|
| `anthropic` | `claude-sonnet-4-20250514` | `anthropic.Anthropic()` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o` | `openai.OpenAI()` | `OPENAI_API_KEY` |
| `kimi` | `moonshotai/kimi-k2.5` | `httpx` direct to NVIDIA NIM API (SSE streaming) | `NVIDIA_API` |

`call_llm(system, user_message, provider=None)` dispatches to `_call_anthropic`, `_call_openai`, or `_call_kimi`. All providers return parsed JSON dicts. `_strip_code_fences()` handles LLMs that wrap JSON in markdown code blocks.

**Important limitation:** Only the startup provider's client is initialized. Per-request provider override (via `/interpret` body or upload page dropdown) only works for the provider initialized at startup.

## Key Design Details

- **Password redaction**: `formSubmit` replaces password field values with `[REDACTED]`
- **Input debounce**: 800ms per field keyed by XPath; pending timers discarded (not flushed) on stop
- **Kimi streaming**: Uses SSE via `httpx.stream()`, collects `delta.content` chunks, discards `reasoning_content` (chain-of-thought). Console prints `[Kimi]` prefixed debug logs.
- **System prompt** (`SYSTEM_PROMPT` in server.py): Instructs LLM to return a specific JSON schema with `intent_summary`, `trigger`, `steps[]`, `data_flow`, `conditions`, `unresolved_questions[]`, `overall_confidence`. Rules: extract ≥70% from evidence, max 3-5 questions, plain English.
- **CORS**: Fully open (`*`) — intentional for local POC.
- **Backend URL**: Hardcoded in `popup.js` as `http://localhost:8000`.
