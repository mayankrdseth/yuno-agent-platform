"""
Tool registry for agent runtime.
Each tool is a plain async callable that takes a string input and returns a string output.
Tools are loaded per-agent based on the agent's tools JSON field.
"""
import asyncio
import datetime as dt
import json
import math
import urllib.parse
import urllib.request


# ---------------------------------------------------------------------------
# Individual tool implementations
# ---------------------------------------------------------------------------

async def tool_datetime(_input: str) -> str:
    """Return the current date and time."""
    now = dt.datetime.now()
    return f"Current date and time: {now.strftime('%A, %d %B %Y, %I:%M %p')}"


async def tool_calculator(expression: str) -> str:
    """Safely evaluate a mathematical expression."""
    try:
        # Restrict to safe math operations only
        allowed_names = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
        allowed_names["abs"] = abs
        allowed_names["round"] = round
        result = eval(expression.strip(), {"__builtins__": {}}, allowed_names)  # noqa: S307
        return f"Result: {result}"
    except Exception as e:
        return f"Calculator error: {e}"


async def tool_web_search(query: str) -> str:
    """Search the web using DuckDuckGo Instant Answer API (no API key required)."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&skip_disambig=1"

        def _fetch():
            with urllib.request.urlopen(url, timeout=8) as resp:  # noqa: S310
                return resp.read().decode("utf-8")

        raw = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        data = json.loads(raw)

        # Try AbstractText first, then RelatedTopics
        answer = data.get("AbstractText", "").strip()
        if not answer:
            topics = data.get("RelatedTopics", [])
            snippets = []
            for t in topics[:3]:
                if isinstance(t, dict) and t.get("Text"):
                    snippets.append(t["Text"])
            answer = " | ".join(snippets) if snippets else ""

        if not answer:
            return f"No direct result found for: {query}. Try rephrasing."

        source = data.get("AbstractURL", "")
        return f"{answer}\nSource: {source}" if source else answer

    except Exception as e:
        return f"Web search error: {e}"


async def tool_wikipedia(topic: str) -> str:
    """Fetch a short Wikipedia summary for a topic."""
    try:
        encoded = urllib.parse.quote_plus(topic.strip())
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"

        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "yuno-agent/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
                return resp.read().decode("utf-8")

        raw = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        data = json.loads(raw)
        extract = data.get("extract", "").strip()
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

        if not extract:
            return f"No Wikipedia article found for: {topic}"

        # Limit to ~400 chars to keep context concise
        short = extract[:400] + ("..." if len(extract) > 400 else "")
        return f"{short}\nSource: {page_url}" if page_url else short

    except Exception as e:
        return f"Wikipedia error: {e}"


# ---------------------------------------------------------------------------
# Registry mapping tool name → callable
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, callable] = {
    "datetime": tool_datetime,
    "calculator": tool_calculator,
    "web_search": tool_web_search,
    "wikipedia": tool_wikipedia,
}

AVAILABLE_TOOLS = list(TOOL_REGISTRY.keys())


def get_tools_for_agent(tool_names: list[str]) -> dict[str, callable]:
    """Return only the tools that exist in the registry and are requested by the agent."""
    return {name: TOOL_REGISTRY[name] for name in tool_names if name in TOOL_REGISTRY}


def format_tools_for_prompt(tool_names: list[str]) -> str:
    """Return a human-readable list of available tools for injection into a system prompt."""
    if not tool_names:
        return "No tools available."
    lines = []
    descriptions = {
        "datetime": "datetime() — returns current date and time",
        "calculator": "calculator(expression) — evaluates a math expression",
        "web_search": "web_search(query) — searches the web using DuckDuckGo",
        "wikipedia": "wikipedia(topic) — fetches a Wikipedia summary for a topic",
    }
    for name in tool_names:
        if name in descriptions:
            lines.append(f"  - {descriptions[name]}")
    return "\n".join(lines)
