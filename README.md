# Yuno Agent Platform

A full-stack multi-agent orchestration platform. Create agents, wire them into workflows on a visual canvas, run them against real LLMs (via Groq), and monitor execution live — all from a browser UI or a Telegram bot.

---

## What It Does

- **Agent management** — create, edit, and delete agents with custom system prompts, models, tools, guardrails, and channel assignments
- **Visual workflow canvas** — drag agents onto a ReactFlow canvas and wire them up; the selected agent list is the live workflow definition
- **LangGraph execution** — an orchestrator agent uses LLM-based routing to select a specialist agent; the specialist runs with optional tool calls
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
| Messaging | python-telegram-bot (webhook mode) |
| Testing | pytest + pytest-asyncio (backend), Vitest + Testing Library (frontend) |

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
  guardrails check (forbidden_topics, max_output_chars)
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
| `runtime/agent_graph.py` | LangGraph `StateGraph` — orchestrator + specialist nodes, guardrails, token tracking |
| `runtime/tools.py` | Tool registry: `datetime`, `calculator`, `web_search` (DuckDuckGo), `wikipedia` |
| `runtime/llm.py` | `get_llm(model)` — returns a `ChatGroq` instance |
| `runtime/state.py` | `WorkflowState` TypedDict and `TokenUsage` dataclass |
| `runtime/demo_graph.py` | Legacy hardcoded demo graph (kept for reference) |
| `db/init_db.py` | Creates tables, seeds 5 built-in agents + 2 built-in templates (idempotent) |
| `core/broadcast.py` | Async pub/sub queue for WebSocket monitor events |
| `models/agent.py` | `Agent` SQLAlchemy model (name, role, system_prompt, model, tools, channels, guardrails) |
| `models/workflow_run.py` | `WorkflowRun` model (status, input/output, token usage, cost) |
| `models/workflow_message.py` | Per-message log (sender, receiver, type, content) |
| `models/workflow_template.py` | `WorkflowTemplate` model (agent_ids, edges JSON, is_builtin flag) |

### Frontend (`frontend/src/`)

All UI logic lives in `App.jsx` (single-file app). Sections:

- **Agents tab** — list, create, and delete agents; shows model, tools, guardrail config
- **Workflow canvas tab** — ReactFlow canvas; drag agents to build a workflow; run it with a prompt
- **Run history tab** — paginated list of past runs with status, tokens, and cost
- **Message log** — per-run message thread (orchestrator ↔ specialist exchange)
- **Live monitor** — WebSocket-connected event feed

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

### Agent Guardrails

Each agent supports two output-level guardrails configured at creation time:

- **`forbidden_topics`** — list of keywords; if any appear in the output, the response is replaced with a refusal message
- **`max_output_chars`** — hard character cap; output is truncated if exceeded

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
│   │   ├── run_service.py
│   │   ├── telegram_service.py
│   │   ├── workflow_service.py
│   │   └── workflow_template_service.py
│   └── main.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── App.css
│   │   ├── App.test.jsx
│   │   ├── index.css
│   │   ├── main.jsx
│   │   └── setupTests.js
│   ├── package.json
│   └── vite.config.js
├── tests/
│   └── test_api.py
├── pytest.ini
└── README.md
```

---

## Setup

### 1. Clone

```bash
git clone https://github.com/mayankrdseth/yuno-agent-platform.git
cd yuno-agent-platform
```

### 2. Backend

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Environment variables

Create `.env` in the project root:

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

### 4. Frontend

```bash
cd frontend
npm install
```

---

## Running

### Backend

```bash
uvicorn app.main:app --reload
# → http://127.0.0.1:8000
# → API docs at http://127.0.0.1:8000/docs
```

The first startup auto-creates the SQLite database and seeds the two built-in templates and five built-in agents.

### Frontend

```bash
cd frontend
npm run dev
# → http://localhost:5173
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
| `GET` | `/` | Root / health check |
| `GET` | `/health` | Health endpoint |
| `WS` | `/ws/monitor` | WebSocket live event stream |
| `POST` | `/telegram/webhook` | Telegram webhook receiver |

---

## Running Tests

### Backend

```bash
python -m pytest tests/test_api.py -v
```

Covers: root endpoint, agent creation, agent listing, run listing, and run-not-found error.

### Frontend

```bash
cd frontend
npm run test:run
```

---

## Telegram Bot Flow

1. Set your bot webhook to point at `POST /telegram/webhook`
2. Send a message — greetings are handled inline; task prompts trigger a full workflow run
3. The bot replies with the final response from the specialist agent
4. The run is persisted and visible in the dashboard run history

---

## Token Usage & Cost Tracking

Every workflow run records:

- `prompt_tokens`, `completion_tokens`, `total_tokens`
- `estimated_cost_usd` — calculated per model using hardcoded Groq rates

Supported model cost table (approximate, USD per 1k tokens):

| Model | Input | Output |
|---|---|---|
| `llama-3.3-70b-versatile` | $0.00059 | $0.00079 |
| `llama-3.1-8b-instant` | $0.00005 | $0.00008 |
| `mixtral-8x7b-32768` | $0.00024 | $0.00024 |
| `gemma2-9b-it` | $0.00020 | $0.00020 |
