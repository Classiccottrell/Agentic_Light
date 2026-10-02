#!/usr/bin/env python3
"""identity.py — the fork's display name and slug, read from
System_Config/identity.json (library module, not a CLI).

The one place runtime code gets the harness identity from: run.py's branch
prefix, commit prefix and banner, pr_create.py's default PR title/body, the
gate scripts' manual references, specialize.py's banner, gen_governance.py,
and config.py's `.<slug>.conf` filename. White-labeling edits identity.json;
the code reading it stays untouched.

A standalone module rather than part of config.py: pipeline/lib/*.py run as
separate processes and only need this — no provider resolution, no locks.
Stdlib only, no import-time side effects; load_identity() reads the file on
every call (it is tiny), so a test can swap the file between runs.
"""
import json
import re
import unicodedata
from pathlib import Path

IDENTITY_FILE = Path(__file__).resolve().parent / "identity.json"
DEFAULT_IDENTITY = {"name": "Agentic Light", "slug": "agentic-light"}
# Lowercase alphanumeric runs joined by single hyphens: safe as a git branch
# prefix (no leading "-", no "..", no "/", no ".lock" suffix possible) and as
# a dotfile name (.<slug>.conf).
SLUG_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")  # used with fullmatch(): "$" alone would admit a trailing "\n"
SLUG_MAX = 64


class IdentityError(ValueError):
    """identity.json exists but is unusable. The message names the file."""


def load_identity(path=None):
    """Return {"name": str, "slug": str}. A missing file yields the defaults;
    an unreadable, malformed or invalid file raises IdentityError."""
    path = Path(path) if path else IDENTITY_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return dict(DEFAULT_IDENTITY)
    except UnicodeDecodeError as e:
        raise IdentityError(f"{path}: not valid UTF-8: {e}") from e
    except OSError as e:
        raise IdentityError(f"{path}: unreadable: {e}") from e
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise IdentityError(f"{path}: not valid JSON: {e}") from e
    if not isinstance(data, dict) or set(data) != {"name", "slug"}:
        raise IdentityError(f'{path}: must be a JSON object with exactly the keys "name" and "slug"')
    name, slug = data["name"], data["slug"]
    # Category C* covers control, format (incl. bidi overrides/isolates U+202A-
    # U+202E, U+2066-U+2069), and unassigned code points; Zl/Zp are the
    # Unicode line/paragraph separators. U+0085 is Cc.
    if not isinstance(name, str) or not name.strip() or name != name.strip() \
            or any(unicodedata.category(c)[0] == "C" or unicodedata.category(c) in ("Zl", "Zp") for c in name):
        raise IdentityError(f"{path}: name {name!r} must be a non-empty single-line string with no "
                            "leading/trailing whitespace, control, format/bidi, or line-separator characters")
    if not isinstance(slug, str) or len(slug) > SLUG_MAX or not SLUG_RE.fullmatch(slug):
        raise IdentityError(f"{path}: slug {slug!r} must be at most {SLUG_MAX} lowercase letters/digits in "
                            "hyphen-separated runs (e.g. \"northwind-harness\")")
    return {"name": name, "slug": slug}
