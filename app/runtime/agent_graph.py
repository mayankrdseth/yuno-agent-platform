"""
Dynamic multi-agent LangGraph.

Routing modes
-------------
1. SINGLE   — orchestrator picks one specialist
2. FANOUT   — orchestrator picks multiple specialists (compound query)
             all run independently on user_input; responses merged
3. PIPELINE — orchestrator detects a research-then-summarise intent
             Researcher runs first on user_input, fills state["research_notes"]
             Summariser then runs on research_notes (not user_input)
             This demonstrates true inter-agent message passing
4. SCHEDULE — orchestrator detects cron intent; registers job and returns

Retry / Feedback Loop
---------------------
After each specialist (or after fanout/pipeline), retry_check_node evaluates
the output. Empty or guardrail-blocked responses trigger re-route to
orchestrator (up to MAX_RETRIES=2).

Orchestrator Tools
------------------
The orchestrator agent has access to `calculator` and `datetime` tools so it
can do precise UTC arithmetic for cron scheduling without relying on LLM
native arithmetic (which is unreliable for half-hour offsets like IST).

Scheduling — UTC only
---------------------
All cron expressions are stored and executed in UTC.
The orchestrator uses the `datetime` tool to get current UTC time and the
`calculator` tool to do offset arithmetic. The routing prompt instructs it
to always emit cron in UTC and show the original user time for verification.

Skills & Interaction Rules
--------------------------
Each specialist's skills are injected into the routing prompt for richer
routing signal. Interaction rules are appended to each agent's system prompt.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from typing import Any, Union

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.runtime.llm import get_llm
from app.runtime.state import TokenUsage, WorkflowState
from app.runtime.tools import format_tools_for_prompt, get_tools_for_agent

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
MAX_FANOUT = 3
_GUARDRAIL_PREFIX = "[Guardrail]"

_COST_PER_1K = {
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
    "llama-3.1-8b-instant":    (0.00005, 0.00008),
    "mixtral-8x7b-32768":      (0.00024, 0.00024),
    "gemma2-9b-it":            (0.00020, 0.00020),
    "llama-3.1-70b-specdec":   (0.00059, 0.00099),
}
_DEFAULT_COST = (0.00020, 0.00020)

# Matches a JSON object containing a "tool" key anywhere in the reply.
# This is intentionally non-greedy and single-level (no nested {}) so it
# won't accidentally match the routing JSON or other objects.
_TOOL_CALL_RE = re.compile(r'\{[^{}]*"tool"\s*:[^{}]*\}', re.DOTALL)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_usage_dict(obj):
    if obj is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if isinstance(obj, TokenUsage):
        return asdict(obj)
    return obj


def _extract_usage(response) -> dict:
    meta = getattr(response, "usage_metadata", None) or {}
    return {
        "prompt_tokens":     meta.get("input_tokens", 0),
        "completion_tokens": meta.get("output_tokens", 0),
        "total_tokens":      meta.get("total_tokens", 0),
    }


def _accumulate_usage(existing, new) -> TokenUsage:
    a = _to_usage_dict(existing)
    b = _to_usage_dict(new)
    return TokenUsage(
        prompt_tokens     = a.get("prompt_tokens", 0)     + b.get("prompt_tokens", 0),
        completion_tokens = a.get("completion_tokens", 0) + b.get("completion_tokens", 0),
        total_tokens      = a.get("total_tokens", 0)      + b.get("total_tokens", 0),
    )


def _estimate_cost(model: str, usage) -> float:
    d = _to_usage_dict(usage)
    in_cost, out_cost = _COST_PER_1K.get(model, _DEFAULT_COST)
    return (
        d.get("prompt_tokens", 0)     / 1000 * in_cost
        + d.get("completion_tokens", 0) / 1000 * out_cost
    )


def _apply_guardrails(text, forbidden_topics, max_output_chars, agent_name) -> str:
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
        text = text[:max_output_chars] + " … [truncated]"
    return text


def _format_memory_context(memory_turns: list[dict]) -> str:
    if not memory_turns:
        return ""
    lines = ["Conversation history (most recent last):"]
    for m in memory_turns:
        prefix = "User" if m["role"] == "human" else "Assistant"
        lines.append(f"  {prefix}: {m['content']}")
    return "\n".join(lines)


def _build_system_prompt_with_rules(system_prompt: str, interaction_rules: list[str]) -> str:
    if not interaction_rules:
        return system_prompt
    rules_block = "\n\nBehavioural rules you MUST follow on every response:\n" + "\n".join(
        f"  - {rule}" for rule in interaction_rules
    )
    return system_prompt + rules_block


def _extract_tool_call(reply: str, tools: dict) -> tuple[str, str] | None:
    """
    Search for a JSON tool-call object anywhere in `reply`.

    LLMs often prepend prose before the JSON, e.g.:
        "To calculate this I'll use the calculator tool. {"tool": "calculator", "input": "22*36"}"

    Using re.search (instead of startswith) handles this case correctly.
    Returns (tool_name, tool_input) if a valid, known tool call is found,
    otherwise None.
    """
    match = _TOOL_CALL_RE.search(reply)
    if not match:
        return None
    try:
        parsed = json.loads(match.group())
        tool_name = parsed.get("tool", "")
        tool_input = parsed.get("input", "")
        if tool_name and tool_name in tools:
            return tool_name, tool_input
    except (json.JSONDecodeError, KeyError):
        pass
    return None


# ── Core specialist runner ────────────────────────────────────────────────────

async def run_agent_with_tools(
    system_prompt: str,
    user_message: str,
    tool_names: list[str],
    agent_name: str,
    forbidden_topics: list | None = None,
    max_output_chars: int | None = None,
    model: str = "",
    memory_context: str = "",
    previous_attempt: str = "",
    interaction_rules: list | None = None,
) -> tuple[str, list[dict], TokenUsage]:
    llm = get_llm(model) if model else get_llm()
    tool_calls_log: list[dict] = []
    tools = get_tools_for_agent(tool_names)
    usage_acc: TokenUsage = TokenUsage()

    effective_system_prompt = _build_system_prompt_with_rules(
        system_prompt, interaction_rules or []
    )

    tool_section = ""
    if tools:
        tool_section = (
            "\n\nYou have access to these tools. "
            "To use a tool, respond ONLY with a JSON object like:\n"
            '{"tool": "<tool_name>", "input": "<input_string>"}\n'
            "Do NOT include any prose before or after the JSON — output the JSON object only.\n"
            f"Available tools:\n{format_tools_for_prompt(tool_names)}"
        )

    messages: list = [SystemMessage(content=effective_system_prompt + tool_section)]
    if memory_context:
        messages.append(SystemMessage(content=memory_context))
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

    # Use re.search-based extraction — handles prose before the JSON object
    if tools:
        tool_call = _extract_tool_call(reply, tools)
        if tool_call:
            tool_name, tool_input = tool_call
            logger.info("[%s] calling tool: %s(%s)", agent_name, tool_name, tool_input)
            tool_result = await tools[tool_name](tool_input)
            tool_calls_log.append({"tool": tool_name, "input": tool_input, "result": tool_result})
            followup = [
                SystemMessage(content=effective_system_prompt),
                HumanMessage(content=user_message),
                SystemMessage(content=f"Tool result from {tool_name}:\n{tool_result}\nNow provide your final answer."),
            ]
            final_response = await llm.ainvoke(followup)
            usage_acc = _accumulate_usage(usage_acc, _extract_usage(final_response))
            reply = final_response.content.strip()

    reply = _apply_guardrails(
        reply,
        forbidden_topics=forbidden_topics or [],
        max_output_chars=max_output_chars,
        agent_name=agent_name,
    )
    return reply, tool_calls_log, usage_acc


# ── Orchestrator LLM call ─────────────────────────────────────────────────────

async def llm_route_and_detect(
    user_input: str,
    orchestrator_system_prompt: str,
    orchestrator_tools: list[str],
    specialist_agents: list[dict],
    model: str = "",
    memory_turns: list[dict] | None = None,
    previous_routing: str = "",
    previous_output: str = "",
) -> tuple[dict[str, Any], TokenUsage]:
    """
    Orchestrator LLM call — detects schedule intent, routing mode
    (single / fanout / pipeline), and uses tools for UTC arithmetic.

    Pipeline mode is triggered when the orchestrator detects the query
    needs research FOLLOWED BY summarisation — it emits:
      {"routing_mode": "pipeline", "pipeline": ["Researcher", "Summariser"], ...}
    """
    llm = get_llm(model) if model else get_llm()
    tools = get_tools_for_agent(orchestrator_tools)
    usage_acc: TokenUsage = TokenUsage()

    agent_list_lines = []
    for a in specialist_agents:
        skills = a.get("skills") or []
        skills_str = f" | skills: {', '.join(skills)}" if skills else ""
        agent_list_lines.append(
            f"  - {a['name']}: {a['role']}{skills_str} — {a['system_prompt'][:120]}"
        )
    agent_list = "\n".join(agent_list_lines)

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
            "Please route to a DIFFERENT specialist or use a different approach.\n"
        )

    tool_section = ""
    if tools:
        tool_section = (
            "\n\nYou have access to tools for precise calculation. "
            "To use a tool, respond with ONLY a JSON object like:\n"
            '{"tool": "<tool_name>", "input": "<input>"}\n'
            "Do NOT include any prose before or after the JSON — output the JSON object only.\n"
            "Use the `datetime` tool to get current UTC time. "
            "Use the `calculator` tool for offset arithmetic.\n"
            f"Available tools:\n{format_tools_for_prompt(orchestrator_tools)}\n"
            "IMPORTANT: Only use tools when you need them (e.g. for cron scheduling). "
            "For routing decisions, respond directly with the routing JSON."
        )

    routing_prompt = (
        f"{orchestrator_system_prompt}\n"
        f"{history_section}"
        f"{retry_section}"
        f"{tool_section}\n\n"
        "You are the orchestrator. For the user request below, decide the routing mode:\n\n"
        "ROUTING MODES:\n"
        "A) SINGLE   — one specialist handles the whole query\n"
        "B) FANOUT   — multiple specialists each handle a different part independently\n"
        "C) PIPELINE — the query needs research FIRST, then the research output should be "
        "summarised/processed by a second agent. Use this when the user asks to "
        "'research AND summarise', 'find and brief me', 'look up and condense', etc. "
        "The first agent's output becomes the second agent's input.\n"
        "D) SCHEDULE — user wants to schedule a recurring task (cron)\n\n"
        "For SCHEDULE: cron MUST be in UTC. "
        "Use the `datetime` tool to get current time, then `calculator` for offset arithmetic. "
        "Steps: (1) get current UTC via datetime tool, (2) convert user time to total minutes "
        "from midnight, (3) subtract timezone offset in minutes, (4) emit cron.\n"
        "Example: '5:57 PM IST' → total minutes = 17*60+57=1077, IST offset=330min, "
        "1077-330=747min → 12h 27m UTC → cron: '27 12 * * *'\n\n"
        "Respond ONLY with a JSON object matching one of these shapes:\n\n"
        "SINGLE:   {\"routing_mode\": \"single\",    \"target\": \"<name>\", "
        "\"reason\": \"...\", \"schedule_intent\": null}\n"
        "FANOUT:   {\"routing_mode\": \"fanout\",    \"targets\": [\"<name1>\", \"<name2>\"], "
        "\"reason\": \"...\", \"schedule_intent\": null}\n"
        "PIPELINE: {\"routing_mode\": \"pipeline\",  \"pipeline\": [\"<first>\", \"<second>\"], "
        "\"reason\": \"...\", \"schedule_intent\": null}\n"
        "SCHEDULE: {\"routing_mode\": \"schedule\",  \"target\": \"<name>\", \"reason\": \"...\", "
        "\"schedule_intent\": {\"cron\": \"<UTC cron>\", \"prompt\": \"<task>\", "
        "\"original_time\": \"<what user said>\"}}\n\n"
        f"Available agents:\n{agent_list}\n\n"
        f"User request: {user_input}"
    )

    # Run orchestrator — may use tools for UTC arithmetic
    messages: list = [HumanMessage(content=routing_prompt)]
    response = await llm.ainvoke(messages)
    usage_acc = _accumulate_usage(usage_acc, _extract_usage(response))
    reply = response.content.strip()

    # Handle tool call from orchestrator — use re.search to find JSON anywhere in reply
    if tools:
        tool_call = _extract_tool_call(reply, tools)
        if tool_call:
            tool_name, tool_input = tool_call
            logger.info("[orchestrator] tool call: %s(%s)", tool_name, tool_input)
            tool_result = await tools[tool_name](tool_input)
            followup_prompt = (
                routing_prompt
                + f"\n\nTool result from {tool_name}: {tool_result}\n"
                "Now provide your final routing JSON."
            )
            followup_response = await llm.ainvoke([HumanMessage(content=followup_prompt)])
            usage_acc = _accumulate_usage(usage_acc, _extract_usage(followup_response))
            reply = followup_response.content.strip()

    # Parse routing JSON
    json_match = re.search(r'\{.*\}', reply, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            mode = data.get("routing_mode", "single")

            # Normalise all modes to have both target + targets for compat
            if mode == "pipeline":
                pipeline = data.get("pipeline", [])
                data["targets"]        = pipeline
                data["target"]         = pipeline[0] if pipeline else ""
                data["pipeline_queue"] = pipeline
            elif mode == "fanout":
                targets = data.get("targets", [])
                data["targets"]        = targets[:MAX_FANOUT]
                data["target"]         = targets[0] if targets else ""
                data["pipeline_queue"] = []
            else:  # single or schedule
                data["targets"]        = [data.get("target", "")]
                data["pipeline_queue"] = []

            data["memory_context"] = _format_memory_context(memory_turns or [])
            return data, usage_acc
        except json.JSONDecodeError:
            pass

    fallback = specialist_agents[0]["name"] if specialist_agents else "fallback"
    return {
        "routing_mode":  "single",
        "target":        fallback,
        "targets":       [fallback],
        "pipeline_queue": [],
        "reason":        "routing fallback",
        "schedule_intent": None,
        "memory_context":  "",
    }, usage_acc


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_agent_graph(
    orchestrator: dict,
    specialists: list[dict],
    memory_turns: list[dict] | None = None,
):
    if not specialists:
        raise ValueError("At least one specialist agent is required.")

    seen: set[str] = set()
    unique_specialists: list[dict] = []
    for s in specialists:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique_specialists.append(s)
    specialists = unique_specialists
    specialists = [s for s in specialists if s["name"] != orchestrator["name"]]
    specialist_map = {a["name"]: a for a in specialists}

    # Orchestrator tools (calculator + datetime for UTC arithmetic)
    orchestrator_tools: list[str] = []
    raw_tools = orchestrator.get("tools", [])
    if isinstance(raw_tools, str):
        try:
            orchestrator_tools = json.loads(raw_tools)
        except json.JSONDecodeError:
            orchestrator_tools = []
    elif isinstance(raw_tools, list):
        orchestrator_tools = raw_tools

    async def orchestrator_node(state: WorkflowState) -> WorkflowState:
        state["current_step"] = "orchestrator"
        state["status"] = "running"

        prev_routing = state.get("routing_decision", "") if state.get("retry_count", 0) > 0 else ""
        prev_output  = state.get("last_specialist_output", "") if state.get("retry_count", 0) > 0 else ""

        route, usage = await llm_route_and_detect(
            user_input=state["user_input"],
            orchestrator_system_prompt=orchestrator["system_prompt"],
            orchestrator_tools=orchestrator_tools,
            specialist_agents=specialists,
            model=orchestrator.get("model", ""),
            memory_turns=memory_turns or [],
            previous_routing=prev_routing,
            previous_output=prev_output,
        )

        mode     = route.get("routing_mode", "single")
        targets  = route.get("targets") or [route.get("target", specialists[0]["name"])]
        targets  = [t for t in targets if t in specialist_map]
        if not targets:
            targets = [specialists[0]["name"]]

        state["routing_decision"]  = targets[0]
        state["routing_targets"]   = targets
        state["routing_reason"]    = route.get("reason", "")
        state["schedule_intent"]   = route.get("schedule_intent")
        state["memory_context"]    = route.get("memory_context", "")
        state["token_usage"]       = _accumulate_usage(state.get("token_usage"), usage)
        state["needs_retry"]       = False
        state["pipeline_mode"]     = (mode == "pipeline")
        state["pipeline_stage"]    = "research" if mode == "pipeline" else ""
        state["pipeline_queue"]    = route.get("pipeline_queue", [])

        logger.info(
            "Orchestrator: mode=%s targets=%s schedule=%s retry=%d",
            mode, targets, state["schedule_intent"], state.get("retry_count", 0),
        )
        return state

    def route_from_orchestrator(state: WorkflowState) -> str:
        if state.get("schedule_intent"):
            return "__schedule_end__"
        if state.get("pipeline_mode"):
            queue = state.get("pipeline_queue") or []
            first = queue[0] if queue else ""
            return first if first in specialist_map else specialists[0]["name"]
        targets = state.get("routing_targets") or [state.get("routing_decision", "")]
        if len(targets) > 1:
            return "__fanout__"
        target = targets[0] if targets else ""
        return target if target in specialist_map else specialists[0]["name"]

    async def schedule_end_node(state: WorkflowState) -> WorkflowState:
        intent = state["schedule_intent"]
        original_time = intent.get("original_time", "")
        original_note = f" (converted from {original_time})" if original_time else ""
        state["final_response"] = (
            f"\u2705 Got it! I'll schedule this for you.\n"
            f"Cron: `{intent['cron']}` (UTC{original_note})\n"
            f"Task: {intent['prompt']}"
        )
        state["status"]       = "scheduled"
        state["current_step"] = "schedule_end"
        return state

    async def pipeline_handoff_node(state: WorkflowState) -> WorkflowState:
        """
        Between Researcher and Summariser in pipeline mode.
        Pops the first item from pipeline_queue (already ran),
        sets the next agent as target, and passes research_notes
        as the effective input for the next stage.
        """
        queue = list(state.get("pipeline_queue") or [])
        if queue:
            queue.pop(0)  # remove completed stage
        state["pipeline_queue"]  = queue
        state["pipeline_stage"]  = "summarise" if queue else "done"
        state["routing_targets"] = queue
        state["routing_decision"]= queue[0] if queue else ""
        logger.info("Pipeline handoff: next=%s research_notes_len=%d",
                    queue[0] if queue else "(done)", len(state.get("research_notes", "")))
        return state

    def route_from_pipeline_handoff(state: WorkflowState) -> str:
        queue = state.get("pipeline_queue") or []
        if queue and queue[0] in specialist_map:
            return queue[0]
        return "retry_check"

    async def fanout_node(state: WorkflowState) -> WorkflowState:
        targets         = state.get("routing_targets") or [state.get("routing_decision")]
        all_responses: list[str]   = []
        all_tool_calls: list[dict] = list(state.get("tool_calls") or [])
        acc_usage = _accumulate_usage(state.get("token_usage"), None)

        for target_name in targets:
            agent_config = specialist_map.get(target_name)
            if not agent_config:
                continue
            state["current_step"] = target_name

            forbidden = agent_config.get("forbidden_topics", [])
            if isinstance(forbidden, str):
                try: forbidden = json.loads(forbidden)
                except: forbidden = []

            interaction_rules = agent_config.get("interaction_rules", [])
            if isinstance(interaction_rules, str):
                try: interaction_rules = json.loads(interaction_rules)
                except: interaction_rules = []

            previous_attempt = state.get("last_specialist_output", "") if state.get("retry_count", 0) > 0 else ""

            response, tool_calls, usage = await run_agent_with_tools(
                system_prompt=agent_config["system_prompt"],
                user_message=state["user_input"],
                tool_names=agent_config.get("tools", []),
                agent_name=target_name,
                forbidden_topics=forbidden,
                max_output_chars=agent_config.get("max_output_chars"),
                model=agent_config.get("model", ""),
                memory_context=state.get("memory_context", ""),
                previous_attempt=previous_attempt,
                interaction_rules=interaction_rules,
            )
            all_responses.append(f"**{target_name}:**\n{response}")
            all_tool_calls.extend(tool_calls)
            acc_usage = _accumulate_usage(acc_usage, usage)

        merged = "\n\n".join(all_responses) if all_responses else ""
        state["final_response"] = merged
        state["research_notes"] = merged
        state["tool_calls"]     = all_tool_calls
        state["token_usage"]    = acc_usage
        return state

    def retry_check_node(state: WorkflowState) -> WorkflowState:
        response    = state.get("final_response", "").strip()
        retry_count = state.get("retry_count", 0)

        should_retry = (
            (not response or response.startswith(_GUARDRAIL_PREFIX))
            and retry_count < MAX_RETRIES
        )

        if should_retry:
            state["needs_retry"]            = True
            state["retry_count"]            = retry_count + 1
            state["last_specialist_output"] = response
            state["final_response"]         = ""
            state["pipeline_mode"]          = False  # abort pipeline on retry
            state["pipeline_queue"]         = []
        else:
            state["needs_retry"] = False
            if not response:
                state["final_response"] = "I was unable to produce a response for this request."
                state["status"]         = "failed"
            else:
                state["status"] = "completed"
        return state

    def route_from_retry_check(state: WorkflowState) -> str:
        return "orchestrator" if state.get("needs_retry") else "__end__"

    def make_specialist_node(agent_config: dict):
        name = agent_config["name"]

        async def specialist_node(state: WorkflowState) -> WorkflowState:
            state["current_step"] = name

            forbidden = agent_config.get("forbidden_topics", [])
            if isinstance(forbidden, str):
                try: forbidden = json.loads(forbidden)
                except: forbidden = []

            interaction_rules = agent_config.get("interaction_rules", [])
            if isinstance(interaction_rules, str):
                try: interaction_rules = json.loads(interaction_rules)
                except: interaction_rules = []

            previous_attempt = state.get("last_specialist_output", "") if state.get("retry_count", 0) > 0 else ""

            # PIPELINE: Summariser receives Researcher's output, not raw user_input
            if state.get("pipeline_stage") == "summarise" and state.get("research_notes"):
                effective_input = (
                    f"The following research was gathered on the topic: \"{state['user_input']}\"\n\n"
                    f"{state['research_notes']}\n\n"
                    "Please summarise this into a concise, well-structured brief."
                )
            else:
                effective_input = state["user_input"]

            response, tool_calls, usage = await run_agent_with_tools(
                system_prompt=agent_config["system_prompt"],
                user_message=effective_input,
                tool_names=agent_config.get("tools", []),
                agent_name=name,
                forbidden_topics=forbidden,
                max_output_chars=agent_config.get("max_output_chars"),
                model=agent_config.get("model", ""),
                memory_context=state.get("memory_context", ""),
                previous_attempt=previous_attempt,
                interaction_rules=interaction_rules,
            )

            # In pipeline research stage, store output in research_notes for handoff
            if state.get("pipeline_stage") == "research":
                state["research_notes"] = response
                state["final_response"] = ""  # don't surface intermediate research
            else:
                state["research_notes"] = response
                state["final_response"] = response

            state["tool_calls"]  = (state.get("tool_calls") or []) + tool_calls
            state["token_usage"] = _accumulate_usage(state.get("token_usage"), usage)
            return state

        specialist_node.__name__ = name
        return specialist_node

    # ── Build graph ────────────────────────────────────────────────────────────
    graph = StateGraph(WorkflowState)
    graph.add_node("orchestrator",         orchestrator_node)
    graph.add_node("__schedule_end__",     schedule_end_node)
    graph.add_node("__fanout__",           fanout_node)
    graph.add_node("__pipeline_handoff__", pipeline_handoff_node)
    graph.add_node("retry_check",          retry_check_node)

    for agent in specialists:
        graph.add_node(agent["name"], make_specialist_node(agent))

    graph.add_edge(START, "orchestrator")

    # Orchestrator → one of: schedule_end, fanout, pipeline_first, single_specialist
    routing_map = {a["name"]: a["name"] for a in specialists}
    routing_map["__schedule_end__"] = "__schedule_end__"
    routing_map["__fanout__"]       = "__fanout__"
    graph.add_conditional_edges("orchestrator", route_from_orchestrator, routing_map)

    graph.add_edge("__schedule_end__", END)
    graph.add_edge("__fanout__",       "retry_check")

    # Specialist → pipeline_handoff OR retry_check
    for agent in specialists:
        graph.add_conditional_edges(
            agent["name"],
            lambda state, _name=agent["name"]: (
                "__pipeline_handoff__"
                if state.get("pipeline_mode") and state.get("pipeline_stage") == "research"
                else "retry_check"
            ),
            {"__pipeline_handoff__": "__pipeline_handoff__", "retry_check": "retry_check"},
        )

    # Pipeline handoff → next specialist OR retry_check
    pipeline_map = {a["name"]: a["name"] for a in specialists}
    pipeline_map["retry_check"] = "retry_check"
    graph.add_conditional_edges("__pipeline_handoff__", route_from_pipeline_handoff, pipeline_map)

    graph.add_conditional_edges(
        "retry_check",
        route_from_retry_check,
        {"orchestrator": "orchestrator", "__end__": END},
    )

    return graph.compile()
