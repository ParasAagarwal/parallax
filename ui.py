"""
Everything visual: copy, example prompts, the theme, CSS, and small functions that build HTML.
Kept separate from app.py so the app logic stays easy to read.

Design: light and quiet. One centred column, one accent colour (pine green), one typeface
(Instrument Sans). The headline is the only loud element; everything else stays out of the way.
"""

import html
import re
import time

import gradio as gr

from config import HOW_MANY_SEARCHES, MODEL_NAME, OWNER_FIRST_NAME, OWNER_NAME

LINKEDIN_URL = "https://www.linkedin.com/in/parasagarwal-dev"

# (short label on the chip, full question that goes into the search box)
RESEARCH_EXAMPLES = [
    ("Top AI agent frameworks?", "What are the most popular open-source AI agent frameworks in 2026?"),
    ("How is GenAI ROI measured?", "How are companies measuring ROI on generative AI projects?"),
    ("Can small models run on laptops?", "What is the current state of small language models running on laptops?"),
    ("RAG or long context?", "Compare RAG and long-context models for enterprise search."),
]

CHAT_EXAMPLES = [
    "Introduce yourself in a few lines.",
    "What kind of roles are you looking for?",
    "How can I get in touch with you?",
]


# ---------------------------------------------------------------- theme

PINE = "#0F6E56"

THEME = gr.themes.Base(
    font=[gr.themes.GoogleFont("Instrument Sans"), "system-ui", "sans-serif"],
    radius_size=gr.themes.sizes.radius_lg,
).set(
    body_background_fill="#FFFFFF",
    body_text_color="#16181D",
    color_accent=PINE,
    color_accent_soft="#E8F3EF",
    button_primary_background_fill=PINE,
    button_primary_background_fill_hover="#0B5A46",
    button_primary_text_color="#FFFFFF",
    input_background_fill="#F4F5F7",
    block_border_width="0px",
    block_shadow="none",
    # Same colours for dark mode, in case the script below can't run: the design is light-only.
    body_background_fill_dark="#FFFFFF",
    body_text_color_dark="#16181D",
    body_text_color_subdued_dark="#6A707C",
    background_fill_primary_dark="#FFFFFF",
    background_fill_secondary_dark="#F4F5F7",
    block_background_fill_dark="#FFFFFF",
    border_color_primary_dark="#E6E8EC",
    color_accent_soft_dark="#E8F3EF",
    button_primary_background_fill_dark=PINE,
    button_primary_background_fill_hover_dark="#0B5A46",
    button_primary_text_color_dark="#FFFFFF",
    input_background_fill_dark="#F4F5F7",
)

# Gradio switches to dark mode when the visitor's system is dark. This design is light-only,
# so this small script removes Gradio's "dark" class whenever it appears.
# (Gradio adds `head` scripts after the page has loaded, so it runs straight away rather than
# waiting for a load event that has already happened.)
LIGHT_ONLY_HEAD = """
<script>
(() => {
  const keepLight = () => document.body.classList.remove("dark");
  const start = () => {
    keepLight();
    new MutationObserver(keepLight).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  };
  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);
})();
</script>
"""


def html_block(value: str = "", **kwargs) -> gr.HTML:
    """A gr.HTML without Gradio's default text styles, so this file's CSS decides every colour."""
    return gr.HTML(value, apply_default_css=False, padding=False, **kwargs)


# ---------------------------------------------------------------- header, hints, footer

# The Parallax mark: one ring seen from two viewpoints, slightly offset - the parallax effect.
BRAND_MARK = """
<svg class="sc-mark" viewBox="0 0 32 32" aria-hidden="true">
  <circle cx="13" cy="16" r="9.5" fill="none" stroke="currentColor" stroke-width="2.2" opacity=".45"/>
  <circle cx="19" cy="16" r="9.5" fill="none" stroke="currentColor" stroke-width="2.2"/>
</svg>"""


def hero_html(missing: list[str]) -> str:
    warning = ""
    if missing:
        warning = (f'<p class="sc-alert">Parallax is missing <code>{html.escape(", ".join(missing))}</code>, '
                   f'so some features won\'t work until it\'s set.</p>')
    return f"""
<header class="sc-hero">
  <div class="sc-brand">{BRAND_MARK}<span>Parallax</span></div>
  <h1>Ask the web.<br>Or ask {OWNER_FIRST_NAME}.</h1>
  <p class="sc-sub">Parallax looks at your question from several angles and writes you a short, sourced brief.
  It also knows {OWNER_FIRST_NAME}, who built it.</p>
  {warning}
</header>"""


