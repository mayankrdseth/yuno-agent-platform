# Yuno Agent Platform

A full-stack multi-agent orchestration platform. Create agents, wire them into workflows on a visual canvas, run them against real LLMs (via Groq), and monitor execution live — all from a browser UI or a Telegram bot.

---

## What It Does

- **Agent management** — create, edit, and delete agents with custom system prompts, models, tools, guardrails, skills, and interaction rules
- **Visual workflow canvas** — drag agents onto a ReactFlow canvas and wire them up; tool badges are shown directly on each canvas node (⚡ teal for orchestrator-pinned tools, 🔧 amber for specialist tools)
- **LangGraph execution** — a LangGraph `StateGraph` orchestrates agents with three routing modes: single specialist, parallel fanout, and sequential pipeline
- **Pipeline routing** — for research-then-summarise queries, the Researcher's output is automatically passed to the Summariser as input (true inter-agent message passing)
- **Retry / feedback loop** — if a specialist returns an empty or guardrail-blocked response, the graph re-routes back to the orchestrator (up to 2 retries)
- **Built-in templates** — two pre-seeded workflows (*Research Hub*, *Support Triage*) load on first startup
- **Run history** — every workflow execution is persisted with full message logs, token usage, and estimated cost
- **Live monitoring** — WebSocket stream (`/ws/monitor`) broadcasts real-time execution events to the dashboard
- **Telegram integration** — send a task to the bot, it runs the workflow and replies with the result
- **Scheduled workflows** — tell the bot "run this every day at 9 AM IST" and the platform converts to UTC and registers a recurring cron job automatically

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
- **`Dockerfile.frontend`** — two-stage build: Node 20 builds the Vite app, then nginx serves the static output
- **`nginx.conf`** — serves static assets with long-cache headers, SPA fallback for all routes
- The backend has a healthcheck (`GET /health`) — the frontend container waits for it before starting

---

## Manual Setup (Local Development)

```bash
# Backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

---

## Architecture

### Routing Modes

The orchestrator LLM analyses every user request and selects one of four routing modes:

| Mode | When Used | Flow |
|---|---|---|
| **SINGLE** | One specialist can handle the full query | `Orchestrator → Specialist → END` |
| **FANOUT** | Compound query needing multiple independent agents | `Orchestrator → [AgentA ∥ AgentB] → merge → END` |
| **PIPELINE** | Research-then-summarise: second agent needs first agent's output | `Orchestrator → Researcher → handoff → Summariser → END` |
| **SCHEDULE** | User wants a recurring task | `Orchestrator → register cron → END` |

### Execution Flow

```
User input (UI or Telegram)
        │
        ▼
  orchestrator_node  ←─────────────────────────────────────┐
  (LLM router — detects mode, uses calculator/datetime      │
   tools for UTC cron arithmetic)                           │
        │                                                   │
        ├── SCHEDULE ──▶ schedule_end_node ──▶ END          │
        │                                                   │
        ├── SINGLE ────▶ specialist_node                    │
        │                      │                           │
        ├── FANOUT ────▶ fanout_node (parallel)             │
        │                      │                           │
        └── PIPELINE ──▶ Researcher                         │
                               │                           │
                        pipeline_handoff_node              │
                        (injects research_notes)           │
                               │                           │
                          Summariser                       │
                               │                           │
                        retry_check_node                   │
                        (empty/guardrail?) ── needs_retry ─┘
                               │
                               └── response + token usage persisted to DB
