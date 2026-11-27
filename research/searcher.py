"""
Search agent: runs one web search with a Tavily tool and summarises the results.

The tool also records every source it finds into a shared "context" object,
so the app can show visitors which websites were used - without asking the LLM.
"""

from dataclasses import dataclass, field

import httpx
from agents import Agent, ModelSettings, RunContextWrapper, function_tool

from config import MAX_CHARS_PER_RESULT, RESULTS_PER_SEARCH, TAVILY_API_KEY, model

TAVILY_URL = "https://api.tavily.com/search"


@dataclass
class SearchContext:
    """Filled in by the web_search tool during one search agent run."""
    sources: list[dict] = field(default_factory=list)
    failed: bool = False


@function_tool
async def web_search(ctx: RunContextWrapper[SearchContext], query: str) -> str:
    """
    Search the web and return the top results with their page content.

    Args:
        query: The search term to look up
    """
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(
                TAVILY_URL,
                headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
                json={"query": query, "max_results": RESULTS_PER_SEARCH, "search_depth": "basic"},
            )
    except httpx.HTTPError as error:
        print(f"[parallax] Tavily network error: {error}", flush=True)
        ctx.context.failed = True
        return "The web search failed because of a network problem. No results are available."

    if response.status_code != 200:
        print(f"[parallax] Tavily error {response.status_code}: {response.text[:300]}", flush=True)
        ctx.context.failed = True
        return "The web search service returned an error. No results are available."

    results = response.json().get("results", [])
    if not results:
        return "The search returned no results."

    blocks = []
    for result in results:
        url = result.get("url", "")
        title = result.get("title") or url
        ctx.context.sources.append({"title": title, "url": url})
        content = (result.get("content") or "")[:MAX_CHARS_PER_RESULT]
        blocks.append(f"Title: {title}\nURL: {url}\nContent: {content}")
    return "\n\n".join(blocks)


INSTRUCTIONS = """
You are the search step of a research assistant.
You are given a search term and the reason for the search. Use your web_search tool once,
then write a factual summary of what the results say that is relevant to the reason.

Rules:
- 2 to 3 short paragraphs, under 250 words.
- Only use information from the search results. Never add facts from memory.
- Keep important specifics: names, numbers, dates.
- If the search failed or found nothing useful, reply with exactly: NO_RESULTS
- Reply with the summary only, no preamble.
"""

search_agent = Agent(
    name="Searcher",
    instructions=INSTRUCTIONS,
    tools=[web_search],
    model=model,
    # Force a tool call first. The SDK then resets this to "auto" so the agent can write its summary.
    model_settings=ModelSettings(tool_choice="required"),
)
