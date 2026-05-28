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

Guardrails
----------
  - forbidden_topics : list[str] — if any topic keyword appears in the output,
    the response is replaced with a refusal message.
  - max_output_chars  : int | None — output is hard-truncated at this limit.

Token tracking
--------------
  usage_metadata from every LLM call is accumulated into state["token_usage"].
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.runtime.llm import get_llm
from app.runtime.state import TokenUsage, WorkflowState
from app.runtime.tools import format_tools_for_prompt, get_tools_for_agent

logger = logging.getLogger(__name__)

# Groq cost per 1k tokens (USD) — approximate, update as needed
_COST_PER_1K = {
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
    "llama-3.1-8b-instant": (0.00005, 0.00008),
    "mixtral-8x7b-32768": (0.00024, 0.00024),
    "gemma2-9b-it": (0.00020, 0.00020),
    "llama-3.1-70b-specdec": (0.00059, 0.00099),
}
_DEFAULT_COST = (0.00020, 0.00020)


def _extract_usage(response) -> dict:
    """Pull token counts from a LangChain LLM response safely."""
    meta = getattr(response, "usage_metadata", None) or {}
    return {
        "prompt_tokens": meta.get("input_tokens", 0),
        "completion_tokens": meta.get("output_tokens", 0),
        "total_tokens": meta.get("total_tokens", 0),
    }


def _accumulate_usage(existing: dict, new: dict) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=existing.get("prompt_tokens", 0) + new.get("prompt_tokens", 0),
        completion_tokens=existing.get("completion_tokens", 0) + new.get("completion_tokens", 0),
        total_tokens=existing.get("total_tokens", 0) + new.get("total_tokens", 0),
    )


def _estimate_cost(model: str, usage: dict) -> float:
    in_cost, out_cost = _COST_PER_1K.get(model, _DEFAULT_COST)
    return (
        usage.get("prompt_tokens", 0) / 1000 * in_cost
        + usage.get("completion_tokens", 0) / 1000 * out_cost
    )


def _apply_guardrails(
    text: str,
    forbidden_topics: list[str],
    max_output_chars: int | None,
    agent_name: str,
) -> str:
    """Enforce output guardrails: forbidden topic blocking + length cap."""
    # 1. Forbidden topic check (case-insensitive keyword match)
    if forbidden_topics:
        text_lower = text.lower()
        for topic in forbidden_topics:
            if topic.strip().lower() in text_lower:
                logger.warning(
                    "[%s] guardrail blocked output — forbidden topic '%s' detected.",
                    agent_name, topic,
                )
                return (
                    f"[Guardrail] I\'m not able to provide information on \"{topic}\" "
                    "as it falls outside my permitted scope."
                )
    # 2. Output length cap
    if max_output_chars and len(text) > max_output_chars:
        logger.info(
            "[%s] output truncated from %d to %d chars (max_output_chars guardrail).",
            agent_name, len(text), max_output_chars,
        )
        text = text[:max_output_chars] + " … [truncated]"
    return text


async def run_agent_with_tools(
    system_prompt: str,
    user_message: str,
    tool_names: list[str],
    agent_name: str,
    forbidden_topics: list[str] | None = None,
    max_output_chars: int | None = None,
    model: str = "",
) -> tuple[str, list[dict], TokenUsage]:
    llm = get_llm(model) if model else get_llm()
    tool_calls_log: list[dict] = []
    tools = get_tools_for_agent(tool_names)
    usage_acc: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

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
    usage_acc = _accumulate_usage(usage_acc, _extract_usage(response))
    reply = response.content.strip()

    if tools and reply.startswith("{"):
        try:
            parsed = json.loads(reply)
            tool_name = parsed.get("tool", "")
            tool_input = parsed.get("input", "")

            if tool_name in tools:
                logger.info("[%s] calling tool: %s(%s)", agent_name, tool_name, tool_input)
                tool_result = await tools[tool_name](tool_input)
                tool_calls_log.append({"tool": tool_name, "input": tool_input, "result": tool_result})

                followup = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                    SystemMessage(content=f"Tool result from {tool_name}:\n{tool_result}\nNow provide your final answer."),
                ]
                final_response = await llm.ainvoke(followup)
                usage_acc = _accumulate_usage(usage_acc, _extract_usage(final_response))
                reply = final_response.content.strip()
        except (json.JSONDecodeError, KeyError):
            pass

    # Apply guardrails
    reply = _apply_guardrails(
        reply,
        forbidden_topics=forbidden_topics or [],
        max_output_chars=max_output_chars,
        agent_name=agent_name,
    )

    return reply, tool_calls_log, TokenUsage(**usage_acc)


