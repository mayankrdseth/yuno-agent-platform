# Yuno Agent Platform

A full-stack multi-agent orchestration platform. Create agents, wire them into workflows on a visual canvas, run them against real LLMs (via Groq), and monitor execution live — all from a browser UI or a Telegram bot.

---

## What It Does

- **Agent management** — create, edit, and delete agents with custom system prompts, models, tools, guardrails, skills, and interaction rules
- **Visual workflow canvas** — drag agents onto a ReactFlow canvas and wire them up; the selected agent list is the live workflow definition
- **LangGraph execution** — an orchestrator agent uses LLM-based routing to select a specialist agent; the specialist runs with optional tool calls
- **Retry / feedback loop** — if a specialist returns an empty or guardrail-blocked response, the graph automatically routes back to the orchestrator (up to 2 retries), which re-routes to a different or better-instructed specialist
- **Built-in templates** — two pre-seeded workflows (*Research Hub*, *Support Triage*) load on first startup
- **Run history** — every workflow execution is persisted with full message logs, token usage, and estimated cost
- **Live monitoring** — WebSocket stream (`/ws/monitor`) broadcasts real-time execution events to the dashboard
- **Telegram integration** — send a task to the bot, it runs the workflow and replies with the result

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.11+, SQLAlchemy (async), SQLite (aiosqlite) |
| Workflow runtime | LangGraph `StateGraph` |
| LLM provider | Groq API (`langchain-groq`) |
| Frontend | React 19, Vite 8, ReactFlow 11, Axios |
| Frontend serving | nginx (production Docker build) |
| Messaging | python-telegram-bot (webhook mode) |
| Testing | pytest + pytest-asyncio (backend), Vitest + Testing Library (frontend) |

---

## Quick Start (Docker — Recommended)

### 1. Clone

```bash
git clone https://github.com/mayankrdseth/yuno-agent-platform.git
cd yuno-agent-platform
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```env
APP_NAME=Yuno Agent Platform
APP_ENV=dev
DEBUG=true

DATABASE_URL=sqlite+aiosqlite:///./yuno.db

GROQ_API_KEY=your_groq_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_WEBHOOK_SECRET=your_webhook_secret
```

Get a free Groq API key at [console.groq.com](https://console.groq.com).

### 3. Build and run

```bash
docker compose up --build
```

That's it. No manual database setup needed — `init_db()` runs at backend startup, creates all tables, and seeds the built-in agents and templates.

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |

### Wipe and reseed from scratch

```bash
docker compose down -v   # -v removes the yuno-db volume
docker compose up --build
```

---

## Telegram Webhook Setup (Local Development)

Telegram webhooks require a publicly reachable HTTPS URL. The easiest way to get one locally is **ngrok**.

### Step 1 — Install and run ngrok

```bash
# macOS
brew install ngrok

# Linux / Windows — download from https://ngrok.com/download
```

Start a tunnel pointing at the backend port:

```bash
ngrok http 8000
```

ngrok will print a forwarding URL like:

```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:8000
```

### Step 2 — Register the webhook with Telegram

Replace the placeholders and run:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://<YOUR_NGROK_SUBDOMAIN>.ngrok-free.app/telegram/webhook",
    "secret_token": "<YOUR_WEBHOOK_SECRET>"
  }'
```

A successful response looks like:

```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

### Step 3 — Verify

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

Check that `"url"` matches your ngrok address and `"last_error_message"` is absent.

### Step 4 — Start the backend (if not already running)

```bash
uvicorn app.main:app --reload
# or: docker compose up --build
```

Now send any message to your bot — it will trigger a full workflow run and reply.

> **Note:** ngrok free-tier tunnels expire when you restart ngrok. Re-run the `setWebhook` curl command each time your ngrok URL changes. For a stable URL, use a paid ngrok plan or a free alternative like [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).

---

## Docker Architecture

The stack runs as two containers orchestrated by `docker-compose.yml`:

```
┌─────────────────────────────────────┐
│  yuno-frontend  (nginx:1.27-alpine) │
│  port 5173:80                       │
│  Vite build → static files          │
│  SPA fallback via nginx.conf        │
└────────────────┬────────────────────┘
                 │  depends_on (healthy)
