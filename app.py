"""
Parallax - Paras's AI workspace: a research agent and an AI twin, built to keep growing.

Run locally:   cd parallax  then  uv run app.py
"""

import os
import re
import time

import gradio as gr
from agents import Runner
from openai.types.responses import ResponseTextDeltaEvent

from about.agent import twin_agent
from about.draft import ChatContext
from config import (
    ERROR_ICONS, MAX_CHAT_CHARS, MAX_HISTORY_CHARS, MAX_HISTORY_MESSAGES, MAX_MESSAGE_CHARS,
    MAX_QUERY_CHARS, MESSAGES_PER_VISITOR, OWNER_EMAIL, OWNER_FIRST_NAME, friendly_error, missing_keys,
)
from logbook import log_in_background, logging_enabled, send_event
from research.manager import ResearchManager
from ui import (
    CHAT_EXAMPLES, CONTACT_INTRO, CSS, LIGHT_ONLY_HEAD, RESEARCH_EXAMPLES, RESEARCH_HINT, THEME,
    TWIN_NOTE, activity_html, footer_html, hero_html, html_block, quota_html, showcase_html, status_html,
)
from limits import limiter, visitor_key


LOG_CELL_CHARS = 45_000   # stays under Google Sheets' 50,000-character limit per cell


def show_quota(request: gr.Request):
    """Runs when the page opens: shows how many messages this visitor can still send."""
    left = limiter.remaining(visitor_key(request))
    return quota_html(left, MESSAGES_PER_VISITOR), gr.update(interactive=left > 0)


# ---------------------------------------------------------------- Research tab

def _research_problem(question: str) -> str:
    """Why a question can't be researched, or "" if it's fine."""
    if not question:
        return "Type a research question first, or pick one of the examples."
    if len(question) < 8:
        return "Give Parallax a little more to work with, for example a full question."
    if len(question) > MAX_QUERY_CHARS:
        return f"Please keep questions under {MAX_QUERY_CHARS} characters (yours is {len(question)})."
    if missing_keys():
        return "Research is unavailable right now: Parallax is missing its API keys."
    return ""


def start_research(question: str):
    """Step 1, instant: check the question. If it's fine, empty the search box and hand the question
    to step 2 (via the `pending` state). If not, keep the text in the box so the visitor can fix it.
    Returns (search box, pending question, activity panel, report)."""
    question = (question or "").strip()
    problem = _research_problem(question)
    if problem:
        return question, "", activity_html(notice=problem), gr.update()
    return "", question, gr.update(), ""


async def research(question: str):
    """Step 2: run the pipeline. Yields (activity panel HTML, report Markdown) as it progresses."""
    if not question:      # step 1 rejected the question; nothing to do
        return

    manager = ResearchManager()
    steps, report = [], ""
    started = time.monotonic()
    try:
        async for steps, report in manager.run(question):
            yield activity_html(steps, question=question), report
        if manager.complete:
            # Finished successfully: fold the trace into one line so the brief moves up.
            yield activity_html(steps, collapsed=True, question=question), report
    except Exception as error:  # last safety net - the manager already handles expected errors
        report = friendly_error(error)
        yield activity_html(notice="Research stopped unexpectedly."), report

    log_in_background("research", {
        "question": question,
        "status": "complete" if manager.complete else "failed",
        "seconds": round(time.monotonic() - started),
        "sources": len({link["url"] for step in steps for link in step.links}),
        "words": len(report.split("## Sources")[0].split()) if manager.complete else 0,
        "failed_steps": "; ".join(step.title for step in steps if step.status == "failed"),
        # Each agent's own output, so the pipeline can be reviewed and refined later.
        # A Google Sheets cell holds at most 50,000 characters, so each is capped below that.
        "plan": manager.plan_log[:LOG_CELL_CHARS],
        "search_summaries": "\n\n".join(manager.search_log)[:LOG_CELL_CHARS],
        "report": (manager.report or report)[:LOG_CELL_CHARS],
    })


