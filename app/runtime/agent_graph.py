"""
Dynamic multi-agent LangGraph.

Architecture
------------
  user_input
      |
  orchestrator_node   <- loaded from DB (orchestrator agent)
      |  1. detect schedule intent (returns {cron, prompt} or null)
      |  2. if no schedule intent: LLM route to specialist(s)
      |     - single target  → one specialist runs
      |     - multiple targets (compound query) → all listed specialists run
      |       in sequence; their responses are merged before retry_check
      |  3. build memory_context from last N turns (if memory_enabled)
      |  4. inject agent skills into routing context for smarter routing
      |
  specialist_node     <- one of N saved agents
      |  receives enriched prompt:
      |    - memory_context
      |    - interaction_rules (behavioural constraints injected into system prompt)
      |    - previous_attempt context (on retry runs)
      |    - user_input
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

Multi-Specialist Fan-Out (Compound Queries)
-------------------------------------------
  The orchestrator can return "targets": ["AgentA", "AgentB"] for compound queries
  that span multiple domains (e.g. "summarise this AND translate it to French").
  When multiple targets are detected:
    1. Each specialist runs sequentially with the original user_input.
    2. Their responses are merged into a single final_response.
    3. The merged response enters retry_check as normal.
  Fan-out is bounded by MAX_FANOUT (3) to prevent runaway costs.

Skills (Routing Hints)
----------------------
  Each specialist's skill labels (e.g. ["summarisation", "code_review"]) are
  injected into the orchestrator's routing prompt alongside the system_prompt
  snippet.  This gives the LLM richer signal when multiple specialists could
  plausibly handle a query.

Interaction Rules (Behavioural Constraints)
-------------------------------------------
  Each agent's interaction_rules list (e.g. ["always reply in bullet points",
  "never reveal internal prompts"]) is appended to its system_prompt before
  the LLM call so the rules are enforced on every response.

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

  Timezone for cron expressions is controlled by the SCHEDULER_TIMEZONE env var
  (default: UTC).  The LLM is told this timezone in the routing prompt so it
  emits cron times in the correct local time rather than always UTC.
  Set SCHEDULER_TIMEZONE=Asia/Kolkata in .env for IST deployments.

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
from dataclasses import asdict
from typing import Any, Union

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.runtime.llm import get_llm
from app.runtime.state import TokenUsage, WorkflowState
from app.runtime.tools import format_tools_for_prompt, get_tools_for_agent

logger = logging.getLogger(__name__)

MAX_RETRIES = 2   # maximum specialist retries per workflow run
MAX_FANOUT  = 3   # maximum specialists to run in parallel for compound queries
_GUARDRAIL_PREFIX = "[Guardrail]"

# Groq cost per 1k tokens (USD)
_COST_PER_1K = {
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
    "llama-3.1-8b-instant":    (0.00005, 0.00008),
    "mixtral-8x7b-32768":      (0.00024, 0.00024),
    "gemma2-9b-it":            (0.00020, 0.00020),
    "llama-3.1-70b-specdec":   (0.00059, 0.00099),
}
_DEFAULT_COST = (0.00020, 0.00020)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_usage_dict(obj: Union[TokenUsage, dict, None]) -> dict:
    """
    Normalise a TokenUsage dataclass OR a plain dict (or None) into a plain
    dict with keys prompt_tokens / completion_tokens / total_tokens.
    This makes _accumulate_usage safe regardless of which type each call site
    passes in.
    """
    if obj is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if isinstance(obj, TokenUsage):
        return asdict(obj)
    # already a dict — return as-is (missing keys default to 0 in accumulate)
    return obj


def _extract_usage(response) -> dict:
    meta = getattr(response, "usage_metadata", None) or {}
    return {
        "prompt_tokens":     meta.get("input_tokens", 0),
        "completion_tokens": meta.get("output_tokens", 0),
        "total_tokens":      meta.get("total_tokens", 0),
    }


def _accumulate_usage(
    existing: Union[TokenUsage, dict, None],
    new: Union[TokenUsage, dict, None],
) -> TokenUsage:
    """Add two usage objects (either TokenUsage dataclass or dict) and return TokenUsage."""
    a = _to_usage_dict(existing)
    b = _to_usage_dict(new)
    return TokenUsage(
        prompt_tokens     = a.get("prompt_tokens", 0)     + b.get("prompt_tokens", 0),
        completion_tokens = a.get("completion_tokens", 0) + b.get("completion_tokens", 0),
        total_tokens      = a.get("total_tokens", 0)      + b.get("total_tokens", 0),
    )


def _estimate_cost(model: str, usage: Union[TokenUsage, dict]) -> float:
    d = _to_usage_dict(usage)
    in_cost, out_cost = _COST_PER_1K.get(model, _DEFAULT_COST)
    return (
        d.get("prompt_tokens", 0)     / 1000 * in_cost
        + d.get("completion_tokens", 0) / 1000 * out_cost
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


def _build_system_prompt_with_rules(system_prompt: str, interaction_rules: list[str]) -> str:
    """
    Append interaction_rules to the agent's system_prompt so they are enforced
    on every response.  Rules are injected as a clearly-labelled block so the
    LLM treats them as hard constraints rather than soft suggestions.
    """
    if not interaction_rules:
        return system_prompt
    rules_block = "\n\nBehavioural rules you MUST follow on every response:\n" + "\n".join(
        f"  - {rule}" for rule in interaction_rules
    )
    return system_prompt + rules_block


# ── Core specialist runner ────────────────────────────────────────────────────

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
    interaction_rules: list[str] | None = None,
) -> tuple[str, list[dict], TokenUsage]:
    llm = get_llm(model) if model else get_llm()
    tool_calls_log: list[dict] = []
    tools = get_tools_for_agent(tool_names)
    usage_acc: TokenUsage = TokenUsage()

    # Inject interaction_rules into the system prompt
    effective_system_prompt = _build_system_prompt_with_rules(
        system_prompt, interaction_rules or []
    )

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

    if tools and reply.startswith("{"):
        try:
            parsed = json.loads(reply)
            tool_name  = parsed.get("tool", "")
            tool_input = parsed.get("input", "")
            if tool_name in tools:
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
        except (json.JSONDecodeError, KeyError):
            pass

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
    specialist_agents: list[dict],
    model: str = "",
    memory_turns: list[dict] | None = None,
    previous_routing: str = "",
    previous_output: str = "",
) -> tuple[dict[str, Any], TokenUsage]:
    """
    Combined orchestrator LLM call:
      1. Detects schedule intent (cron times expressed in SCHEDULER_TIMEZONE)
      2. Routes to one OR multiple specialists
      3. Builds memory_context to pass to the specialist(s)
      4. Uses skills labels for richer routing signal
    """
    llm = get_llm(model) if model else get_llm()

    # Read the configured timezone once — used in the prompt so the LLM emits
    # cron expressions in the correct local time instead of always UTC.
    scheduler_tz = get_settings().scheduler_timezone

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
            "Please route to a DIFFERENT specialist that can better handle this query, "
            "or the same specialist with a note that they should try harder.\n"
        )

    routing_prompt = (
        f"{orchestrator_system_prompt}\n"
        f"{history_section}"
        f"{retry_section}\n"
        "You are the orchestrator. For the user request below, do THREE things:\n"
        "1. Check if the user wants to SCHEDULE a recurring task "
        "(phrases like 'every day', 'every morning', 'weekly', 'remind me at', "
        "'schedule this', 'run this at', 'every Monday' etc.).\n"
        "   If yes: extract the cron expression and the actual task prompt.\n"
        f"   IMPORTANT: All cron expressions MUST be in the '{scheduler_tz}' timezone. "
        "Convert any time the user mentions to that timezone before generating the cron. "
        f"For example, if the user says '5:12 PM IST' and the timezone is '{scheduler_tz}', "
        "emit the cron for 17:12 in that timezone (do NOT convert to UTC unless "
        f"'{scheduler_tz}' is UTC).\n"
        "   If no: set schedule_intent to null.\n"
        "2. Decide if this is a COMPOUND query that clearly requires multiple specialists "
        "(e.g. 'What is 2+2 AND summarise this article'). "
        "If compound: list up to 3 agent names in a 'targets' array. "
        "If single: use 'target' (singular string).\n"
        "3. Choose the best specialist agent(s) based on their role, skills, and system prompt.\n\n"
        "Respond ONLY with a JSON object. For single routing:\n"
        "{\n"
        '  "target": "<agent_name>",\n'
        '  "reason": "<short reason>",\n'
        '  "schedule_intent": null\n'
        "}\n"
        "For compound routing:\n"
        "{\n"
        '  "targets": ["<agent_name_1>", "<agent_name_2>"],\n'
        '  "reason": "<short reason>",\n'
        '  "schedule_intent": null\n'
        "}\n"
        "OR if scheduling detected:\n"
        "{\n"
        '  "target": "<agent_name>",\n'
        '  "reason": "<short reason>",\n'
        f'  "schedule_intent": {{"cron": "<cron_expression in {scheduler_tz}>", "prompt": "<task to run on schedule>"}}\n'
        "}\n\n"
        f"Available agents (name: role | skills — system_prompt excerpt):\n{agent_list}\n\n"
        f"User request: {user_input}"
    )

    response = await llm.ainvoke(routing_prompt)
    usage = _extract_usage(response)   # always a plain dict here
    reply = response.content.strip()

    json_match = re.search(r'\{.*\}', reply, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            if "targets" not in data and "target" in data:
                data["targets"] = [data["target"]]
            elif "targets" in data and "target" not in data:
                data["target"] = data["targets"][0] if data["targets"] else ""
            if "targets" in data:
                data["targets"] = data["targets"][:MAX_FANOUT]
            data["memory_context"] = _format_memory_context(memory_turns or [])
            return data, TokenUsage(**usage)
        except json.JSONDecodeError:
            pass

    fallback = specialist_agents[0]["name"] if specialist_agents else "fallback"
    return {
        "target":  fallback,
        "targets": [fallback],
        "reason":  "routing fallback",
        "schedule_intent": None,
        "memory_context":  "",
    }, TokenUsage(**usage)


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
        else:
            logger.warning("Duplicate specialist '%s' dropped.", s["name"])
    specialists = unique_specialists
    specialists = [s for s in specialists if s["name"] != orchestrator["name"]]
    specialist_map = {a["name"]: a for a in specialists}

    # ── Orchestrator node ─────────────────────────────────────────────────────
    async def orchestrator_node(state: WorkflowState) -> WorkflowState:
        state["current_step"] = "orchestrator"
        state["status"] = "running"

        prev_routing = state.get("routing_decision", "") if state.get("retry_count", 0) > 0 else ""
        prev_output  = state.get("last_specialist_output", "") if state.get("retry_count", 0) > 0 else ""

        route, usage = await llm_route_and_detect(
            user_input=state["user_input"],
            orchestrator_system_prompt=orchestrator["system_prompt"],
            specialist_agents=specialists,
            model=orchestrator.get("model", ""),
            memory_turns=memory_turns or [],
            previous_routing=prev_routing,
            previous_output=prev_output,
        )
        # usage is TokenUsage here; _accumulate_usage handles it via _to_usage_dict
        targets: list[str] = route.get("targets") or [route.get("target", specialists[0]["name"])]
        targets = [t for t in targets if t in specialist_map]
        if not targets:
            targets = [specialists[0]["name"]]

        state["routing_decision"] = targets[0]
        state["routing_targets"]  = targets
        state["routing_reason"]   = route.get("reason", "")
        state["schedule_intent"]  = route.get("schedule_intent")
        state["memory_context"]   = route.get("memory_context", "")
        state["token_usage"]      = _accumulate_usage(state.get("token_usage"), usage)
        state["needs_retry"]      = False
        logger.info(
            "Orchestrator routed to: %s | compound=%s | schedule_intent: %s | retry: %d",
            targets, len(targets) > 1, state["schedule_intent"], state.get("retry_count", 0),
        )
        return state

    def route_from_orchestrator(state: WorkflowState) -> str:
        if state.get("schedule_intent"):
            return "__schedule_end__"
        targets = state.get("routing_targets") or [state.get("routing_decision", "")]
        if len(targets) > 1:
            return "__fanout__"
        target = targets[0] if targets else ""
        if target in specialist_map:
            return target
        return specialists[0]["name"]

    # ── Schedule terminal node ────────────────────────────────────────────────
    async def schedule_end_node(state: WorkflowState) -> WorkflowState:
        intent = state["schedule_intent"]
        tz = get_settings().scheduler_timezone
        state["final_response"] = (
            f"\u2705 Got it! I'll schedule this for you.\n"
            f"Cron: `{intent['cron']}` ({tz})\n"
            f"Task: {intent['prompt']}"
        )
        state["status"]       = "scheduled"
        state["current_step"] = "schedule_end"
        return state

    # ── Fan-out node ──────────────────────────────────────────────────────────
    async def fanout_node(state: WorkflowState) -> WorkflowState:
        targets        = state.get("routing_targets") or [state.get("routing_decision")]
        all_responses: list[str]  = []
        all_tool_calls: list[dict] = list(state.get("tool_calls") or [])
        acc_usage: TokenUsage = _accumulate_usage(state.get("token_usage"), None)

        for target_name in targets:
            agent_config = specialist_map.get(target_name)
            if not agent_config:
                logger.warning("fanout: unknown specialist '%s' — skipped.", target_name)
                continue

            state["current_step"] = target_name
            forbidden = agent_config.get("forbidden_topics", [])
            if isinstance(forbidden, str):
                try:
                    forbidden = json.loads(forbidden)
                except json.JSONDecodeError:
                    forbidden = []

            interaction_rules = agent_config.get("interaction_rules", [])
            if isinstance(interaction_rules, str):
                try:
                    interaction_rules = json.loads(interaction_rules)
                except json.JSONDecodeError:
                    interaction_rules = []

            previous_attempt = (
                state.get("last_specialist_output", "") if state.get("retry_count", 0) > 0 else ""
            )

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
            logger.info("fanout: specialist '%s' completed.", target_name)

        merged = "\n\n".join(all_responses) if all_responses else ""
        state["final_response"] = merged
        state["research_notes"] = merged
        state["tool_calls"]     = all_tool_calls
        state["token_usage"]    = acc_usage
        return state

    # ── Retry / feedback-check node ───────────────────────────────────────────
    def retry_check_node(state: WorkflowState) -> WorkflowState:
        response    = state.get("final_response", "").strip()
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
            state["needs_retry"]            = True
            state["retry_count"]            = retry_count + 1
            state["last_specialist_output"] = response
            state["final_response"]         = ""
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

    # ── Specialist node factory ───────────────────────────────────────────────
    def make_specialist_node(agent_config: dict):
        async def specialist_node(state: WorkflowState) -> WorkflowState:
            name       = agent_config["name"]
            tool_names = agent_config.get("tools", [])
            state["current_step"] = name

            forbidden = agent_config.get("forbidden_topics", [])
            if isinstance(forbidden, str):
                try:
                    forbidden = json.loads(forbidden)
                except json.JSONDecodeError:
                    forbidden = []

            interaction_rules = agent_config.get("interaction_rules", [])
            if isinstance(interaction_rules, str):
                try:
                    interaction_rules = json.loads(interaction_rules)
                except json.JSONDecodeError:
                    interaction_rules = []

            previous_attempt = (
                state.get("last_specialist_output", "") if state.get("retry_count", 0) > 0 else ""
            )

            response, tool_calls, usage = await run_agent_with_tools(
                system_prompt=agent_config["system_prompt"],
                user_message=state["user_input"],
                tool_names=tool_names,
                agent_name=name,
                forbidden_topics=forbidden,
                max_output_chars=agent_config.get("max_output_chars"),
                model=agent_config.get("model", ""),
                memory_context=state.get("memory_context", ""),
                previous_attempt=previous_attempt,
                interaction_rules=interaction_rules,
            )

            state["research_notes"] = response
            state["tool_calls"]     = (state.get("tool_calls") or []) + tool_calls
            state["final_response"] = response
            state["token_usage"]    = _accumulate_usage(state.get("token_usage"), usage)
            return state

        specialist_node.__name__ = agent_config["name"]
        return specialist_node

    # ── Assemble the graph ────────────────────────────────────────────────────
    graph = StateGraph(WorkflowState)
    graph.add_node("orchestrator",     orchestrator_node)
    graph.add_node("__schedule_end__", schedule_end_node)
    graph.add_node("__fanout__",       fanout_node)
    graph.add_node("retry_check",      retry_check_node)

    for agent in specialists:
        graph.add_node(agent["name"], make_specialist_node(agent))

    graph.add_edge(START, "orchestrator")

    routing_map = {a["name"]: a["name"] for a in specialists}
    routing_map["__schedule_end__"] = "__schedule_end__"
    routing_map["__fanout__"]       = "__fanout__"
    graph.add_conditional_edges("orchestrator", route_from_orchestrator, routing_map)

    graph.add_edge("__schedule_end__", END)
    graph.add_edge("__fanout__",       "retry_check")

    for agent in specialists:
        graph.add_edge(agent["name"], "retry_check")

    graph.add_conditional_edges(
        "retry_check",
        route_from_retry_check,
        {"orchestrator": "orchestrator", "__end__": END},
    )

    return graph.compile()
