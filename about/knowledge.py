"""
What the twin knows: the owner's profile and resume, read once at startup.

Like the Week 1 twin, both texts go straight into the agent's instructions.
They are small (a few thousand tokens), so the agent answers in a single model
call, with no tool round-trips that could slow it down or fail.

The files are personal, so they are NOT in the public repo. Parallax looks for them in:
  1. the folder named by PARALLAX_ME_DIR (if set)
  2. me/ next to the app (local development)
  3. /etc/secrets/ (where Render puts "Secret Files")
The resume can be a PDF (resume.pdf) or plain text (resume.md / resume.txt); hosting
dashboards that only accept text secrets can use the text version.
"""

import os
from pathlib import Path

from pypdf import PdfReader

APP_DIR = Path(__file__).resolve().parent.parent
SEARCH_DIRS = [Path(p) for p in (os.getenv("PARALLAX_ME_DIR"), APP_DIR / "me", "/etc/secrets") if p]


def _find(*names: str) -> Path | None:
    for folder in SEARCH_DIRS:
        for name in names:
            path = folder / name
            if path.is_file():
                return path
    return None


def _read_resume() -> str:
    path = _find("resume.pdf", "resume.md", "resume.txt")
    if path is None:
        print("[parallax] No resume found (looked for resume.pdf / .md / .txt)", flush=True)
        return ""
    try:
        if path.suffix == ".pdf":
            reader = PdfReader(path)
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        return path.read_text(encoding="utf-8").strip()
    except Exception as error:
        print(f"[parallax] Couldn't read {path.name}: {error}", flush=True)
        return ""


def _read_profile() -> str:
    path = _find("profile.md")
    if path is None:
        print("[parallax] No profile found (looked for profile.md)", flush=True)
        return ""
    return path.read_text(encoding="utf-8").strip()


RESUME_TEXT = _read_resume()
PROFILE_TEXT = _read_profile()
