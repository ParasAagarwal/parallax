"""
Shared settings for Parallax.

Everything that you might want to tweak lives here: the model, the limits,
the owner's name, and the friendly error messages shown to visitors.
"""

import os
import sys

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError

load_dotenv(override=True)

# Some consoles (e.g. Windows) can't print every character; never let a log line crash a request.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(errors="replace")
    except Exception:
        pass

# Traces are uploaded to OpenAI, and production has no OpenAI key - so switch them off.
# (Parallax shows its own live "activity" panel instead.)
set_tracing_disabled(True)


# ---------- Who this site is about ----------

OWNER_NAME = "Paras Agarwal"
OWNER_FIRST_NAME = "Paras"
OWNER_PRONOUNS = "he/him"   # how others refer to the owner, e.g. "he/him", "she/her", "they/them"
OWNER_EMAIL = "parasjuly2003@gmail.com"   # shown if the message box isn't connected yet


# ---------- Activity log + messages (optional) ----------
# A free Google Apps Script web app (see apps_script/Code.gs) writes each event to a Google Sheet
# and emails the owner. If PARALLAX_LOG_URL isn't set, logging is simply switched off.

LOG_URL = os.getenv("PARALLAX_LOG_URL", "").strip()
LOG_TOKEN = os.getenv("PARALLAX_LOG_TOKEN", "").strip()   # shared secret, so only Parallax can write to the Sheet
MAX_MESSAGE_CHARS = 2000        # longest message a visitor can send
MESSAGE_COOLDOWN_SECONDS = 5    # minimum gap between two messages from the same visitor
MESSAGES_PER_VISITOR = 5        # messages one visitor can send per 24 hours (feedback + suggestions + reach-outs)
MESSAGES_PER_DAY_TOTAL = 80     # site-wide cap per 24 hours, so Gmail's ~100 emails/day quota is never exhausted


# ---------- The model: one free Gemini model for every agent ----------

MODEL_NAME = "gemini-3.5-flash-lite"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# max_retries: automatically retry when Google is briefly busy (503) or rate-limits us (429)
# timeout: never let a single LLM call hang forever
gemini_client = AsyncOpenAI(
    base_url=GEMINI_BASE_URL,
    api_key=GOOGLE_API_KEY or "missing-key",  # the client refuses None; we report the missing key in the UI
    max_retries=3,
    timeout=90,
)
model = OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=gemini_client)


# ---------- Limits (kept small so the free tier copes) ----------

HOW_MANY_SEARCHES = 3          # parallel web searches per research question
RESULTS_PER_SEARCH = 5         # Tavily results per search
MAX_CHARS_PER_RESULT = 1500    # trim each web page so prompts stay small
MAX_QUERY_CHARS = 400          # longest research question we accept
MAX_CHAT_CHARS = 1000          # longest chat message we accept
MAX_HISTORY_MESSAGES = 12      # chat turns we send back to the model (keeps context small)
MAX_HISTORY_CHARS = 2000       # each earlier message is trimmed to this, so long answers can't bloat the prompt


def missing_keys() -> list[str]:
    """Names of required environment variables that are not set."""
    required = {"GOOGLE_API_KEY": GOOGLE_API_KEY, "TAVILY_API_KEY": TAVILY_API_KEY}
    return [name for name, value in required.items() if not value]


# ---------- Friendly errors ----------

# Every friendly error starts with one of these icons. The chat uses them to leave
# earlier error messages out of the conversation history it sends to the model.
ERROR_ICONS = ("⏳", "🌩️", "🔑", "📡", "🤔", "🔁", "⚠️")

def friendly_error(error: Exception) -> str:
    """Turn any exception into a short, human message for visitors.
    The full technical error is printed to the server logs for the owner."""
    print(f"[parallax] {type(error).__name__}: {error}", flush=True)

    if isinstance(error, RateLimitError):
        return ("⏳ **The free model's rate limit was reached.** Parallax runs on Google's free tier, "
                "which allows only a limited number of requests per minute. "
                "Please wait about a minute and try again.")
    if isinstance(error, APIStatusError) and error.status_code == 503:
        return ("🌩️ **Google's free model is overloaded right now.** This happens at busy times and "
                "usually passes within a few minutes. Please try again shortly.")
    if isinstance(error, APIStatusError) and error.status_code in (400, 401, 403) and "key" in str(error).lower():
        return "🔑 **Parallax isn't configured correctly** (API key problem). The owner has been notified via the logs."
    if isinstance(error, (APITimeoutError, APIConnectionError)):
        return "📡 **Couldn't reach the AI model** (network timeout). Please try again."
    if isinstance(error, ModelBehaviorError):
        return ("🤔 **The model returned something unexpected.** Small free models occasionally do this. "
                "Trying again usually works.")
    if isinstance(error, MaxTurnsExceeded):
        return "🔁 **The agent went round in circles** and was stopped. Try rephrasing your question."
    return "⚠️ **Something went wrong.** Please try again in a moment."


def short_error(error: Exception) -> str:
    """Just the bold headline of friendly_error, for one-line status displays."""
    message = friendly_error(error)
    return message.split("**")[1].rstrip(".") if message.count("**") >= 2 else "Something went wrong"