# ---------------------------------------------------------------- Ask-Paras tab

def _text_of(content) -> str:
    """Gradio history content can be a string or a list of parts - get plain text out of it."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    return ""


def _history_to_input(history: list, message: str) -> list[dict]:
    """The conversation so far, cleaned up: only recent messages, each trimmed,
    and without earlier error messages (those aren't part of the conversation)."""
    items = []
    for entry in history[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(entry, dict) or entry.get("role") not in ("user", "assistant"):
            continue
        text = _text_of(entry.get("content")).strip()
        if not text or (entry["role"] == "assistant" and text.startswith(ERROR_ICONS)):
            continue
        items.append({"role": entry["role"], "content": text[:MAX_HISTORY_CHARS]})
    items.append({"role": "user", "content": message})
    return items


def start_chat(message: str, history: list):
    """Step 1, instant: show the visitor's message in the chat and empty the box.
    Returns (chat box, pending message, chat window)."""
    message = (message or "").strip()
    history = history or []
    if not message:
        return "", "", history
    if len(message) > MAX_CHAT_CHARS:
        note = f"⚠️ That's a long message! Please keep it under {MAX_CHAT_CHARS} characters (yours is {len(message)})."
        return message, "", history + [{"role": "assistant", "content": note}]   # keep the text so they can shorten it
    return "", message, history + [{"role": "user", "content": message}]


MESSAGE_KINDS = ("Feedback", "Suggestion", "Reach out")
NO_CHANGE = (gr.update(),) * 5     # leaves the five Say hello outputs as they are


def _draft_updates(draft: dict | None):
    """Turns the twin's draft into updates for the Say hello box: (kind, message, name, email, status).
    Everything is checked here, in code, so the model can't put anything odd into the form."""
    if not draft or draft.get("kind") not in MESSAGE_KINDS or not draft.get("message"):
        return NO_CHANGE
    name, email = draft.get("name", "")[:100], draft.get("email", "")[:200]
    return (
        draft["kind"],
        draft["message"][:MAX_MESSAGE_CHARS],
        name or gr.update(),                                      # never wipe what the visitor typed
        email if EMAIL_PATTERN.match(email) else gr.update(),
        status_html("Drafted from your chat. Check it, add your email if you'd like a reply, and press Send.", "ok"),
    )


async def chat_reply(message: str, history: list):
    """Step 2: stream the twin's answer word by word into the chat window.
    `history` already ends with the visitor's message (added in step 1).
    Yields (chat window, then the Say hello box's kind, message, name, email and status line)."""
    if not message:      # step 1 rejected the message; nothing to do
        return
    earlier = history[:-1]

    if "GOOGLE_API_KEY" in missing_keys():
        yield history + [{"role": "assistant", "content": "🔑 Chat is unavailable right now: Parallax is missing its API key."}], *NO_CHANGE
        return

    answer, status = "", "ok"
    context = ChatContext()   # fresh per reply; the draft_message tool writes into it
    try:
        # max_turns=3: one turn may be a draft_message call, the next is the written reply.
        result = Runner.run_streamed(twin_agent, _history_to_input(earlier, message), context=context, max_turns=3)
        async for event in result.stream_events():
            if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                answer += event.data.delta
                yield history + [{"role": "assistant", "content": answer}], *NO_CHANGE
        if not answer.strip():
            answer = (str(result.final_output or "").strip()
                      or "Sorry, I lost my train of thought there. Could you ask that again?")
    except Exception as error:
        status = f"error: {type(error).__name__}"
        problem = friendly_error(error)
        # Keep whatever was already written, then explain what went wrong underneath.
        answer = (answer.strip() + "\n\n" + problem) if answer.strip() else problem

    # Final update: the full answer, plus the draft (if the twin made one) copied into the Say hello box.
    yield history + [{"role": "assistant", "content": answer}], *_draft_updates(context.draft)

    log_in_background("chat", {
        "question": message,
        "answer": answer[:3000],
        "status": status,
        "turn": sum(1 for m in history if m.get("role") == "user"),   # 1 = first message of the conversation
        "drafted": context.draft["kind"] if context.draft else "",
    })


# ---------------------------------------------------------------- Message box

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def send_message(name: str, email: str, kind: str, message: str, request: gr.Request):
    """Validates the form, applies the limits and sends the message to the owner.
    Returns (status line, message box, messages-left line, send button)."""
    name, email, message = (name or "").strip(), (email or "").strip(), (message or "").strip()
    who = visitor_key(request)

    def result(text: str, tone: str, box: str = message):
        left = limiter.remaining(who)
        return (status_html(text, tone), box, quota_html(left, MESSAGES_PER_VISITOR),
                gr.update(interactive=left > 0))

    if not message:
        return result("Write a message first.", "warn")
    if len(message) > MAX_MESSAGE_CHARS:
        return result(f"Please keep it under {MAX_MESSAGE_CHARS} characters (yours is {len(message)}).", "warn")
    if email and not EMAIL_PATTERN.match(email):
        return result("That email doesn't look right. Fix it, or leave it empty.", "warn")
    if limiter.remaining(who) <= 0:
        return result(f"You've reached today's limit. For anything urgent, email me at {OWNER_EMAIL}.", "warn")
    wait = limiter.wait_seconds(who)
    if wait:
        return result(f"Please wait {wait} second{'s' if wait != 1 else ''} before sending another message.", "warn")
    if limiter.site_is_full():
        return result(f"Parallax has had a lot of messages today. Please email me at {OWNER_EMAIL}.", "warn")
    if not logging_enabled():
        return result(f"Messages aren't switched on yet. Please email me at {OWNER_EMAIL}.", "warn")

    limiter.record(who)   # count it before sending, so two quick clicks can't both get through
    sent = await send_event("message", {
        "type": kind or "Feedback",
        "name": name[:100] or "(not given)",
        "email": email[:200] or "(not given)",
        "message": message,
    })
    if not sent:
        limiter.undo(who)   # not delivered: give the attempt back
        return result(f"Your message couldn't be sent just now. Please try again, or email me at {OWNER_EMAIL}.",
                      "warn")
    reply_note = " I'll reply by email." if email else ""
    return result(f"Thanks, your message reached me.{reply_note}", "ok", box="")


# ---------------------------------------------------------------- Layout

with gr.Blocks(title="Parallax: research agent and AI twin") as app:
    html_block(hero_html(missing_keys()))

    with gr.Tabs(elem_id="sc-tabs"):

        with gr.Tab("Research"):
            with gr.Row(equal_height=True, elem_id="sc-search"):
                question_box = gr.Textbox(
                    placeholder="What do you want to know?", show_label=False, container=False,
                    autofocus=True, max_lines=3, elem_id="sc-query", scale=5,
                )
                run_button = gr.Button("Research", variant="primary", elem_id="sc-run", scale=1, min_width=120)

            # Example chips: clicking one copies its full question into the search box.
            with gr.Row(elem_classes="sc-chips"):
                for label, full_question in RESEARCH_EXAMPLES:
                    chip = gr.Button(label, size="sm", scale=0, min_width=0)
                    chip.click(lambda q=full_question: q, outputs=question_box, queue=False)
            html_block(RESEARCH_HINT)

            activity = html_block(activity_html())
            report = gr.Markdown(elem_id="sc-report")
            pending = gr.State("")   # the question handed from step 1 to step 2

            # Step 1 (instant) checks the question and empties the box; .then() starts step 2, the research.
            # concurrency_limit: at most 2 research runs at once, to protect the free API quota.
            # Extra visitors wait in Gradio's queue and see their position.
            for trigger in (run_button.click, question_box.submit):
                trigger(
                    start_research, inputs=question_box, outputs=[question_box, pending, activity, report],
                    queue=False,
                ).then(
                    research, inputs=pending, outputs=[activity, report],
                    concurrency_limit=2, concurrency_id="research", show_progress="hidden",
                )

        with gr.Tab(f"Ask {OWNER_FIRST_NAME}"):
            # A hand-built chat (instead of gr.ChatInterface), so it can use the same chips and
            # box-clearing behaviour as the Research tab.
            chatbot = gr.Chatbot(elem_id="sc-chat", show_label=False, height=440, placeholder=(
                f"**Hi, I'm {OWNER_FIRST_NAME}'s AI twin.**  \n"
                "Ask me about my work, skills, projects, or how to reach me."))
            with gr.Row(equal_height=True, elem_id="sc-chat-input"):
                chat_box = gr.Textbox(placeholder="Ask me anything…", show_label=False, container=False,
                                      max_lines=4, elem_id="sc-chat-box", scale=5)
                chat_send = gr.Button("Send", variant="primary", elem_id="sc-chat-send", scale=1, min_width=90)
            with gr.Row(elem_classes="sc-chips"):
                for example in CHAT_EXAMPLES:
                    chip = gr.Button(example, size="sm", scale=0, min_width=0)
                    chip.click(lambda q=example: q, outputs=chat_box, queue=False)
            html_block(TWIN_NOTE)
            pending_chat = gr.State("")
            # The chat's events are wired further down, after the Say hello box exists,
            # because a reply can fill that box with a draft.

        with gr.Tab("How it works"):
            html_block(showcase_html())

    # Message box: feedback, suggestions, or reaching out. Sits above the footer on every tab.
    with gr.Column(elem_id="sc-contact"):
        html_block(CONTACT_INTRO)
        contact_kind = gr.Radio(["Feedback", "Suggestion", "Reach out"], value="Feedback",
                                show_label=False, container=False, elem_id="sc-kind")
        with gr.Row(elem_id="sc-contact-who"):
            contact_name = gr.Textbox(placeholder="Your name (optional)", show_label=False, container=False)
            contact_email = gr.Textbox(placeholder="Your email, if you'd like a reply", show_label=False,
                                       container=False)
        contact_message = gr.Textbox(placeholder="Your message", lines=3, max_lines=8, show_label=False,
                                     container=False, elem_id="sc-message")
        send_button = gr.Button("Send message", variant="primary", elem_id="sc-send")
        contact_status = html_block()
        contact_quota = html_block(quota_html(MESSAGES_PER_VISITOR, MESSAGES_PER_VISITOR))

        send_button.click(send_message,
                          inputs=[contact_name, contact_email, contact_kind, contact_message],
                          outputs=[contact_status, contact_message, contact_quota, send_button],
                          concurrency_limit=4)

    # Chat wiring. Step 1 (instant) shows the message and empties the box; step 2 streams the reply,
    # and its last update may drop a draft into the Say hello box (never sends it).
    for trigger in (chat_send.click, chat_box.submit):
        trigger(
            start_chat, inputs=[chat_box, chatbot], outputs=[chat_box, pending_chat, chatbot], queue=False,
        ).then(
            chat_reply, inputs=[pending_chat, chatbot],
            outputs=[chatbot, contact_kind, contact_message, contact_name, contact_email, contact_status],
            concurrency_limit=4, concurrency_id="chat", show_progress="hidden",
        )

    html_block(footer_html())

    app.load(show_quota, outputs=[contact_quota, send_button], show_progress="hidden", queue=False)


if __name__ == "__main__":
    # Hosting platforms (Render, Railway, Fly, ...) set PORT and expect the app on 0.0.0.0.
    # Locally there's no PORT, so Gradio uses its usual 127.0.0.1:7860.
    port = os.getenv("PORT")
    app.queue(max_size=20).launch(
        css=CSS, theme=THEME, head=LIGHT_ONLY_HEAD,
        server_name="0.0.0.0" if port else None,
        server_port=int(port) if port else None,
    )