RESEARCH_HINT = ('<p class="sc-hint">A run takes about a minute on a free AI model. '
                 'Every brief lists the sources it used.</p>')

TWIN_NOTE = (f'<p class="sc-hint">You\'re chatting with an AI twin of {OWNER_FIRST_NAME}, '
             f'which answers from his profile and resume. It can get things wrong.</p>')


CONTACT_INTRO = f"""
<div class="sc-contact-intro">
  <h2>Say hello</h2>
  <p>Feedback on Parallax, an idea, or an opportunity? Send it here and it goes straight to my inbox.</p>
</div>"""


def status_html(text: str, tone: str = "ok") -> str:
    """A one-line result under the message box. tone: ok | warn"""
    return f'<p class="sc-status sc-status-{tone}">{html.escape(text)}</p>'


def quota_html(left: int, total: int) -> str:
    """How many messages this visitor can still send."""
    if left <= 0:
        text = f"You've sent {total} messages, the limit for today. Thanks for all the notes!"
    else:
        text = f"{left} of {total} messages left today"
    return f'<p class="sc-quota">{text}</p>'


def footer_html() -> str:
    return f"""
<footer class="sc-foot">
  <p>Parallax runs on Google's free <b>{MODEL_NAME}</b> model and free hosting. If it has been idle,
  the first request can take up to a minute while it wakes up. Busy moments pass quickly: just try again.</p>
  <p>Research questions and chats are saved so {OWNER_FIRST_NAME} can improve Parallax.
  Please don't share anything sensitive.</p>
  <p>Built by <a href="{LINKEDIN_URL}" target="_blank" rel="noopener">{OWNER_NAME}</a> with the OpenAI Agents SDK.</p>
</footer>"""


# ---------------------------------------------------------------- activity panel (the live trace)

SLOW_AFTER_SECONDS = 20   # a running step older than this gets a reassuring "still working" note
SPIN_SECONDS = 0.8        # one spinner rotation; must match the animation in the CSS

