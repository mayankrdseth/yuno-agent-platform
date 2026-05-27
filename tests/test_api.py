import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_root(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_create_agent(client):
    payload = {
        "name": "Test Agent",
        "role": "researcher",
        "system_prompt": "You are a test agent.",
        "model": "llama-3.3-70b-versatile",
        "tools": ["web_search"],
        "channels": ["telegram"],
        "is_active": True,
        "max_iterations": 5,
        "memory_enabled": True,
        "schedule": None,
    }
    response = await client.post("/agents", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Agent"
    assert data["role"] == "researcher"


@pytest.mark.asyncio
async def test_list_agents(client):
    response = await client.get("/agents")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_list_runs(client):
    response = await client.get("/workflows/runs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_run_messages_not_found(client):
    response = await client.get("/workflows/runs/99999/messages")
    assert response.status_code == 404