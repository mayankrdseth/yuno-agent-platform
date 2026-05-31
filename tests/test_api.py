"""
API test suite.

Coverage:
  - Health / root
  - Agent CRUD (create, list, get by id, patch, patch 404, delete, delete 404)
  - Skills + interaction_rules round-trip (verifies serialize_agent fix)
  - WorkflowRunSummary field names (verifies estimated_cost_usd not total_cost_usd)
  - Run history (list, messages 200, messages 404)
  - Workflow templates (list, create, load built-in, delete)
  - Scheduled jobs (list)
  - demo-run guard: <2 agents rejected with 400
"""
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


# ── Helpers ───────────────────────────────────────────────────────────────────

BASE_AGENT = {
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


async def _create_agent(client, overrides=None) -> dict:
    payload = {**BASE_AGENT, **(overrides or {})}
    resp = await client.post("/agents", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Root ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_root(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()


# ── Agent CRUD ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_agent(client):
    data = await _create_agent(client)
    assert data["name"] == "Test Agent"
    assert data["role"] == "researcher"


@pytest.mark.asyncio
async def test_list_agents(client):
    response = await client.get("/agents")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_agent_by_id(client):
    created = await _create_agent(client, {"name": "ByID Agent"})
    agent_id = created["id"]
    resp = await client.get(f"/agents/{agent_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == agent_id


@pytest.mark.asyncio
async def test_get_agent_not_found(client):
    resp = await client.get("/agents/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_agent(client):
    created = await _create_agent(client, {"name": "Patch Target"})
    agent_id = created["id"]
    resp = await client.patch(f"/agents/{agent_id}", json={"name": "Patched Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Patched Name"


@pytest.mark.asyncio
async def test_patch_agent_not_found(client):
    resp = await client.patch("/agents/99999", json={"name": "Ghost"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_agent(client):
    created = await _create_agent(client, {"name": "Delete Me"})
    agent_id = created["id"]
    del_resp = await client.delete(f"/agents/{agent_id}")
    assert del_resp.status_code == 204
    # Confirm it's gone
    get_resp = await client.get(f"/agents/{agent_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_agent_not_found(client):
    resp = await client.delete("/agents/99999")
    assert resp.status_code == 404


# ── Skills + interaction_rules round-trip ─────────────────────────────────────
# Verifies the serialize_agent() fix: both fields must be returned by the API.

@pytest.mark.asyncio
async def test_skills_round_trip(client):
    """Skills set on create must be returned by GET /agents/{id}."""
    created = await _create_agent(client, {
        "name": "Skilled Agent",
        "skills": ["summarisation", "code_review"],
    })
    agent_id = created["id"]
    # Verify create response includes skills
    assert created["skills"] == ["summarisation", "code_review"]

    # Verify GET by id also returns skills
    resp = await client.get(f"/agents/{agent_id}")
    assert resp.status_code == 200
    assert resp.json()["skills"] == ["summarisation", "code_review"]


@pytest.mark.asyncio
async def test_interaction_rules_round_trip(client):
    """interaction_rules set on create must be returned and patchable."""
    created = await _create_agent(client, {
        "name": "Rules Agent",
        "interaction_rules": ["always reply in bullet points", "respond only in English"],
    })
    agent_id = created["id"]
    assert created["interaction_rules"] == [
        "always reply in bullet points",
        "respond only in English",
    ]

    # Patch interaction_rules
    patch_resp = await client.patch(
        f"/agents/{agent_id}",
        json={"interaction_rules": ["be concise"]},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["interaction_rules"] == ["be concise"]


# ── Run history ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_runs(client):
    response = await client.get("/workflows/runs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_run_summary_field_names(client):
    """
    WorkflowRunSummary must expose 'estimated_cost_usd', NOT 'total_cost_usd'.
    This is the contract the frontend depends on.
    """
    response = await client.get("/workflows/runs")
    assert response.status_code == 200
    runs = response.json()
    if runs:
        run = runs[0]
        # Correct field must be present (even if None)
        assert "estimated_cost_usd" in run, (
            "WorkflowRunSummary is missing 'estimated_cost_usd' — "
            "frontend will never render cost. Check WorkflowRunSummary schema."
        )
        # Wrong field must NOT be present
        assert "total_cost_usd" not in run, (
            "WorkflowRunSummary must not expose 'total_cost_usd'. "
            "Frontend reads 'estimated_cost_usd'."
        )


@pytest.mark.asyncio
async def test_run_messages_not_found(client):
    response = await client.get("/workflows/runs/99999/messages")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_run_messages_happy_path(client):
    """Creates a run directly via service to get a real run_id, then fetches messages."""
    from app.db.session import get_db_session
    from app.services.run_service import create_run

    # Get a DB session directly to seed a run
    async for db in get_db_session():
        run = await create_run(db, "test-workflow", "test input")
        run_id = run.id
        break

    resp = await client.get(f"/workflows/runs/{run_id}/messages")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── demo-run guard ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_run_rejects_single_agent(client):
    """demo-run must reject a canvas with only 1 agent."""
    resp = await client.post("/workflows/demo-run", json={
        "user_input": "hello",
        "agent_ids": [1],
    })
    assert resp.status_code == 400
    assert "at least 2 agents" in resp.json()["detail"].lower()


# ── Workflow templates ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_templates(client):
    resp = await client.get("/workflow-templates")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_and_delete_template(client):
    # Need two agent IDs — create them
    a1 = await _create_agent(client, {"name": "Tpl Agent Orch", "role": "orchestrator"})
    a2 = await _create_agent(client, {"name": "Tpl Agent Spec"})

    resp = await client.post("/workflow-templates", json={
        "name": "My Test Template",
        "description": "Created in tests",
        "agent_ids": [a1["id"], a2["id"]],
        "edges": [{"source": str(a1["id"]), "target": str(a2["id"])}],
    })
    assert resp.status_code in (200, 201), resp.text
    tpl = resp.json()
    assert tpl["name"] == "My Test Template"
    tpl_id = tpl["id"]

    # Delete it
    del_resp = await client.delete(f"/workflow-templates/{tpl_id}")
    assert del_resp.status_code in (200, 204)

    # Confirm gone
    templates = (await client.get("/workflow-templates")).json()
    assert all(t["id"] != tpl_id for t in templates)


@pytest.mark.asyncio
async def test_builtin_templates_present(client):
    """At least the two seeded built-in templates must always be returned."""
    resp = await client.get("/workflow-templates")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    # Seeded in init_db — names must exist
    assert any("research" in n.lower() or "support" in n.lower() for n in names), (
        f"Expected seeded built-in templates, got: {names}"
    )


# ── Scheduled jobs ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_scheduled_jobs(client):
    """Scheduled jobs endpoint must return a list (empty is fine on a clean DB)."""
    resp = await client.get("/workflows/scheduled-jobs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
