# FinCorp Workflow Recorder

> Record browser actions → interpret intent with an LLM → generate and deploy n8n workflows automatically.

<div align="center">
  <img src="demo_output.gif" alt="Demo: recording browser actions and generating an n8n workflow" width="800" />
</div>

---

## Prerequisites

- Python 3.10+
- Node.js 18+ (for n8n)
- Google Chrome
- An LLM API key (Anthropic, OpenAI, or NVIDIA/Kimi)

## Setup

**1. Install backend dependencies**

```bash
cd backend && pip install -r requirements.txt
```

**2. Configure environment**

Create `backend/.env`:

```
LLM_PROVIDER=anthropic          # anthropic | openai | kimi

ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
NVIDIA_API=nvapi-...

N8N_HOST=http://localhost:5678  # optional — needed for deploy/activate
N8N_API_KEY=your-n8n-api-key
```

**3. Start n8n** *(optional — for deploy/activate)*

```bash
npx n8n start
```

Go to `http://localhost:5678` → Settings → API → Create API Key, then paste it into `.env`.

**4. Start the backend**

```bash
cd backend && python server.py
```

Runs at `http://localhost:8000`.

**5. Start the Playwright service** *(optional — for browser automation steps)*

```bash
cd playwright-service
pip install -r requirements.txt
playwright install chromium
python main.py
```

Runs at `http://localhost:3001`.

**6. Load the Chrome extension**

1. Go to `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select the `chrome-extension/` folder

---

## Usage

1. Click the **Workflow Recorder** icon in Chrome's toolbar
2. Click **Start Recording** — the button turns red
3. Browse normally: click links, fill forms, navigate pages
4. Click the icon again → **Stop Recording**
5. Click **Send to Interpreter** — a session page opens automatically

**On the session page:**

- **Interpret** — review the plain-English intent summary; answer any clarifying questions or confirm as-is
- **Generate** — the LLM produces an n8n workflow JSON with structural validation and a second LLM review pass
- **Deploy** — pushes the workflow to your n8n instance (or download the JSON to import manually)
- **Activate** — goes live; set up credentials in n8n first

---

See [REFERENCE.md](REFERENCE.md) for API endpoints, architecture details, and how each component works.