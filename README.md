# Yuno Agent Platform

A full-stack multi-agent orchestration platform. Create agents, wire them into workflows on a visual canvas, run them against real LLMs (via Groq), and monitor execution live — all from a browser UI or a Telegram bot.

---

## What It Does

- **Agent management** — create, edit, and delete agents with custom system prompts, models, tools, guardrails, skills, and interaction rules
- **Visual workflow canvas** — drag agents onto a ReactFlow canvas and wire them up; the selected agent list is the live workflow definition
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
2. **Researcher** runs on `user_input`, stores detailed findings in `state["research_notes"]`, does NOT surface output yet
3. **pipeline_handoff_node** advances the queue, sets `pipeline_stage="summarise"`
4. **Summariser** receives `research_notes` as its input (not raw `user_input`) → produces a structured TL;DR brief
5. Final response is the Summariser's brief — the Researcher's raw output is internal

This is the key difference from FANOUT: in FANOUT both agents get `user_input` and run independently. In PIPELINE, Agent B gets Agent A's output.

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

- **Empty response** → retry (re-route to orchestrator, which picks a different specialist)
- **Guardrail refusal** (`[Guardrail] ...` prefix) → retry
- **Max retries reached** (2×) → graceful error response

On retry, the orchestrator receives the previous output as context so it deliberately picks a different approach.

### Scheduled Workflows

Agents support natural-language scheduling via the `schedule` and `schedule_prompt` fields:

- **`schedule`** — UTC cron expression (e.g. `27 12 * * *`). The orchestrator uses its `calculator` and `datetime` tools to convert any user-mentioned timezone (IST, EST, PST, CET, etc.) to UTC precisely.
- **`schedule_prompt`** — the task text sent to the workflow when the cron fires

Example: user says *"send me a news briefing every day at 9 AM IST"*
→ Orchestrator computes: 9:00 IST = 9×60 − 330 = 210 min = 3:30 UTC → cron: `30 3 * * *`
→ Confirmation shows original time and UTC equivalent so the user can verify

### Built-in Templates

| Template | Orchestrator | Agents | Routing |
|---|---|---|---|
| **Research Hub** | `ResearchOrchestrator` | `Researcher` (web_search, wikipedia), `Summariser` (web_search, wikipedia) | Factual → Researcher (SINGLE); research+brief → Researcher→Summariser (PIPELINE); compound → both (FANOUT) |
| **Support Triage** | `SupportOrchestrator` | `Supporter`, `Escalator` (datetime) | Routine → Supporter (SINGLE); urgent/complex → Escalator (SINGLE) |

**Orchestrators** in both templates have `calculator` and `datetime` tools for precise UTC arithmetic during scheduling.

### Tool Registry

| Tool | What it does | Used by |
|---|---|---|
| `datetime` | Returns current UTC date and time | Orchestrators (cron arithmetic), Escalator (timestamps) |
| `calculator` | Safe `eval` of math expressions using Python `math` module | Orchestrators (UTC offset arithmetic) |
| `web_search` | DuckDuckGo Instant Answer API (no key required) | Researcher, Summariser |
| `wikipedia` | Wikipedia REST API summary (~400 chars) | Researcher, Summariser |

### Agent Configuration — All 5 Dimensions

The challenge requires agents to be configurable across five dimensions. All five are implemented:

| Dimension | Field(s) | Purpose |
|---|---|---|
| **Schedules** | `schedule` (UTC cron), `schedule_prompt` (task text) | When and what the agent runs automatically |
| **Memory** | `memory_enabled` (bool), `max_iterations` (int) | Whether the orchestrator retains conversation history and how many turns to inject |
| **Skills** | `skills` (list of strings) | Capability labels injected into the orchestrator's routing prompt for smarter routing |
| **Interaction Rules** | `interaction_rules` (list of strings) | Behavioural constraints appended to the agent's system prompt on every LLM call |
| **Guardrails** | `forbidden_topics` (list), `max_output_chars` (int) | Hard limits: keyword-triggered refusal and character cap on output |

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
| `GET` | `/health` | Health check |
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

Every workflow run records `prompt_tokens`, `completion_tokens`, `total_tokens`, and `estimated_cost_usd`:

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

---

## Adding New Workflow Templates

Add an entry to `BUILTIN_TEMPLATES` and `BUILTIN_AGENTS` in `app/db/init_db.py`, then restart the backend. The platform upserts on every startup so no DB wipe is needed.

For custom templates via the API, `POST /workflow-templates` with:
```json
{
  "name": "My Template",
  "description": "What it does",
  "agent_ids": ["AgentA", "AgentB"],
  "edges": [{"source": "AgentA", "target": "AgentB"}]
}
```

## Adding a New Messaging Channel

1. Create `app/api/<channel>.py` with a webhook receiver endpoint
2. Create `app/services/<channel>_service.py` with send/receive logic
3. Register the router in `app/main.py`
4. Add the channel name to the `channels` field on whichever agents should be reachable via it