```

### Pipeline Pattern (Inter-Agent Message Passing)

The PIPELINE mode demonstrates true agent-to-agent communication:

1. **Orchestrator** detects intent (e.g. *"research LangGraph and give me a brief"*) → sets `pipeline_mode=True`, routes to Researcher
2. **Researcher** runs on `user_input`, stores detailed findings in `state["research_notes"]`
3. **pipeline_handoff_node** advances the queue, sets `pipeline_stage="summarise"`
4. **Summariser** receives `research_notes` as its input (not raw `user_input`) → produces a structured TL;DR brief
5. Final response is the Summariser's brief — the Researcher's raw output is internal

This is the key difference from FANOUT: in FANOUT both agents get `user_input` independently. In PIPELINE, Agent B gets Agent A's output.

### Built-in Agents

| Agent | Role | Tools | Skills |
|---|---|---|---|
| `ResearchOrchestrator` | orchestrator | ⚡ `calculator`, ⚡ `datetime` | routing, intent_detection, pipeline_orchestration |
| `Researcher` | agent | 🔧 `web_search`, 🔧 `wikipedia` | web_search, summarisation, fact_checking |
| `Summariser` | agent | 🔧 `web_search`, 🔧 `wikipedia` | summarisation, content_condensing, structured_briefs |
| `SupportOrchestrator` | orchestrator | ⚡ `calculator`, ⚡ `datetime` | triage, routing, urgency_detection |
| `Supporter` | agent | — | customer_support, empathy, communication |
| `Escalator` | agent | 🔧 `datetime` | escalation, incident_reporting, urgency_classification |

> ⚡ **Orchestrator tools** (`calculator` and `datetime`) are **always active** on both orchestrators and are pinned in the UI — they cannot be removed. These tools are required for UTC timezone arithmetic when scheduling cron jobs.

### Built-in Templates

| Template | Orchestrator | Specialist Agents | Routing |
|---|---|---|---|
| **Research Hub** | `ResearchOrchestrator` (⚡ calculator, ⚡ datetime) | `Researcher` (web_search, wikipedia), `Summariser` (web_search, wikipedia) | Factual → Researcher (SINGLE); research+brief → Researcher→Summariser (PIPELINE); compound → both (FANOUT) |
| **Support Triage** | `SupportOrchestrator` (⚡ calculator, ⚡ datetime) | `Supporter`, `Escalator` (datetime) | Routine → Supporter (SINGLE); urgent/complex → Escalator (SINGLE) |

### Tool Registry

| Tool | What it does | Used by |
|---|---|---|
| `datetime` | Returns current UTC date and time | ⚡ Both orchestrators (cron arithmetic), Escalator (timestamps) |
| `calculator` | Safe `eval` of math expressions using Python `math` module | ⚡ Both orchestrators (UTC offset arithmetic) |
| `web_search` | DuckDuckGo Instant Answer API (no key required) | Researcher, Summariser |
| `wikipedia` | Wikipedia REST API summary (~400 chars) | Researcher, Summariser |

### Visual Builder — Tool Badges

Every agent node on the ReactFlow canvas displays its tools inline:

- **⚡ Teal badge** — orchestrator-pinned tools (`calculator`, `datetime`). Always shown, cannot be removed via the edit modal.
- **🔧 Amber badge** — specialist tools (e.g. `web_search`, `wikipedia`).
- **📡 Blue badge** — messaging channels (e.g. `telegram`).

This makes the workflow topology immediately readable — you can see at a glance which tools each agent brings to the workflow.

### Backend (`app/`)

| Path | Responsibility |
|---|---|
| `main.py` | FastAPI app, CORS, lifespan: DB init + Telegram setup + scheduler startup |
| `api/agents.py` | Full CRUD: `GET/POST /agents`, `GET/PATCH/DELETE /agents/{id}` |
| `api/workflows.py` | `POST /workflows/demo-run`, `GET /workflows/runs`, `GET /workflows/runs/{id}/messages` |
| `api/workflow_templates.py` | `GET/POST /workflow-templates`, `DELETE /workflow-templates/{id}` |
| `api/monitor.py` | WebSocket `/ws/monitor` — broadcasts run events |
| `api/telegram.py` | Telegram webhook receiver |
| `api/health.py` | Health check endpoint |
| `runtime/agent_graph.py` | LangGraph `StateGraph` — all four routing modes, retry/feedback loop, guardrails, token tracking |
| `runtime/tools.py` | Tool registry: `datetime`, `calculator`, `web_search`, `wikipedia` |
| `runtime/llm.py` | `get_llm(model)` — returns a `ChatGroq` instance |
| `runtime/state.py` | `WorkflowState` TypedDict (includes `pipeline_mode`, `pipeline_stage`, `pipeline_queue`) |
| `db/init_db.py` | Creates tables, seeds built-in agents + templates (upserts on restart) |
| `core/broadcast.py` | Async pub/sub queue for WebSocket monitor events |
| `services/scheduler_service.py` | APScheduler cron jobs (UTC only) for scheduled agent runs |
| `services/memory_service.py` | Per-session conversation memory for orchestrator agents |

### Retry / Feedback Loop

After every specialist run, `retry_check_node` evaluates the output:

- **Empty response** → retry (re-route to or