CHECK_ICON = ('<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" fill="none" '
              'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
FAIL_ICON = ('<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 4v5M8 11.5v.5" fill="none" '
             'stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>')


def _inline(text: str) -> str:
    """Escape text, then allow **bold** only."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text))


def _domain(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0]


def _step_rows(steps) -> str:
    # The panel is rebuilt on every update, which would restart the spinner animation each time.
    # Starting it at a clock-based point (negative delay) keeps the rotation smooth across rebuilds.
    spin_phase = time.monotonic() % SPIN_SECONDS
    spinner = f'<span class="sc-spin" style="animation-delay: -{spin_phase:.2f}s"></span>'

    rows = []
    for step in steps:
        icon = {"running": spinner, "done": CHECK_ICON, "failed": FAIL_ICON}[step.status]
        details = "".join(f"<li>{_inline(d)}</li>" for d in step.details)
        if step.status == "running" and step.seconds > SLOW_AFTER_SECONDS:
            details += '<li class="sc-slow">Still working. Free AI models can be slow at busy times.</li>'
        links = "".join(
            f'<a href="{html.escape(link["url"])}" target="_blank" rel="noopener" title="{html.escape(link["title"])}">'
            f'{html.escape(_domain(link["url"]))}</a>'
            for link in step.links
        )
        rows.append(f"""
<div class="sc-step sc-{step.status}">
  <div class="sc-icon">{icon}</div>
  <div class="sc-body">
    <div class="sc-title"><span>{_inline(step.title)}</span><span class="sc-time">{step.seconds:.1f}s</span></div>
    {f'<ul class="sc-details">{details}</ul>' if details else ''}
    {f'<div class="sc-links">{links}</div>' if links else ''}
  </div>
</div>""")
    return "".join(rows)


def activity_html(steps=None, notice: str = "", collapsed: bool = False, question: str = "") -> str:
    """The live trace. Three shapes:
    - a one-line notice (input problems), or nothing at all before the first run
    - the full trace while research runs (or after it stopped with an error)
    - a one-line summary that expands on click, once research finished successfully
    `question` is shown above the trace, since the search box is emptied when research starts."""
    if notice:
        return f'<p class="sc-notice">{_inline(notice)}</p>'
    if not steps:
        return ""
    asked = f'<p class="sc-asked">{html.escape(question)}</p>' if question else ""
    return asked + _trace_html(steps, collapsed)


def _trace_html(steps, collapsed: bool) -> str:
    if collapsed:
        sources = len({link["url"] for step in steps for link in step.links})
        seconds = steps[-1].seconds   # the last step ("Research complete") spans the whole run
        return f"""
<details class="sc-activity sc-collapsed">
  <summary>
    <span class="sc-icon sc-ok">{CHECK_ICON}</span>
    <span class="sc-summary-text">Read {sources} sources in {seconds:.0f} seconds</span>
    <span class="sc-toggle"></span>
  </summary>
  <div class="sc-steps">{_step_rows(steps)}</div>
</details>"""

    running = any(step.status == "running" for step in steps)
    elapsed = (time.monotonic() if running else max(step.ended or 0 for step in steps)) - steps[0].started
    heading = "Researching" if running else "Research stopped"
    return f"""
<div class="sc-activity">
  <div class="sc-activity-head"><span>{heading}</span><span class="sc-time">{elapsed:.0f}s</span></div>
  <div class="sc-steps">{_step_rows(steps)}</div>
</div>"""


# ---------------------------------------------------------------- "How it works"

SKILLS = [
    "OpenAI Agents SDK", "Multi-agent pipeline", "Code-driven orchestration", "Function tools",
    "Structured outputs (Pydantic)", "Async parallel runs", "Streaming", "Run context",
    "Date-aware instructions", "Grounded digital twin", "Prompt guardrails",
    "Gemini (OpenAI-compatible API)", "Tavily search API", "Gradio", "Graceful error handling",
]


def showcase_html() -> str:
    chips = "".join(f"<li>{html.escape(s)}</li>" for s in SKILLS)
    return f"""
<div class="sc-how">

  <section>
    <h2>Research</h2>
    <p class="sc-lead">A pipeline where Python decides the order and each agent does one job.</p>
    <ol class="sc-pipeline">
      <li><b>Plan</b><span>A planner agent turns your question into {HOW_MANY_SEARCHES} web searches,
        returned as typed data (Pydantic), so the code can rely on its shape.</span></li>
      <li><b>Search</b><span>{HOW_MANY_SEARCHES} searcher agents run in parallel. Each must call a Tavily
        web-search tool and summarise only what it finds.</span></li>
      <li><b>Write</b><span>A writer agent streams the brief word by word, written as of today's date,
        and follows any length you ask for.</span></li>
      <li><b>Cite</b><span>Code adds the sources the search tool actually returned, so the list is
        always real, never written by the model.</span></li>
    </ol>
    <p class="sc-note">The trace above each brief shows these steps live, refreshed every second,
    with the plan, timings and sources.</p>
  </section>

  <section>
    <h2>Ask {OWNER_FIRST_NAME}</h2>
    <p class="sc-lead">An AI twin that answers as {OWNER_FIRST_NAME}, in the first person.</p>
    <ul class="sc-points">
      <li>His profile and resume are part of the agent's instructions, so answers are grounded
        and need no lookups.</li>
      <li>It remembers the last few messages, so follow-up questions work.</li>
      <li>One tool, used sparingly: when you want to hire, work with or reach {OWNER_FIRST_NAME}, or share
        feedback, it drafts a short note into the Say hello box. You review it, add your email and press
        Send. The agent can draft, but never send.</li>
      <li>Guardrails keep it honest and professional: no invented facts, private topics stay private,
        and attempts to change its role are ignored.</li>
    </ul>
  </section>

  <section>
    <h2>Built with</h2>
    <ul class="sc-tags">{chips}</ul>
  </section>

  <section>
    <h2>Trade-offs</h2>
    <ul class="sc-points">
      <li>Everything runs on a free, lightweight model ({MODEL_NAME}). It's quick, but briefs are
        less nuanced than a frontier model would write.</li>
      <li>Free tiers have rate limits. Parallax retries automatically, keeps to {HOW_MANY_SEARCHES} searches,
        and says clearly when you need to wait.</li>
      <li>Free hosting sleeps when idle, so the first visit after a quiet spell is slower.</li>
    </ul>
  </section>
</div>"""


# ---------------------------------------------------------------- CSS

CSS = """
:root {
  --sc-ink: #16181D;
  --sc-ink-2: #3A3F4A;
  --sc-muted: #6A707C;
  --sc-line: #E6E8EC;
  --sc-surface: #F4F5F7;
  --sc-paper: #FFFFFF;
  --sc-pine: #0F6E56;
  --sc-pine-dark: #0B5A46;
  --sc-pine-tint: #E8F3EF;
  --sc-amber: #9A5B00;
  --sc-red: #B42318;
}

footer:not(.sc-foot), .built-with, .show-api, .api-docs { display: none !important; }
html, body, gradio-app { background: var(--sc-paper) !important; }

.gradio-container {
  max-width: 760px !important;
  margin: 0 auto !important;
  padding: 56px 16px 40px !important;
  color: var(--sc-ink);
}

/* ---------- hero ---------- */
.sc-hero { text-align: center; margin-bottom: 8px; }
.sc-brand {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 15px; font-weight: 600; color: var(--sc-ink);
}
.sc-mark { width: 22px; height: 22px; color: var(--sc-pine); }
.sc-hero h1 {
  margin: 28px 0 14px;
  font-size: clamp(40px, 7vw, 64px); line-height: 1.02; font-weight: 600;
  letter-spacing: -0.035em; color: var(--sc-ink);
}
.sc-sub {
  max-width: 34em; margin: 0 auto; font-size: 17px; line-height: 1.5; color: var(--sc-muted);
}
.sc-alert {
  margin: 18px auto 0; max-width: 34em; padding: 10px 14px; border-radius: 12px;
  background: #FEF3F2; color: var(--sc-red); font-size: 14px;
}

/* ---------- tabs as a segmented control ---------- */
#sc-tabs .tab-wrapper { justify-content: center; height: auto; padding: 0; margin: 28px 0 26px; }
#sc-tabs .tab-container {
  width: auto; height: auto; padding: 4px; gap: 2px;
  background: var(--sc-surface); border-radius: 999px;
}
#sc-tabs .tab-container::after { display: none; }
#sc-tabs .tab-container button {
  height: 36px; padding: 0 18px; border-radius: 999px;
  font-size: 14.5px; font-weight: 500; color: var(--sc-muted);
}
#sc-tabs .tab-container button:hover:not(.selected) { background: transparent; color: var(--sc-ink); }
#sc-tabs .tab-container button.selected {
  background: var(--sc-paper); color: var(--sc-ink);
  box-shadow: 0 1px 2px rgba(22, 24, 29, .08), 0 1px 6px rgba(22, 24, 29, .06);
}
#sc-tabs .tab-container button.selected::after { display: none; }
#sc-tabs button:focus-visible { outline: 2px solid var(--sc-pine); outline-offset: 2px; }