┌────────────────▼────────────────────┐
│  yuno-backend  (python:3.11-slim)   │
│  port 8000:8000                     │
│  uvicorn app.main:app               │
│  SQLite stored in yuno-db volume    │
└─────────────────────────────────────┘
```

- **`Dockerfile.backend`** — installs Python deps, copies `app/`, mounts SQLite at `/data/yuno.db` via a named volume
- **`Dockerfile.frontend`** — two-stage build: Node 20 builds the Vite app (with `VITE_API_BASE` baked in at build time), then nginx serves the static output
- **`nginx.conf`** — serves static assets with long-cache headers, SPA fallback for all routes
- The backend has a healthcheck (`GET /health`) — the frontend container waits for it before starting

---

## Manual Setup (Local Development)

Use this if you want hot-reload on both frontend and backend simultaneously.

### Backend

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# → http://127.0.0.1:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

---

## Architecture

### Execution Flow

```
User input (UI or Telegram)
        │
        ▼
  orchestrator_node  ←  loaded from DB by role="orchestrator"
  (LLM router — returns JSON {target, reason})
        │
        ▼
  specialist_node    ←  one of N agents on the canvas
  (runs with tool calls if needed)
        │
        ▼
  retry_check_node
  (empty / guardrail-blocked response?)
        │
        ├── needs_retry=True  ──▶  orchestrator_node  (re-routes, up to 2×)
        │
        └── needs_retry=False ──▶  guardrails check
                                        │
                                        ▼
                              response + token usage persisted to DB
```

### Backend (`app/`)

| Path | Responsibility |
|---|---|
| `main.py` | FastAPI app, CORS for `localhost:5173`, lifespan runs DB init and Telegram setup |
| `api/agents.py` | Full CRUD: `GET/POST /agents`, `GET/PATCH/DELETE /agents/{id}` |
| `api/workflows.py` | `POST /workflows/demo-run`, `GET /workflows/runs`, `GET /workflows/runs/{id}/messages` |
| `api/workflow_templates.py` | `GET/POST /workflow-templates`, `DELETE /workflow-templates/{id}` (built-ins protected) |
| `api/monitor.py` | WebSocket `/ws/monitor` — broadcasts run events via in-memory queue |
| `api/telegram.py` | Telegram webhook receiver |
| `api/health.py` | Health check endpoint |
| `runtime/agent_graph.py` | LangGraph `StateGraph` — orchestrator + specialist nodes, retry/feedback loop, guardrails, token tracking |
| `runtime/tools.py` | Tool registry: `datetime`, `calculator`, `web_search` (DuckDuckGo), `wikipedia` |
| `runtime/llm.py` | `get_llm(model)` — returns a `ChatGroq` instance |
| `runtime/state.py` | `WorkflowState` TypedDict and `TokenUsage` dataclass |
| `db/init_db.py` | Creates tables, seeds 5 built-in agents + 2 built-in templates (idempotent) |
| `core/broadcast.py` | Async pub/sub queue for WebSocket monitor events |

### Retry / Feedback Loop

After each specialist run, `retry_check_node` evaluates the output:

- **Empty response** → retry (re-route to a different specialist)
- **Guardrail refusal** (`[Guardrail] ...` prefix) → retry
- **Max retries reached** (2×) → pass through; if still empty, returns a graceful error

On retry, the orchestrator receives the previous specialist's output as context so it can deliberately choose a *different* specialist — enabling sequential multi-agent handling of compound queries (e.g. *"What is 2+2 and who invented calculus?"* hits Mathematician first, then on retry Researcher handles the history part).

### Built-in Templates (seeded at startup)

| Template | Orchestrator | Specialists | Routing logic |
|---|---|---|---|
| **Research Hub** | `ResearchOrchestrator` | `Researcher` (web_search, wikipedia), `Mathematician` (calculator, datetime) | Factual queries → Researcher; numeric/date queries → Mathematician |
| **Support Triage** | `SupportOrchestrator` | `Supporter`, `Escalator` (datetime) | Routine queries → Supporter; urgent/complex → Escalator |

### Tool Registry

| Tool | What it does |
|---|---|
| `datetime` | Returns current date and time |
| `calculator` | Safe `eval` of math expressions using Python `math` module |
| `web_search` | DuckDuckGo Instant Answer API (no key required) |
| `wikipedia` | Wikipedia REST API summary (~400 chars) |

### Agent Configuration

| Field | Purpose |
|---|---|
| `system_prompt` | Core instructions for the agent |
| `model` | Groq model to use |
| `tools` | List of tool names the agent may call |
| `channels` | Messaging channels (e.g. `telegram`) |
| `skills` | Capability labels visible to the orchestrator for routing (e.g. `["summarisation", "code_review"]`) |
| `interaction_rules` | Behavioural rules injected into the agent's prompt context (e.g. `["always reply in bullet points"]`) |
| `forbidden_topics` | Guardrail: keywords that trigger a refusal response |
| `max_output_chars` | Guardrail: hard character cap on output |
| `memory_enabled` | Whether the orchestrator persists conversation turns for this session |
| `max_iterations` | How many memory turns to inject as context |
| `schedule` | Cron expression for scheduled runs (set via natural language) |

---

## Project Structure

```
yuno-agent-platform/
├── app/
│   ├── api/
│   │   ├── agents.py
│   │   ├── health.py
│   │   ├── monitor.py
│   │   ├── telegram.py
│   │   ├── workflow_templates.py
│   │   └── workflows.py
│   ├── core/
│   │   ├── broadcast.py
│   │   └── config.py
│   ├── db/
│   │   ├── base.py
│   │   ├── init_db.py
│   │   └── session.py
│   ├── models/
│   │   ├── agent.py
│   │   ├── workflow_message.py
│   │   ├── workflow_run.py
│   │   └── workflow_template.py
│   ├── runtime/
│   │   ├── agent_graph.py
│   │   ├── demo_graph.py
│   │   ├── llm.py
│   │   ├── state.py
│   │   └── tools.py
│   ├── schemas/
│   ├── services/
│   │   ├── agent_service.py
│   │   ├── memory_service.py
│   │   ├── run_service.py
│   │   ├── scheduler_service.py
│   │   ├── telegram_service.py
│   │   ├── workflow_service.py
│   │   └── workflow_template_service.py
│   └── main.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── App.test.jsx
│   │   └── ...
│   ├── package.json
│   └── vite.config.js
├── tests/
│   └── test_api.py
├── Dockerfile.backend
├── Dockerfile.frontend
├── docker-compose.yml
├── nginx.conf
├── .env.example
├── requirements.txt
└── pytest.ini
```

---

## API Reference

### Agents

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/agents` | List all agents |
| `POST` | `/agents` | Create an agent |
| `GET` | `/agents/{id}` | Get agent by ID |
| `PATCH` | `/agents/{id}` | Update an agent |
| `DELETE` | `/agents/{id}` | Delete an agent |

