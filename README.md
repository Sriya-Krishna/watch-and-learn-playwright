# How to Run

## Prerequisites

- Python 3.10+
- Node.js 18+ (for n8n)
- Google Chrome
- An LLM API key (Anthropic, OpenAI, or NVIDIA/Kimi)

## Setup

### 1. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure environment

Open `backend/.env` and set:

```
# LLM provider: "anthropic", "openai", or "kimi"
LLM_PROVIDER=anthropic

# Set the key for your chosen provider
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
NVIDIA_API=nvapi-...

# n8n instance (optional — needed for deploy/activate)
N8N_HOST=http://localhost:5678
N8N_API_KEY=your-n8n-api-key
```

### 3. Start n8n (optional — needed for deploy/activate)

```bash
npx n8n start
```

n8n runs at `http://localhost:5678`. On first launch, create an account, then generate an API key:

1. Open `http://localhost:5678`
2. Go to **Settings → API**
3. Click **Create API Key**
4. Copy the key into `backend/.env` as `N8N_API_KEY`

### 4. Start the backend server

```bash
cd backend
python server.py
```

The server runs at `http://localhost:8000`.

### 5. Set up the Playwright service (optional — needed for browser automation)

```bash
cd playwright-service
pip install -r requirements.txt
playwright install chromium
```

Configure `playwright-service/.env` — set the same LLM API key as the backend.

Start the service:

```bash
cd playwright-service
python main.py
```

The Playwright service runs at `http://localhost:3001`.

### 6. Load the Chrome extension

1. Open Chrome and go to `chrome://extensions`
2. Toggle **Developer mode** ON (top right corner)
3. Click **Load unpacked**
4. Select the `chrome-extension/` folder from this project

## Usage

### Option A: Record from the browser

1. Click the **Workflow Recorder** icon in Chrome's toolbar
2. Click **Start Recording** (the button turns red and pulses)
3. Browse normally — click links, fill forms, navigate between pages
4. Click the extension icon again and click **Stop Recording**
5. You'll see the event count and three options:
   - **Copy JSON** — copies the raw recording to clipboard
   - **Download JSON** — saves the recording as a `.json` file
   - **Send to Interpreter** — sends the recording to the backend

### Option B: Upload a recording directly

1. Open `http://localhost:8000`
2. Paste a recording JSON or drag-and-drop a `.json` file
3. Select the LLM model from the dropdown
4. Click **Interpret Recording**

## Full Workflow: Record → Interpret → Generate → Deploy → Activate

### Step 1 — Interpret

After submitting a recording, you'll see:
- A plain English summary of what the workflow does
- The trigger and each step with confidence scores
- Clarifying questions (if any) — answer them or click **Confirm Intent As-Is**

### Step 2 — Generate

Once the intent is confirmed, click **Generate n8n Workflow**. The LLM produces a valid n8n workflow JSON. You'll see:
- A visual node flow (color-coded: green=trigger, blue=action, orange=logic)
- Structural validation result (pass/fail)
- **LLM Review** — a second LLM pass that checks the workflow against your intent for logical correctness. Shows a score, verdict (pass/warning/fail), and specific issues with fix suggestions
- Credentials checklist (which accounts need to be connected)
- Collapsible raw JSON

### Step 3 — Deploy

Click **Deploy to n8n** to push the workflow to your n8n instance. If n8n is offline, this button is disabled — use **Download JSON** instead and import manually.

### Step 4 — Activate

After deploying:
1. Set up required credentials in n8n (Settings → Credentials)
2. Open the workflow in n8n and assign credentials to each node
3. Return to the session page and click **Activate Workflow**

The workflow is now live and running automatically.

## API Endpoints

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

### Playwright Service (port 3001)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/scripts/generate` | Generate Playwright script from intent + recording |
| POST | `/scripts/:scriptId/execute` | Execute script, auto-heals on failure |
| GET | `/scripts/:scriptId` | Get script details and stats |
| GET | `/scripts/:scriptId/history` | Get execution and heal history |
| DELETE | `/scripts/:scriptId` | Delete script and history |
| GET | `/scripts` | List all scripts |
| GET | `/health` | Service health check |
