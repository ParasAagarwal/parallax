"""
Research manager: code-driven orchestration of the research pipeline.

    question -> Planner -> N parallel Searchers -> Writer -> report

Python (not an LLM) decides the order. Every step is recorded as a `Step`,
and after each change we `yield` so the page can show live progress - a
visitor-friendly version of a trace.

Slow calls run as background tasks. While we wait for them we still yield
every second (a "heartbeat"), so the timers on the page keep ticking and the
visitor can see Parallax is working, even when the free model is slow.
"""

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from agents import Runner
from openai.types.responses import ResponseTextDeltaEvent

from config import HOW_MANY_SEARCHES, friendly_error, short_error
from research.planner import planner_agent
from research.searcher import SearchContext, search_agent
from research.writer import writer_agent

TICK_SECONDS = 1.0      # how often the page refreshes while we wait (keeps the timers moving)
STREAM_SECONDS = 0.25   # how often the report refreshes while it is being written


@dataclass
class Step:
    """One line in the activity panel."""
    title: str
    status: str = "running"                          # running | done | failed
    details: list[str] = field(default_factory=list)  # extra lines shown under the title
    links: list[dict] = field(default_factory=list)   # sources: {"title", "url"}
    started: float = field(default_factory=time.monotonic)
    ended: float | None = None

    def finish(self, status: str = "done", details: list[str] | None = None, links: list[dict] | None = None):
        self.status = status
        self.ended = time.monotonic()
        if details:
            self.details = details
        if links:
            self.links = links

    @property
    def seconds(self) -> float:
        return (self.ended or time.monotonic()) - self.started


def domain(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.") or url


def clean_markdown(text: str) -> str:
    """Remove a ```markdown fence if the model wrapped the whole report in one."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


class ResearchManager:

    def __init__(self):
        self.steps: list[Step] = []
        self.report = ""
        self.complete = False   # True only when the whole pipeline succeeded (the page then collapses the trace)

    def add_step(self, title: str) -> Step:
        step = Step(title)
        self.steps.append(step)
        return step

    async def _wait_for(self, task: asyncio.Task, every: float = TICK_SECONDS):
        """Heartbeat: wait for a background task, yielding every `every` seconds so the page keeps
        updating (running timers tick, streamed text appears). If the visitor leaves, cancel the task."""
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=every)
                yield self.steps, clean_markdown(self.report)
        finally:
            if not task.done():
                task.cancel()

    async def run(self, question: str):
        """Run the pipeline, yielding (steps, report_markdown) after every change."""
        started = time.monotonic()

        # ---------- 1. Plan ----------
        plan_step = self.add_step("Planning the research")
        yield self.steps, ""
        try:
            plan_task = asyncio.create_task(
                Runner.run(planner_agent, f"Research question: {question}", max_turns=2))
            async for update in self._wait_for(plan_task):
                yield update
            result = plan_task.result()          # the plan, or re-raises the planner's error
            searches = result.final_output.searches[:HOW_MANY_SEARCHES]
            if not searches:
                raise ValueError("The planner returned no searches")
        except Exception as error:
            plan_step.finish("failed", ["Couldn't create a research plan"])
            yield self.steps, friendly_error(error)
            return
        plan_step.finish("done", [f"**{item.query}** · {item.reason}" for item in searches])
        yield self.steps, ""

        # ---------- 2. Search (in parallel) ----------
        search_steps = [self.add_step(f"Searching: {item.query}") for item in searches]
        yield self.steps, ""

        async def run_one_search(index, item):
            context = SearchContext()
            try:
                message = f"Search term: {item.query}\nReason for searching: {item.reason}"
                result = await Runner.run(search_agent, message, context=context, max_turns=4)
                return index, str(result.final_output or ""), context, None
            except Exception as error:
                return index, "", context, error

        summaries: list[tuple[str, str]] = []
        all_sources: list[dict] = []
        last_error = None

        # All searches start at once. Every second (or as soon as one finishes) we update the page,
        # so finished searches appear immediately and running timers keep ticking.
        pending = {asyncio.create_task(run_one_search(i, item)) for i, item in enumerate(searches)}
        try:
            while pending:
                finished, pending = await asyncio.wait(
                    pending, timeout=TICK_SECONDS, return_when=asyncio.FIRST_COMPLETED)
                for task in finished:
                    index, summary, context, error = task.result()
                    step = search_steps[index]
                    if error:
                        last_error = error
                        step.finish("failed", [short_error(error)])
                    elif context.failed or not summary.strip() or "NO_RESULTS" in summary:
                        step.finish("failed", ["No useful results found"])
                    else:
                        summaries.append((searches[index].query, summary))
                        all_sources.extend(context.sources)
                        step.finish("done", [f"Read {len(context.sources)} sources"], context.sources)
                yield self.steps, ""
        finally:
            for task in pending:                 # only non-empty if the visitor left mid-search
                task.cancel()

        if not summaries:
            message = friendly_error(last_error) if last_error else (
                "🔍 **No useful information was found** for this question. Try rephrasing it or making it more specific.")
            yield self.steps, message
            return

        # ---------- 3. Write (streamed) ----------
        write_step = self.add_step("Writing the report")
        yield self.steps, ""

        research_notes = "\n\n".join(f"### Search: {query}\n{summary}" for query, summary in summaries)
        writer_input = f"Research question: {question}\n\nSearch summaries:\n\n{research_notes}"

        async def write():
            """Background task: collect the streamed report into self.report, word by word."""
            streamed = Runner.run_streamed(writer_agent, writer_input, max_turns=2)
            try:
                async for event in streamed.stream_events():
                    if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                        self.report += event.data.delta
            except asyncio.CancelledError:
                streamed.cancel()                # visitor left: stop the model too
                raise

        try:
            write_task = asyncio.create_task(write())
            # The heartbeat shows the growing report 4 times a second, and keeps the timer
            # ticking even before the first words arrive.
            async for update in self._wait_for(write_task, every=STREAM_SECONDS):
                yield update
            write_task.result()                  # re-raises the writer's error, if any
        except Exception as error:
            write_step.finish("failed", ["The report couldn't be finished"])
            partial = clean_markdown(self.report)
            yield self.steps, (partial + "\n\n---\n\n" if partial else "") + friendly_error(error)
            return

        self.report = clean_markdown(self.report)
        if not self.report:
            write_step.finish("failed", ["The model returned an empty report"])
            yield self.steps, "🤔 **The model returned an empty report.** Please try again."
            return
        write_step.finish("done", [f"{len(self.report.split())} words"])

        # ---------- 4. Add sources (by code, so they are always real) ----------
        unique = list({source["url"]: source for source in all_sources if source.get("url")}.values())
        if unique:
            lines = [f"{n}. [{source['title']}]({source['url']}) · *{domain(source['url'])}*"
                     for n, source in enumerate(unique, start=1)]
            self.report += "\n\n---\n\n## Sources\n\n" + "\n".join(lines)

        done = self.add_step("Research complete")
        done.started = started
        done.finish("done", [f"{len(summaries)} of {len(searches)} searches succeeded, {len(unique)} unique sources"])
        self.complete = True
        yield self.steps, self.report
