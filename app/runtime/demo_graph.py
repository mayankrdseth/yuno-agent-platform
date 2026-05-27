from langgraph.graph import END, START, StateGraph
from app.runtime.llm import get_llm
from app.runtime.state import WorkflowState

llm = get_llm()


async def orchestrator_node(state: WorkflowState) -> WorkflowState:
    state["current_step"] = "orchestrator"
    state["status"] = "running"
    return state


async def research_agent_node(state: WorkflowState) -> WorkflowState:
    state["current_step"] = "research_agent"
    prompt = f"""
You are a research agent.
Analyze the user task and produce concise research notes.
Task: {state['user_input']}
"""
    response = await llm.ainvoke(prompt)
    state["research_notes"] = response.content
    return state


async def writer_agent_node(state: WorkflowState) -> WorkflowState:
    state["current_step"] = "writer_agent"
    prompt = f"""
You are a writing agent.
Using the research notes, produce a clear final answer.
Task: {state['user_input']}

Research notes:
{state['research_notes']}
"""
    response = await llm.ainvoke(prompt)
    state["final_response"] = response.content
    state["status"] = "completed"
    return state


def route_after_orchestrator(state: WorkflowState) -> str:
    if state["user_input"].strip():
        return "research_agent"
    return "end"


def build_demo_graph():
    graph = StateGraph(WorkflowState)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("research_agent", research_agent_node)
    graph.add_node("writer_agent", writer_agent_node)
    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {"research_agent": "research_agent", "end": END},
    )
    graph.add_edge("research_agent", "writer_agent")
    graph.add_edge("writer_agent", END)
    return graph.compile()