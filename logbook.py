"""
Logbook: sends visitor activity and messages to the owner's Google Sheet (and inbox).

The receiving end is a free Google Apps Script web app (apps_script/Code.gs). It adds a row
to a Google Sheet and emails the owner. Render's free disk is wiped whenever the app sleeps,
so the Sheet is the permanent log.

Rules:
- Logging must never slow down or break the app for a visitor. Activity is sent in the
  background ("fire and forget"); any failure is only printed to the server log.
- If PARALLAX_LOG_URL isn't set, nothing is sent.
"""

import asyncio

import httpx

from config import LOG_TOKEN, LOG_URL

# Background tasks need a reference somewhere, or Python may clean them up before they finish.
_background: set[asyncio.Task] = set()


def logging_enabled() -> bool:
    return bool(LOG_URL)


async def send_event(kind: str, data: dict) -> bool:
    """Send one event and wait for the answer. Returns True if the Sheet accepted it."""
    if not LOG_URL:
        return False
    payload = {"token": LOG_TOKEN, "kind": kind, "data": data}
    try:
        # Apps Script answers a POST with a redirect to the result, so follow redirects.
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.post(LOG_URL, json=payload)
        accepted = response.status_code == 200 and response.json().get("ok") is True
        if not accepted:
            print(f"[parallax] Log endpoint refused '{kind}': {response.status_code} {response.text[:200]}", flush=True)
        return accepted
    except Exception as error:
        print(f"[parallax] Couldn't log '{kind}': {type(error).__name__}: {error}", flush=True)
        return False


def log_in_background(kind: str, data: dict) -> None:
    """Fire and forget: start sending the event and return immediately."""
    if not LOG_URL:
        return
    task = asyncio.create_task(send_event(kind, data))
    _background.add(task)
    task.add_done_callback(_background.discard)