### Workflows

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/workflows/demo-run` | Execute a workflow (requires ≥ 2 agents) |
| `GET` | `/workflows/runs` | List run history (default limit 50) |
| `GET` | `/workflows/runs/{id}/messages` | Get message log for a run |

### Templates

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/workflow-templates` | List all templates |
| `POST` | `/workflow-templates` | Create a custom template |
| `DELETE` | `/workflow-templates/{id}` | Delete a template (built-ins are protected) |

### Other

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Root endpoint |
| `GET` | `/health` | Health check (used by Docker healthcheck) |
| `WS` | `/ws/monitor` | WebSocket live event stream |
| `POST` | `/telegram/webhook` | Telegram webhook receiver |

---

## Running Tests

### Backend

```bash
python -m pytest tests/test_api.py -v
```

### Frontend

```bash
cd frontend
npm run test:run
```

---

## Token Usage & Cost Tracking

Every workflow run records `prompt_tokens`, `completion_tokens`, `total_tokens`, and `estimated_cost_usd` — calculated per model using Groq's approximate rates:

| Model | Input (per 1k) | Output (per 1k) |
|---|---|---|
| `llama-3.3-70b-versatile` | $0.00059 | $0.00079 |
| `llama-3.1-8b-instant` | $0.00005 | $0.00008 |
| `mixtral-8x7b-32768` | $0.00024 | $0.00024 |
| `gemma2-9b-it` | $0.00020 | $0.00020 |

---

## Telegram Bot Flow

1. Set your bot webhook (see **Telegram Webhook Setup** above)
2. Send a message — greetings are handled inline; task prompts trigger a full workflow run
3. The bot replies with the final response from the specialist agent
4. The run is persisted and visible in the dashboard run history
