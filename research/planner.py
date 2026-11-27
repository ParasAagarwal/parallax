"""Planner agent: turns a research question into a small set of web searches (structured output)."""

from datetime import date

from pydantic import BaseModel, Field
from agents import Agent

from config import HOW_MANY_SEARCHES, model


class SearchItem(BaseModel):
    reason: str = Field(description="One short sentence: why this search helps answer the question.")
    query: str = Field(description="The web search term to use. Concise, like something typed into a search engine.")


class SearchPlan(BaseModel):
    searches: list[SearchItem] = Field(description="The web searches to perform.")


def instructions(context, agent) -> str:
    """Called by the SDK at the start of every run, so the date is always today's
    (the model itself has no idea what today is - it would guess its training year)."""
    today = date.today()
    return f"""
You are the planning step of a research assistant.
Given a research question, plan exactly {HOW_MANY_SEARCHES} web searches that together best answer it.

Today's date is {today:%d %B %Y}. The current year is {today.year}.

Guidelines:
- Visitors want the most recent information. Unless the question names a specific past period,
  aim every search at the latest information: add "{today.year}" (or "latest") to the search terms.
- Never put an earlier year into a search term unless the question explicitly asks about that year.
- For "upcoming" or "future" questions, look forward from today, not from the past.
- Each search should cover a different angle (for example: overview, latest developments, comparisons or data).
- If the question is vague, choose the most sensible interpretation.
- Keep each reason to one short sentence. Visitors can see your plan.
"""


planner_agent = Agent(
    name="Planner",
    instructions=instructions,
    model=model,
    output_type=SearchPlan,
)