async def llm_route(
    user_input: str,
    orchestrator_system_prompt: str,
    specialist_agents: list[dict],
    model: str = "",
) -> tuple[dict[str, Any], TokenUsage]:
    llm = get_llm(model) if model else get_llm()

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
    usage = _extract_usage(response)
    reply = response.content.strip()

    json_match = re.search(r'\{.*?\}', reply, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return data, TokenUsage(**usage)
        except json.JSONDecodeError:
            pass

    fallback = specialist_agents[0]["name"] if specialist_agents else "fallback"
    return {"target": fallback, "reason": "routing fallback"}, TokenUsage(**usage)


def build_agent_graph(
    orchestrator: dict,
    specialists: list[dict],
):
    """
    Build and compile a LangGraph from agent configs.
    Deduplicates specialists by name before building to prevent
    'Node already present' ValueError from LangGraph.
    """
    if not specialists:
        raise ValueError("At least one specialist agent is required.")

    seen: set[str] = set()
    unique_specialists: list[dict] = []
    for s in specialists:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique_specialists.append(s)
        else:
            logger.warning("Duplicate specialist '%s' dropped in graph builder.", s["name"])
    specialists = unique_specialists
    specialists = [s for s in specialists if s["name"] != orchestrator["name"]]

    specialist_map = {a["name"]: a for a in specialists}

    async def orchestrator_node(state: WorkflowState) -> WorkflowState:
        state["current_step"] = "orchestrator"
        state["status"] = "running"
        route, usage = await llm_route(
            user_input=state["user_input"],
            orchestrator_system_prompt=orchestrator["system_prompt"],
            specialist_agents=specialists,
            model=orchestrator.get("model", ""),
        )
        state["routing_decision"] = route.get("target", specialists[0]["name"])
        state["routing_reason"] = route.get("reason", "")
        # Accumulate tokens
        existing = state.get("token_usage") or {}
        state["token_usage"] = _accumulate_usage(existing, usage)
        logger.info("Orchestrator routed to: %s (%s)", state["routing_decision"], state["routing_reason"])
        return state

    def route_from_orchestrator(state: WorkflowState) -> str:
        target = state.get("routing_decision", "")
        if target in specialist_map:
            return target
        return specialists[0]["name"]

    def make_specialist_node(agent_config: dict):
        async def specialist_node(state: WorkflowState) -> WorkflowState:
            name = agent_config["name"]
            tool_names = agent_config.get("tools", [])
            state["current_step"] = name

            # Parse guardrail fields (stored as JSON strings in DB, dicts in memory)
            forbidden = agent_config.get("forbidden_topics", [])
            if isinstance(forbidden, str):
                try:
                    forbidden = json.loads(forbidden)
                except json.JSONDecodeError:
                    forbidden = []
            max_chars = agent_config.get("max_output_chars")

            response, tool_calls, usage = await run_agent_with_tools(
                system_prompt=agent_config["system_prompt"],
                user_message=state["user_input"],
                tool_names=tool_names,
                agent_name=name,
                forbidden_topics=forbidden,
                max_output_chars=max_chars,
                model=agent_config.get("model", ""),
            )

            state["research_notes"] = response
            state["tool_calls"] = tool_calls
            state["final_response"] = response
            state["status"] = "completed"
            # Accumulate tokens
            existing = state.get("token_usage") or {}
            state["token_usage"] = _accumulate_usage(existing, usage)
            return state

        specialist_node.__name__ = agent_config["name"]
        return specialist_node

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
