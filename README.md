# Yuno Agent Orchestration Platform

A full-stack multi-agent orchestration demo platform built for the Yuno AI Engineer Challenge.[cite:1]

The platform allows users to:
- create and manage AI agents
- trigger workflow runs
- inspect run and message history
- monitor live workflow events
- interact with the system through a Telegram bot.[cite:1]

## Overview

This project demonstrates a lightweight orchestration platform for autonomous agents, combining a FastAPI backend, a React frontend, workflow execution logic, persistence, and Telegram integration.[cite:1]

The goal is to simulate how an AI operations platform can coordinate multiple agents, track workflow runs, and expose the system through both a dashboard and a messaging interface.[cite:1]

## Features

- Agent creation and management through REST APIs and frontend UI.[cite:1]
- Workflow execution endpoint for running demo orchestration tasks.[cite:1]
- Persistent workflow run history and message logs.[cite:1]
- Live monitoring stream using WebSocket updates.[cite:1]
- Telegram bot integration for triggering workflows externally.[cite:1]
- Frontend test coverage using Vitest.
- Backend API test coverage using pytest.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, Python, SQLAlchemy, SQLite |
| Frontend | React, Vite, React Flow |
| Messaging | Telegram Bot API |
| Workflow | LangGraph-based demo workflow |
| LLM | Groq API |
| Testing | pytest, Vitest |

## Architecture

### Backend
The backend is built with FastAPI and exposes APIs for agent management, workflow execution, run history retrieval, and monitoring.[cite:1]

It also handles Telegram webhook processing and forwards eligible user prompts into the workflow execution path.[cite:1]

### Frontend
The frontend is a React + Vite dashboard that provides:
- agent creation
- workflow execution
- workflow visualization
- run history inspection
- live monitoring

React Flow is used to present a simple workflow builder view.

### Persistence
SQLite stores:
- agents
- workflow runs
- workflow messages

This keeps the demo lightweight and easy to run locally.

### Telegram Integration
Telegram acts as an external user interface for workflow triggering. Greeting-like messages are handled separately for a cleaner user experience, while actual task prompts are routed into the workflow execution path.

## Project Structure

```text
yuno-agent-platform/
├── app/
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   └── main.py
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── tests/
│   └── test_api.py
├── README.md
└── pytest.ini
```

## Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd yuno-agent-platform
```

### 2. Create and activate virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install backend dependencies

```bash
pip install -r requirements.txt
```

If a `requirements.txt` file is not available yet, install the main dependencies manually:

```bash
pip install fastapi uvicorn sqlalchemy aiosqlite python-telegram-bot httpx pytest pytest-asyncio
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
APP_NAME=Yuno Agent Platform
APP_ENV=dev
DEBUG=true

DATABASE_URL=sqlite+aiosqlite:///./yuno.db

GROQ_API_KEY=your_groq_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_WEBHOOK_SECRET=your_webhook_secret_if_used
```

## Running the Backend

```bash
uvicorn app.main:app --reload
```

Backend default URL:
- `http://127.0.0.1:8000`

## Running the Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend default URL:
- `http://localhost:5173`

## Running Tests

### Backend tests

From project root:

```bash
python -m pytest tests/test_api.py -v
```

### Frontend tests

From `frontend/`:

```bash
npm run test:run
```

## Key API Endpoints

| Method | Endpoint | Purpose |
|-------|----------|---------|
| GET | `/` | Health/root endpoint |
| GET | `/agents` | List agents |
| POST | `/agents` | Create a new agent |
| POST | `/workflows/demo-run` | Run demo workflow |
| GET | `/workflows/runs` | List workflow runs |
| GET | `/workflows/runs/{run_id}/messages` | Get messages for a run |
| WS | `/ws/monitor` | Live workflow monitoring stream |

## Telegram Bot Flow

1. User sends a message to the Telegram bot.
2. Greeting-like inputs are answered directly.
3. Task-like inputs are routed to the demo workflow.
4. A workflow run is created in the database.
5. Messages are stored and exposed in the dashboard.
6. Live monitor events appear in the UI.

## Demo Walkthrough

Suggested demo flow:
1. Open the frontend dashboard.
2. Create an agent.
3. Run a workflow from the dashboard.
4. Inspect workflow run history.
5. Open run messages.
6. Show live monitor activity.
7. Send a task to the Telegram bot.
8. Verify the run appears in the dashboard.

## Known Limitations

- Workflow builder is currently a visual demo, not a full drag-and-drop execution editor.
- SQLite is used for simplicity and local demo speed.
- Telegram interaction currently supports a lightweight rule-based greeting/task split.
- Error handling and production deployment hardening can be extended further.

## Future Improvements

- Editable workflow graphs
- Better agent-to-agent routing logic
- Richer monitoring analytics
- Authentication and multi-user support
- Deployment with managed database and production webhook hosting

## Submission Notes

This project was built as a focused challenge submission to demonstrate:
- backend API design
- async workflow execution
- persistence and monitoring
- frontend integration
- messaging channel integration through Telegram.[cite:1]