/* ---------- search ---------- */
#sc-search, #sc-chat-input { gap: 10px; align-items: stretch; }
#sc-query textarea, #sc-chat-box textarea {
  background: var(--sc-surface) !important; border: 1px solid transparent !important;
  border-radius: 14px !important; padding: 14px 16px !important;
  font-size: 16px !important; color: var(--sc-ink) !important; box-shadow: none !important;
}
#sc-query textarea:focus, #sc-chat-box textarea:focus { border-color: var(--sc-pine) !important; background: var(--sc-paper) !important; }
#sc-run, #sc-chat-send { border-radius: 14px !important; font-size: 15px !important; font-weight: 600 !important; min-height: 52px; }

.sc-chips { gap: 8px !important; flex-wrap: wrap !important; margin-top: 4px; }
.sc-chips button {
  flex: 0 0 auto !important; width: auto !important; min-width: 0 !important;
  padding: 6px 13px !important; border-radius: 999px !important;
  background: var(--sc-paper) !important; border: 1px solid var(--sc-line) !important;
  color: var(--sc-ink-2) !important; font-size: 13.5px !important; font-weight: 500 !important;
  box-shadow: none !important;
}
.sc-chips button:hover { border-color: var(--sc-pine) !important; color: var(--sc-pine) !important; }

.sc-hint { margin: 2px 2px 0; font-size: 13px; color: var(--sc-muted); }
.sc-notice {
  margin: 4px 0 0; padding: 12px 14px; border-radius: 12px;
  background: var(--sc-surface); color: var(--sc-ink-2); font-size: 14.5px;
}

