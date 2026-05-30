"""
Dynamic multi-agent LangGraph.

Architecture
------------
  user_input
      |
  orchestrator_node   <- loaded from DB (orchestrator agent)
      |  1. detect schedule intent (returns {cron, prompt} or null)
      |  2. if no schedule intent: LLM route to specialist
      |  3. build memory_context from last N turns (if memory_enabled)
      |
  specialist_node     <- one of N saved agents
      |  receives enriched prompt: memory_context + user_input
      |
  retry_check_node    <- decides if the response needs to loop back
      |  - empty response           → retry (re-route to different specialist)
      |  - guardrail refusal prefix → retry
      |  - orchestrator explicit    → retry if needs_retry flag set
      |  - max_retries reached      → pass through to END
      |
  response back to caller

Retry / Feedback Loop
---------------------
  After each specialist run, retry_check_node evaluates the output.
  If a retry is warranted AND retry_count < MAX_RETRIES (2), state["needs_retry"]
  is set True and the graph edges route back to the orchestrator for re-routing.
  The orchestrator receives the previous specialist output as additional context
  so it can pick a *different* specialist — enabling sequential multi-agent handling
  of compound / nested queries (e.g. "What is 2+2 and who invented calculus?"
  first hits Mathematician, then on retry the orchestrator routes to Researcher).

Memory
------
  Memory is owned by the orchestrator agent.
  session_key is passed in from the caller ("ui_session" or "telegram_{chat_id}").
  After each run the orchestrator saves the (human, ai) turn pair.

Schedule Detection
------------------
  The orchestrator's LLM call returns an extended JSON:
    {"target": "...", "reason": "...", "schedule_intent": {"cron": "...", "prompt": "..."} | null}
  If schedule_intent is non-null, the graph short-circuits and returns without
  running a specialist — the caller handles job registration.

Guardrails
----------
  - forbidden_topics : list[str]
  - max_output_chars : int | None

Token tracking
--------------
  usage_metadata from every LLM call is accumulated into state["token_usage"].
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.runtime.llm import get_llm
from app.runtime.state import TokenUsage, WorkflowState
from app.runtime.tools import format_tools_for_prompt, get_tools_for_agent

logger = logging.getLogger(__name__)

MAX_RETRIES = 2  # maximum specialist retries per workflow run
_GUARDRAIL_PREFIX = "[Guardrail]"

# Groq cost per 1k tokens (USD)
_COST_PER_1K = {
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
    "llama-3.1-8b-instant": (0.00005, 0.00008),
    "mixtral-8x7b-32768": (0.00024, 0.00024),
    "gemma2-9b-it": (0.00020, 0.00020),
    "llama-3.1-70b-specdec": (0.00059, 0.00099),
}
_DEFAULT_COST = (0.00020, 0.00020)


def _extract_usage(response) -> dict:
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
    if forbidden_topics:
        text_lower = text.lower()
        for topic in forbidden_topics:
            if topic.strip().lower() in text_lower:
                logger.warning("[%s] guardrail blocked — forbidden topic '%s'.", agent_name, topic)
                return (
                    f"{_GUARDRAIL_PREFIX} I'm not able to provide information on \"{topic}\" "
                    "as it falls outside my permitted scope."
                )
    if max_output_chars and len(text) > max_output_chars:
        logger.info("[%s] output truncated %d -> %d chars.", agent_name, len(text), max_output_chars)
        text = text[:max_output_chars] + " … [truncated]"
    return text


def _format_memory_context(memory_turns: list[dict]) -> str:
    """Convert memory rows into a readable context block for the specialist prompt."""
    if not memory_turns:
        return ""
    lines = ["Conversation history (most recent last):"]
    for m in memory_turns:
        prefix = "User" if m["role"] == "human" else "Assistant"
        lines.append(f"  {prefix}: {m['content']}")
    return "\n".join(lines)


async def run_agent_with_tools(
    system_prompt: str,
    user_message: str,
    tool_names: list[str],
    agent_name: str,
    forbidden_topics: list[str] | None = None,
    max_output_chars: int | None = None,
    model: str = "",
    memory_context: str = "",
    previous_attempt: str = "",
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

    # Build message list — inject memory context if present
    messages: list = [SystemMessage(content=system_prompt + tool_section)]
    if memory_context:
        messages.append(SystemMessage(content=memory_context))
    # If a previous attempt was made (retry scenario), give the specialist that context
    if previous_attempt:
        messages.append(
            SystemMessage(
                content=(
                    f"A previous attempt to answer this query produced the following response which "
                    f"was insufficient or blocked:\n\n{previous_attempt}\n\n"
                    "Please provide a better, complete answer."
                )
            )
        )
    messages.append(HumanMessage(content=user_message))

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

    reply = _apply_guardrails(
        reply,
        forbidden_topics=forbidden_topics or [],
        max_output_chars=max_output_chars,
        agent_name=agent_name,
    )
    return reply, tool_calls_log, TokenUsage(**usage_acc)


async def llm_route_and_detect(
    user_input: str,
    orchestrator_system_prompt: str,
    specialist_agents: list[dict],
    model: str = "",
    memory_turns: list[dict] | None = None,
    previous_routing: str = "",
    previous_output: str = "",
) -> tuple[dict[str, Any], TokenUsage]:
    """
    Combined orchestrator LLM call:
      1. Detects schedule intent
      2. If no schedule intent, routes to a specialist
      3. Builds memory_context to pass to the specialist

    On retry runs, previous_routing and previous_output are injected so the
    orchestrator can deliberately choose a DIFFERENT specialist.

    Returns dict with keys:
      target, reason, schedule_intent (null | {cron, prompt}), memory_context
    """
    llm = get_llm(model) if model else get_llm()

    agent_list = "\n".join(
        f"  - {a['name']}: {a['role']} — {a['system_prompt'][:120]}"
        for a in specialist_agents
    )

    history_section = ""
    if memory_turns:
        history_section = "\n\nConversation history so far:\n" + "\n".join(
            f"  {'User' if m['role'] == 'human' else 'Assistant'}: {m['content']}"
            for m in memory_turns
        ) + "\n"

    retry_section = ""
    if previous_routing and previous_output:
        retry_section = (
            f"\n\nPrevious routing attempt: '{previous_routing}' produced this response which "
            f"was insufficient or blocked:\n{previous_output[:300]}\n"
            "Please route to a DIFFERENT specialist that can better handle this query, "
            "or the same specialist with a note that they should try harder.\n"
        )

    routing_prompt = (
        f"{orchestrator_system_prompt}\n"
        f"{history_section}"
        f"{retry_section}\n"
        "You are the orchestrator. For the user request below, do TWO things:\n"
        "1. Check if the user wants to SCHEDULE a recurring task "
        "(phrases like 'every day', 'every morning', 'weekly', 'remind me at', "
        "'schedule this', 'run this at', 'every Monday' etc.).\n"
        "   If yes: extract the cron expression and the actual task prompt.\n"
        "   If no: set schedule_intent to null.\n"
        "2. Choose the best specialist agent for this request (or for the extracted task if scheduled).\n\n"
        "Respond ONLY with a JSON object like:\n"
        "{\n"
        '  "target": "<agent_name>",\n'
        '  "reason": "<short reason>",\n'
        '  "schedule_intent": null\n'
        "}\n"
        "OR if scheduling detected:\n"
        "{\n"
        '  "target": "<agent_name>",\n'
        '  "reason": "<short reason>",\n'
        '  "schedule_intent": {"cron": "<cron_expression>", "prompt": "<task to run on schedule>"}\n'
        "}\n\n"
        f"Available agents:\n{agent_list}\n\n"
        f"User request: {user_input}"
    )

    response = await llm.ainvoke(routing_prompt)
    usage = _extract_usage(response)
    reply = response.content.strip()

    json_match = re.search(r'\{.*\}', reply, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            # Build memory_context for specialist
            memory_context = _format_memory_context(memory_turns or [])
            data["memory_context"] = memory_context
            return data, TokenUsage(**usage)
        except json.JSONDecodeError:
            pass

    fallback = specialist_agents[0]["name"] if specialist_agents else "fallback"
    return {
        "target": fallback,
        "reason": "routing fallback",
        "schedule_intent": None,
        "memory_context": "",
    }, TokenUsage(**usage)


def build_agent_graph(
    orchestrator: dict,
    specialists: list[dict],
    memory_turns: list[dict] | None = None,
):
    """
    Build and compile a LangGraph with retry / feedback loop.

    Flow:
      START → orchestrator → specialist → retry_check
                  ↑                            |
                  |____ needs_retry=True ________|
                                               |
                                        needs_retry=False → END

    memory_turns: pre-fetched memory for this session (fetched by workflow_service).
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
            logger.warning("Duplicate specialist '%s' dropped.", s["name"])
    specialists = unique_specialists
    specialists = [s for s in specialists if s["name"] != orchestrator["name"]]
    specialist_map = {a["name"]: a for a in specialists}

    # ── Orchestrator node ────────────────────────────────────────────────────
    async def orchestrator_node(state: WorkflowState) -> WorkflowState:
        state["current_step"] = "orchestrator"
        state["status"] = "running"

        # On retries pass previous routing + output so the orchestrator can
        # choose a different (or better-instructed) specialist
        prev_routing = state.get("routing_decision", "") if state.get("retry_count", 0) > 0 else ""
        prev_output = state.get("last_specialist_output", "") if state.get("retry_count", 0) > 0 else ""

        route, usage = await llm_route_and_detect(
            user_input=state["user_input"],
            orchestrator_system_prompt=orchestrator["system_prompt"],
            specialist_agents=specialists,
            model=orchestrator.get("model", ""),
            memory_turns=memory_turns or [],
            previous_routing=prev_routing,
            previous_output=prev_output,
        )
        state["routing_decision"] = route.get("target", specialists[0]["name"])
        state["routing_reason"] = route.get("reason", "")
        state["schedule_intent"] = route.get("schedule_intent")  # None or {cron, prompt}
        state["memory_context"] = route.get("memory_context", "")
        existing = state.get("token_usage") or {}
        state["token_usage"] = _accumulate_usage(existing, usage)
        state["needs_retry"] = False  # reset flag each time orchestrator runs
        logger.info(
            "Orchestrator routed to: %s | schedule_intent: %s | retry: %d",
            state["routing_decision"], state["schedule_intent"], state.get("retry_count", 0),
        )
        return state

    def route_from_orchestrator(state: WorkflowState) -> str:
        if state.get("schedule_intent"):
            return "__schedule_end__"
        target = state.get("routing_decision", "")
        if target in specialist_map:
            return target
        return specialists[0]["name"]

    # ── Schedule terminal node ───────────────────────────────────────────────
    async def schedule_end_node(state: WorkflowState) -> WorkflowState:
        intent = state["schedule_intent"]
        state["final_response"] = (
            f"\u2705 Got it! I'll schedule this for you.\n"
            f"Cron: `{intent['cron']}`\n"
            f"Task: {intent['prompt']}"
        )
        state["status"] = "scheduled"
        state["current_step"] = "schedule_end"
        return state

    # ── Retry / feedback-check node ──────────────────────────────────────────
    def retry_check_node(state: WorkflowState) -> WorkflowState:
        """
        Decides whether to retry:
          - response is empty
          - response starts with guardrail prefix
          - AND retry_count has not exceeded MAX_RETRIES
        """
        response = state.get("final_response", "").strip()
        retry_count = state.get("retry_count", 0)

        should_retry = (
            (not response or response.startswith(_GUARDRAIL_PREFIX))
            and retry_count < MAX_RETRIES
        )

        if should_retry:
            logger.info(
                "retry_check: triggering retry %d/%d (response=%r)",
                retry_count + 1, MAX_RETRIES, response[:60],
            )
            state["needs_retry"] = True
            state["retry_count"] = retry_count + 1
            state["last_specialist_output"] = response
            # Clear final_response so it doesn't leak a bad value
            state["final_response"] = ""
        else:
            state["needs_retry"] = False
            if not response:
                # Max retries hit with still no response — give a graceful error
                state["final_response"] = "I was unable to produce a response for this request."
                state["status"] = "failed"
            else:
                state["status"] = "completed"

        return state

    def route_from_retry_check(state: WorkflowState) -> str:
        if state.get("needs_retry"):
            return "orchestrator"  # loop back for re-routing
        return "__end__"

    # ── Specialist node factory ───────────────────────────────────────────────
    def make_specialist_node(agent_config: dict):
        async def specialist_node(state: WorkflowState) -> WorkflowState:
            name = agent_config["name"]
            tool_names = agent_config.get("tools", [])
            state["current_step"] = name

            forbidden = agent_config.get("forbidden_topics", [])
            if isinstance(forbidden, str):
                try:
                    forbidden = json.loads(forbidden)
                except json.JSONDecodeError:
                    forbidden = []
            max_chars = agent_config.get("max_output_chars")

            # Pass last specialist output on retries so the specialist knows
            # what was tried before and can produce a better response
            previous_attempt = state.get("last_specialist_output", "") if state.get("retry_count", 0) > 0 else ""

            response, tool_calls, usage = await run_agent_with_tools(
                system_prompt=agent_config["system_prompt"],
                user_message=state["user_input"],
                tool_names=tool_names,
                agent_name=name,
                forbidden_topics=forbidden,
                max_output_chars=max_chars,
                model=agent_config.get("model", ""),
                memory_context=state.get("memory_context", ""),
                previous_attempt=previous_attempt,
            )

            state["research_notes"] = response
            state["tool_calls"] = (state.get("tool_calls") or []) + tool_calls
            state["final_response"] = response
            existing = state.get("token_usage") or {}
            state["token_usage"] = _accumulate_usage(existing, usage)
            return state

        specialist_node.__name__ = agent_config["name"]
        return specialist_node

    # ── Assemble the graph ───────────────────────────────────────────────────
    graph = StateGraph(WorkflowState)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("__schedule_end__", schedule_end_node)
    graph.add_node("retry_check", retry_check_node)

    for agent in specialists:
        graph.add_node(agent["name"], make_specialist_node(agent))

    graph.add_edge(START, "orchestrator")

    routing_map = {a["name"]: a["name"] for a in specialists}
    routing_map["__schedule_end__"] = "__schedule_end__"
    graph.add_conditional_edges("orchestrator", route_from_orchestrator, routing_map)

    graph.add_edge("__schedule_end__", END)

    # All specialists feed into retry_check
    for agent in specialists:
        graph.add_edge(agent["name"], "retry_check")

    # retry_check either loops back to orchestrator or goes to END
    graph.add_conditional_edges(
        "retry_check",
        route_from_retry_check,
        {"orchestrator": "orchestrator", "__end__": END},
    )

    return graph.compile()
