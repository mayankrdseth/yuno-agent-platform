from sqlalchemy.ext.asyncio import AsyncSession

from app.core.broadcast import publish
from app.runtime.demo_graph import build_demo_graph
from app.runtime.state import WorkflowState
from app.services.run_service import add_message

_demo_graph = build_demo_graph()


async def run_demo_workflow(db: AsyncSession, run_id: int, user_input: str) -> WorkflowState:
    await add_message(db, run_id, "user", user_input, receiver="orchestrator", message_type="input")
    await publish(
        {
            "run_id": run_id,
            "sender": "user",
            "receiver": "orchestrator",
            "content": user_input,
            "type": "input",
        }
    )

    initial_state: WorkflowState = {
        "user_input": user_input,
        "current_step": "start",
        "research_notes": "",
        "final_response": "",
        "status": "pending",
    }

    await add_message(
        db,
        run_id,
        "orchestrator",
        "Routing task to research_agent",
        receiver="research_agent",
        message_type="log",
    )
    await publish(
        {
            "run_id": run_id,
            "sender": "orchestrator",
            "receiver": "research_agent",
            "content": "Routing task to research_agent",
            "type": "log",
        }
    )

    result = await _demo_graph.ainvoke(initial_state)

    await add_message(
        db,
        run_id,
        "research_agent",
        result["research_notes"],
        receiver="writer_agent",
        message_type="agent_message",
    )
    await publish(
        {
            "run_id": run_id,
            "sender": "research_agent",
            "receiver": "writer_agent",
            "content": result["research_notes"],
            "type": "agent_message",
        }
    )

    await add_message(
        db,
        run_id,
        "writer_agent",
        result["final_response"],
        receiver="user",
        message_type="output",
    )
    await publish(
        {
            "run_id": run_id,
            "sender": "writer_agent",
            "receiver": "user",
            "content": result["final_response"],
            "type": "output",
        }
    )

    return result