/* ---------- live trace ---------- */
.sc-activity {
  margin: 8px 0 0; padding: 14px 18px; border-radius: 16px;
  background: var(--sc-surface);
}
.sc-activity-head {
  display: flex; justify-content: space-between; margin-bottom: 6px;
  font-size: 14px; font-weight: 600; color: var(--sc-ink);
}
.sc-step { display: flex; gap: 12px; padding: 9px 0; }
.sc-step + .sc-step { border-top: 1px solid var(--sc-line); }
.sc-icon {
  flex-shrink: 0; width: 22px; height: 22px; border-radius: 50%;
  display: grid; place-items: center; margin-top: 1px;
}
.sc-icon svg { width: 14px; height: 14px; }
.sc-done .sc-icon, .sc-ok { background: var(--sc-pine-tint); color: var(--sc-pine); }
.sc-failed .sc-icon { background: #FEF3F2; color: var(--sc-red); }
.sc-running .sc-icon { background: var(--sc-paper); }
.sc-spin {
  width: 12px; height: 12px; border-radius: 50%;
  border: 2px solid var(--sc-line); border-top-color: var(--sc-pine);
  animation: sc-spin 0.8s linear infinite;
}
@keyframes sc-spin { to { transform: rotate(360deg); } }
.sc-body { flex: 1; min-width: 0; }
.sc-title { display: flex; justify-content: space-between; gap: 12px; font-size: 14.5px; color: var(--sc-ink); }
.sc-time { color: var(--sc-muted); font-size: 13px; font-variant-numeric: tabular-nums; flex-shrink: 0; font-weight: 400; }
.sc-failed .sc-title span:first-child { color: var(--sc-red); }
.sc-details { margin: 4px 0 0; padding-left: 16px; color: var(--sc-muted); font-size: 13.5px; line-height: 1.5; }
.sc-details b { color: var(--sc-ink-2); font-weight: 600; }
.sc-slow { color: var(--sc-amber); }
.sc-links { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.sc-links a {
  font-size: 12.5px; padding: 2px 9px; border-radius: 999px; text-decoration: none !important;
  color: var(--sc-ink-2) !important; background: var(--sc-paper); border: 1px solid var(--sc-line);
}
.sc-links a:hover { color: var(--sc-pine) !important; border-color: var(--sc-pine); }

/* collapsed trace: one line, expands on click */
.sc-collapsed { padding: 0; }
.sc-collapsed summary {
  display: flex; align-items: center; gap: 12px; padding: 12px 18px;
  cursor: pointer; list-style: none; font-size: 14.5px; color: var(--sc-ink);
}
.sc-collapsed summary::-webkit-details-marker { display: none; }
.sc-summary-text { flex: 1; }
.sc-toggle { font-size: 13px; color: var(--sc-pine); font-weight: 500; }
.sc-toggle::after { content: "Show steps"; }
.sc-collapsed[open] .sc-toggle::after { content: "Hide steps"; }
.sc-collapsed .sc-steps { padding: 0 18px 10px; }
.sc-collapsed summary:focus-visible { outline: 2px solid var(--sc-pine); outline-offset: 2px; border-radius: 16px; }

/* ---------- the brief ---------- */
#sc-report { margin-top: 18px; }
#sc-report .prose, #sc-report { font-size: 16.5px; line-height: 1.65; }
#sc-report p, #sc-report li, #sc-report td { color: var(--sc-ink-2); }
#sc-report h1 {
  font-size: 30px; line-height: 1.15; letter-spacing: -0.02em; font-weight: 600;
  color: var(--sc-ink); margin: 8px 0 16px;
}
#sc-report h2 { font-size: 20px; font-weight: 600; color: var(--sc-ink); margin: 1.6em 0 0.4em; }
#sc-report p, #sc-report li { max-width: 68ch; }
#sc-report strong { color: var(--sc-ink); }
#sc-report a { color: var(--sc-pine); }
#sc-report hr { border: none; border-top: 1px solid var(--sc-line); margin: 2em 0 1em; }
#sc-report table { font-size: 14.5px; }
/* the Sources list is the last list in the brief: keep it smaller and quieter */
#sc-report hr ~ ol li { font-size: 14px; line-height: 1.55; color: var(--sc-muted); }

/* ---------- chat ---------- */
#sc-chat { border-radius: 16px; }

/* ---------- how it works ---------- */
.sc-how { color: var(--sc-ink-2); }
.sc-how section { padding: 6px 0 26px; }
.sc-how section + section { border-top: 1px solid var(--sc-line); padding-top: 26px; }
.sc-how h2 { margin: 0 0 4px; font-size: 22px; font-weight: 600; letter-spacing: -0.01em; color: var(--sc-ink); }
.sc-lead { margin: 0 0 16px; color: var(--sc-muted); font-size: 16px; }
.sc-pipeline { list-style: none; counter-reset: step; margin: 0; padding: 0; }
.sc-pipeline li {
  counter-increment: step; display: grid; grid-template-columns: 30px 72px 1fr; gap: 4px 10px;
  padding: 10px 0; font-size: 15px; line-height: 1.5;
}
.sc-pipeline li::before {
  content: counter(step); width: 24px; height: 24px; border-radius: 50%;
  display: grid; place-items: center; font-size: 12.5px; font-weight: 600;
  background: var(--sc-pine-tint); color: var(--sc-pine);
}
.sc-pipeline b { color: var(--sc-ink); font-weight: 600; }
.sc-note { margin: 10px 0 0; font-size: 14.5px; color: var(--sc-muted); }
.sc-points { margin: 0; padding-left: 18px; font-size: 15px; line-height: 1.6; }
.sc-points li + li { margin-top: 6px; }
.sc-tags { list-style: none; display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 0; padding: 0; }
.sc-tags li {
  font-size: 13.5px; padding: 4px 11px; border-radius: 999px;
  background: var(--sc-surface); color: var(--sc-ink-2);
}

/* ---------- message box ---------- */
#sc-contact {
  margin-top: 48px; padding-top: 32px; border-top: 1px solid var(--sc-line); gap: 10px;
}
.sc-contact-intro { text-align: center; margin-bottom: 6px; }
.sc-contact-intro h2 { margin: 0 0 4px; font-size: 24px; font-weight: 600; letter-spacing: -0.015em; color: var(--sc-ink); }
.sc-contact-intro p { margin: 0 auto; max-width: 30em; font-size: 15.5px; color: var(--sc-muted); }

