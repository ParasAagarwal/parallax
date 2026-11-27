"""The twin's one tool: draft a message to the owner for the visitor to review and send.

Safety by design: the tool never sends anything. It only records a draft in the run context.
The app then copies the draft into the "Say hello" box, and the message is sent only when the
visitor presses Send there, through the same checks and limits as any other message.
"""

from dataclasses import dataclass
from typing import Literal

from agents import RunContextWrapper, function_tool


@dataclass
class ChatContext:
    """Per-reply state shared between the app and the twin's tool (one per chat reply)."""
    draft: dict | None = None


@function_tool
def draft_message(
    ctx: RunContextWrapper[ChatContext],
    kind: Literal["Reach out", "Feedback", "Suggestion"],
    message: str,
    name: str = "",
    email: str = "",
) -> str:
    """Put a short draft message in the "Say hello" box below the chat, for the visitor to review and send.

    Args:
        kind: "Reach out" for opportunities, roles, projects or meetings; "Feedback" or "Suggestion" for the website.
        message: 2 to 4 sentences written AS the visitor, in their first person, addressed to the owner by name
            (e.g. "Hi Paras, I'd suggest..." or "Hi Paras, I'm hiring for..."). Use only what the visitor said.
            Never describe the visitor in the third person ("Maya suggested...").
        name: The visitor's name, only if they stated it in this chat. Otherwise leave empty.
        email: The visitor's email, only if they typed it in this chat. Otherwise leave empty.
    """
    ctx.context.draft = {"kind": kind, "message": message.strip(), "name": name.strip(), "email": email.strip()}
    return ("Draft placed in the Say hello box below the chat. It is NOT sent. In your reply, tell the visitor "
            "in one sentence to review it, add their email if they want a reply, and press Send.")
