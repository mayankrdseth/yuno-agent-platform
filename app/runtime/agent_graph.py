"""
Dynamic multi-agent LangGraph.

Architecture
------------
  user_input
      ↓
  orchestrator_node   ← loaded from DB (main agent)
      ↓  (LLM router decides target)
  specialist_node     ← one of N saved agents
      ↓  (agent runs, optionally calls tools)
  response back to caller

The graph is built dynamically at runtime using agent config from the database.
Every routing decision is made by the LLM, not hard-coded rules.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.runtime.llm import get_llm
from app.runtime.state import WorkflowState
from app.runtime.tools import format_tools_for_prompt, get_tools_for_agent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: run a single LLM call with optional tool execution
# ---------------------------------------------------------------------------

async def run_agent_with_tools(
    system_prompt: str,
    user_message: str,
    tool_names: list[str],
    agent_name: str,
) -> tuple[str, list[dict]]:
    """
    Run an agent:
    1. Ask the LLM if it needs a tool.
    2. If yes, execute the tool and feed result back.
    3. Return the final text response and a log of tool calls made.
    """
    llm = get_llm()
    tool_calls_log: list[dict] = []
    tools = get_tools_for_agent(tool_names)

    tool_section = ""
    if tools:
        tool_section = (
            "\n\nYou have access to these tools. "
            "To use a tool, respond ONLY with a JSON object like:\n"
            '{"tool": "<tool_name>", "input": "<input_string>"}\n'
            "Otherwise respond normally with your answer.\n"
            f"Available tools:\n{format_tools_for_prompt(tool_names)}"
        )

    messages = [
        SystemMessage(content=system_prompt + tool_section),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    reply = response.content.strip()

    # Check if the LLM decided to call a tool
    if tools and reply.startswith("{"):
        try:
            parsed = json.loads(reply)
            tool_name = parsed.get("tool", "")
            tool_input = parsed.get("input", "")

            if tool_name in tools:
                logger.info("[%s] calling tool: %s(%s)", agent_name, tool_name, tool_input)
                tool_result = await tools[tool_name](tool_input)
                tool_calls_log.append({"tool": tool_name, "input": tool_input, "result": tool_result})

                # Second LLM call with tool result incorporated
                followup = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                    SystemMessage(content=f"Tool result from {tool_name}:\n{tool_result}\n\nNow provide your final answer."),
                ]
                final_response = await llm.ainvoke(followup)
                reply = final_response.content.strip()
        except (json.JSONDecodeError, KeyError):
            pass  # Not a valid tool call — treat as plain response

    return reply, tool_calls_log


# ---------------------------------------------------------------------------
# LLM Router
# ---------------------------------------------------------------------------

async def llm_route(
    user_input: str,
    orchestrator_system_prompt: str,
    specialist_agents: list[dict],
) -> dict[str, Any]:
    """
    Ask the orchestrator LLM to choose which specialist agent should handle the task.
    Returns {"target": <agent_name>, "reason": <str>}
    """
    llm = get_llm()

    agent_list = "\n".join(
        f"  - {a['name']}: {a['role']} — {a['system_prompt'][:120]}"
        for a in specialist_agents
    )

    routing_prompt = (
        f"{orchestrator_system_prompt}\n\n"
        "You are the orchestrator. Given the user request below, decide which specialist agent "
        "should handle it. Respond ONLY with a JSON object like:\n"
        '{"target": "<agent_name>", "reason": "<short reason>"}\n\n'
        f"Available agents:\n{agent_list}\n\n"
        f"User request: {user_input}"
    )

    response = await llm.ainvoke(routing_prompt)
    reply = response.content.strip()

    # Extract JSON even if LLM wraps it in markdown code blocks
    json_match = re.search(r'\{.*?\}', reply, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return data
        except json.JSONDecodeError:
            pass

    # Fallback: pick first specialist
    fallback = specialist_agents[0]["name"] if specialist_agents else "fallback"
    return {"target": fallback, "reason": "routing fallback"}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_agent_graph(
    orchestrator: dict,
    specialists: list[dict],
):
    """
    Build and compile a LangGraph from agent configs.

    Parameters
    ----------
    orchestrator : dict with keys name, role, system_prompt, tools (list[str])
    specialists  : list of dicts with the same keys
    """

    if not specialists:
        raise ValueError("At least one specialist agent is required to build a workflow.")

    specialist_map = {a["name"]: a for a in specialists}

    # -- Orchestrator node --
    async def orchestrator_node(state: WorkflowState) -> WorkflowState:
        state["current_step"] = "orchestrator"
        state["status"] = "running"

        route = await llm_route(
            user_input=state["user_input"],
            orchestrator_system_prompt=orchestrator["system_prompt"],
            specialist_agents=specialists,
        )

        state["routing_decision"] = route.get("target", specialists[0]["name"])
        state["routing_reason"] = route.get("reason", "")
        logger.info("Orchestrator routed to: %s (%s)", state["routing_decision"], state["routing_reason"])
        return state

    # -- Routing function --
    def route_from_orchestrator(state: WorkflowState) -> str:
        target = state.get("routing_decision", "")
        if target in specialist_map:
            return target
        return specialists[0]["name"]  # safe fallback

    # -- Specialist node factory --
    def make_specialist_node(agent_config: dict):
        async def specialist_node(state: WorkflowState) -> WorkflowState:
            name = agent_config["name"]
            tool_names = agent_config.get("tools", [])
            state["current_step"] = name

            response, tool_calls = await run_agent_with_tools(
                system_prompt=agent_config["system_prompt"],
                user_message=state["user_input"],
                tool_names=tool_names,
                agent_name=name,
            )

            state["research_notes"] = response
            state["tool_calls"] = tool_calls
            state["final_response"] = response
            state["status"] = "completed"
            return state

        specialist_node.__name__ = agent_config["name"]
        return specialist_node

    # -- Build graph --
    graph = StateGraph(WorkflowState)
    graph.add_node("orchestrator", orchestrator_node)

    for agent in specialists:
        graph.add_node(agent["name"], make_specialist_node(agent))

    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {a["name"]: a["name"] for a in specialists},
    )

    for agent in specialists:
        graph.add_edge(agent["name"], END)

    return graph.compile()
