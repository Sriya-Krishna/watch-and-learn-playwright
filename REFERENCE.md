# Reference

Architecture, API endpoints, and component internals for FinCorp Workflow Recorder.

---

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

Playwright Service (port 3001) ← n8n HTTP Request nodes
  → Generates Playwright scripts from intent + recording
  → Executes scripts headless, returns structured data
  → Self-heals scripts when they break (LLM patches + retry)
```

---

## Backend API (port 8000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Upload page — paste/upload JSON, select model |
| POST | `/interpret` | Send recorded events, get structured intent |
| POST | `/clarify` | Answer clarifying questions, get refined intent |
| GET | `/intent/:sessionId` | Get current intent state |
| POST | `/confirm/:sessionId` | Confirm the intent as final |
| POST | `/generate` | Generate n8n workflow, validate, and LLM review |
| POST | `/deploy` | Deploy generated workflow to n8n |
| POST | `/activate` | Activate deployed workflow on n8n |
| GET | `/workflow/:sessionId` | Get generated workflow JSON |
| GET | `/workflow/:sessionId/download` | Download workflow as .json file |
| GET | `/n8n/status` | Check n8n instance connectivity |
| GET | `/session/:sessionId` | Session wizard page |

## Playwright Service API (port 3001)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/scripts/generate` | Generate Playwright script from intent + recording |
| POST | `/scripts/:scriptId/execute` | Execute script, auto-heals on failure |
| GET | `/scripts/:scriptId` | Get script details and stats |
| GET | `/scripts/:scriptId/history` | Get execution and heal history |
| DELETE | `/scripts/:scriptId` | Delete script and history |
| GET | `/scripts` | List all scripts |
| GET | `/health` | Service health check |

---

## Component Details

### Chrome Extension

- **content.js** — injected at `document_start`. Captures click, input (debounced 800ms), formSubmit, copy, paste, and navigation events. Monkey-patches `history.pushState`/`replaceState` for SPA navigation. All DOM listeners use capture phase. Password fields are redacted.
- **background.js** — service worker. Relays start/stop to content scripts, appends events to `chrome.storage.local`, captures tab/window focus events via Chrome APIs.
- **popup.js** — reads events from storage on stop, sends to `http://localhost:8000/interpret`, opens session page in a new tab.

### Backend

Single-file server (`server.py`). Sessions stored in a Python dict — lost on restart.

**Session flow:** `clarifying` → `confirmed` → `generating` → `generated` → `deployed` → `active`

**Workflow generation:**
1. LLM produces n8n workflow JSON guided by `GENERATOR_PROMPT` (includes node type reference + example workflow)
2. `validator.py` checks structure: nodes exist, connections valid, required fields present, no duplicate names, positions are numbers — retries once if invalid
3. LLM review pass (`REVIEW_PROMPT`) checks logical correctness against original intent — returns verdict (`pass`/`warning`/`fail`), score (0–1), and issues with fix suggestions. Non-blocking — failure stores a fallback result.

### LLM Providers

Configured via `LLM_PROVIDER` in `.env`. Client is initialized at startup — per-request override only works for the provider initialized at startup.

| Provider | Model | Key env var |
|----------|-------|-------------|
| `anthropic` | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| `kimi` | `moonshotai/kimi-k2.5` | `NVIDIA_API` |

Kimi uses SSE streaming via `httpx` directly to the NVIDIA NIM API. `reasoning_content` (chain-of-thought) is discarded.

### Playwright Service

Standalone microservice (`playwright-service/`). n8n calls it via HTTP Request nodes.

**Script lifecycle:** LLM generates a `run(page, params) -> dict` function → stored to disk (SQLite metadata + `scripts/{id}/script_vN.py`) → executed headless → on failure, healer captures error + DOM + screenshot → LLM patches script → retry up to 3 times.

**Storage:** SQLite (`playwright_service.db`) for metadata; every script version kept on disk.