#sc-kind { display: flex; justify-content: center; }
#sc-kind .wrap { gap: 6px; justify-content: center; }
#sc-kind label {
  padding: 6px 14px !important; border-radius: 999px !important; cursor: pointer;
  background: var(--sc-paper) !important; border: 1px solid var(--sc-line) !important;
  color: var(--sc-ink-2) !important; font-size: 13.5px !important; box-shadow: none !important;
}
#sc-kind label.selected, #sc-kind label:has(input:checked) {
  background: var(--sc-pine-tint) !important; border-color: var(--sc-pine) !important; color: var(--sc-pine) !important;
}
#sc-kind input { display: none; }

#sc-contact-who { gap: 10px; }
#sc-contact textarea {
  background: var(--sc-surface) !important; border: 1px solid transparent !important;
  border-radius: 12px !important; padding: 11px 14px !important; font-size: 15px !important;
  color: var(--sc-ink) !important; box-shadow: none !important;
}
#sc-contact textarea:focus { border-color: var(--sc-pine) !important; background: var(--sc-paper) !important; }
#sc-send { align-self: center; width: auto !important; min-width: 180px; border-radius: 12px !important; font-weight: 600 !important; }

.sc-status { margin: 2px 0 0; text-align: center; font-size: 14px; }
.sc-quota { margin: 0; text-align: center; font-size: 13px; color: var(--sc-muted); }
.sc-asked { margin: 14px 2px 8px; font-size: 16px; font-weight: 500; line-height: 1.45; color: var(--sc-ink); }
.sc-status-ok { color: var(--sc-pine); }
.sc-status-warn { color: var(--sc-amber); }

/* ---------- footer ---------- */
.sc-foot {
  margin-top: 40px; padding-top: 18px; border-top: 1px solid var(--sc-line);
  text-align: center; font-size: 13px; line-height: 1.55; color: var(--sc-muted);
}
.sc-foot p { margin: 0 auto 6px; max-width: 46em; }
.sc-foot b { color: var(--sc-ink-2); font-weight: 600; }
.sc-foot a { color: var(--sc-pine); text-decoration: none; }
.sc-foot a:hover { text-decoration: underline; }

@media (max-width: 640px) {
  .gradio-container { padding-top: 32px !important; }
  .sc-sub { font-size: 16px; }
  #sc-tabs .tab-container button { padding: 0 12px; font-size: 14px; }
  .sc-pipeline li { grid-template-columns: 30px 1fr; }
  .sc-pipeline li span { grid-column: 2; }
}

@media (prefers-reduced-motion: reduce) {
  .sc-spin { animation-duration: 2.4s; }
}
"""
