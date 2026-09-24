#!/usr/bin/env python3
"""config.py — shared, relocatable configuration (library module, not a CLI).
Python port of config.sh. Every other Tier 0/1 script that needs provider
resolution or the shared lock/secret-scan helpers imports this module.

Path resolution note (see blueprint §2): WORKSPACE below is computed via
os.path.abspath (logical, no symlink resolution) — matches bash's plain
`cd "$(dirname "$0")/.." && pwd`, NOT `pwd -P`. Callers doing a security
containment check should resolve() their own local copy instead of relying
on WORKSPACE being symlink-resolved.
"""
import contextlib
import os
import re
import shutil
import sys
import time
from pathlib import Path

WORKSPACE = Path(os.path.abspath(__file__)).parent.parent
BRAIN = WORKSPACE / "brain"
RAW = BRAIN / "raw"
LOG_DIR = WORKSPACE / "System_Config" / "logs"
AGENT_CONFIG = WORKSPACE / ".agentic-light.conf"

# Captured once at import time, never re-read live afterward — resolve_agent_
# provider() re-exports AGENT_TYPE (below) to the resolved provider on every
# call; reading a *live* os.environ["AGENT_TYPE"] on a later call would pick
# up that re-export and self-corrupt (mistake the previous call's resolved
# provider for a fresh user override). See blueprint §2.
_LEGACY_AGENT_TYPE_OVERRIDE = os.environ.get("AGENT_TYPE", "")

_KNOWN_PROVIDERS = ("claude", "gemini", "codex", "ollama")

# Module-level resolution state, set by resolve_agent_provider() — mirrors
# config.sh's `export AGENT_PROVIDER AGENT_COMMAND AGENT_MODEL AGENT_TYPE
# CLAUDE`. None until the first successful resolution.
AGENT_PROVIDER = None
AGENT_COMMAND = None
AGENT_MODEL = None
AGENT_TYPE = None
CLAUDE = None


def config_value(key):
    """Return the last `KEY=value` line in .agentic-light.conf, or "" if the
    file is unreadable or the key is absent. Parsed as plain text (matches
    bash's sed -n "s/^${key}=//p" | tail -1) — never evaluated as shell."""
    try:
        text = AGENT_CONFIG.read_text(encoding="utf-8")
    except OSError:
        return ""
    prefix = f"{key}="
    value = ""
    for line in text.splitlines():
        if line.startswith(prefix):
            value = line[len(prefix):]
    return value


def provider_command(provider):
    """Resolve <provider>'s executable via shutil.which — resolved ONCE here;
    callers spawn the returned absolute path directly, never a bare name
    (Windows .cmd shims need PATHEXT resolution up front, see blueprint §2)."""
    if provider == "claude":
        return shutil.which("claude")
    if provider == "gemini":
        return shutil.which("agy") or shutil.which("gemini")
    if provider == "codex":
        return shutil.which("codex")
    if provider == "ollama":
        return shutil.which("ollama")
    return None


def validate_provider_lists(enabled, priority):
    """True iff both are non-empty, comma-separated, duplicate-free lists
    drawn only from _KNOWN_PROVIDERS, and priority is an exact reordering of
    enabled (same set, either order)."""
    combined = f"{enabled},{priority}"
    if not re.match(r'^[a-z,]+$', combined):
        return False
    if combined.startswith(",") or combined.endswith(",") or ",," in combined:
        return False
    enabled_items = enabled.split(",")
    priority_items = priority.split(",")
    for item in enabled_items:
        if item not in _KNOWN_PROVIDERS or enabled_items.count(item) > 1 or item not in priority_items:
            return False
    for item in priority_items:
        if item not in _KNOWN_PROVIDERS or priority_items.count(item) > 1 or item not in enabled_items:
            return False
    return True


def resolve_agent_provider():
    """Pick the first available provider in priority order; sets the module-
    level AGENT_* / CLAUDE globals on success. Returns True/False — never
    raises, mirrors bash's `return 1` (caller decides what to do)."""
    global AGENT_PROVIDER, AGENT_COMMAND, AGENT_MODEL, AGENT_TYPE, CLAUDE

    enabled = os.environ.get("AGENTIC_LIGHT_PROVIDERS") or config_value("PROVIDERS")
    configured = os.environ.get("AGENTIC_LIGHT_PRIORITY") or config_value("PRIORITY") or enabled
    if not enabled:
        enabled = "claude,gemini,codex,ollama"
    if not configured:
        configured = "claude,gemini,codex,ollama"

    if not validate_provider_lists(enabled, configured):
        print("config.py: invalid provider configuration (priority must be an exact ordering of enabled providers)", file=sys.stderr)
        return False

    if _LEGACY_AGENT_TYPE_OVERRIDE:
        if _LEGACY_AGENT_TYPE_OVERRIDE in enabled.split(","):
            configured = f"{_LEGACY_AGENT_TYPE_OVERRIDE},{configured}"
        else:
            print(f"config.py: AGENT_TYPE is not enabled: {_LEGACY_AGENT_TYPE_OVERRIDE}", file=sys.stderr)
            return False

    for provider in configured.split(","):
        if provider not in _KNOWN_PROVIDERS:
            continue
        command = provider_command(provider)
        if command:
            AGENT_PROVIDER = provider
            AGENT_COMMAND = command
            AGENT_MODEL = os.environ.get(f"AGENTIC_LIGHT_MODEL_{provider.upper()}") or config_value(f"MODEL_{provider.upper()}") or ""
            AGENT_TYPE = provider
            CLAUDE = command
            os.environ["AGENT_TYPE"] = provider  # mirror bash's `export AGENT_TYPE` for external tooling; never read back for override logic (see _LEGACY_AGENT_TYPE_OVERRIDE note above)
            return True

    print(f"config.py: no enabled agent provider executable found ({configured})", file=sys.stderr)
    return False


def looks_like_secret(source, shaped_only=True):
    """Scan `source` (a Path/str filename, or an iterable of text lines) for
    common credential shapes. Returns a list of "N:line" matches (1-indexed,
    mirrors `grep -n`). Tight, repo-specific pattern set — not a general
    secret scanner.

    shaped_only=True (the default) checks only the high-confidence "shaped"
    patterns (sk-/ghp_/AKIA/Bearer prefixes) — safe against an arbitrary
    external target repo's ordinary source diff, where a generic
    KEY/TOKEN/SECRET-name heuristic produces real false positives (e.g.
    `apiKey: process.env.OPENAI_API_KEY` or `sortKey: "createdAt"` both
    match a bare "<word ending in KEY> [:=] 8+ chars" pattern with nothing
    resembling a real secret value). This is pipeline/run.py's pre-commit
    diff scan's mode.

    shaped_only=False additionally checks the broader KEY/TOKEN/SECRET-name
    pattern (with the placeholder/schema-field exclusions below) — intended
    for healthcheck.py's Config Security Scan (once ported, Tier 3), which
    scans a narrow, known set of this repo's OWN config files rather than
    an arbitrary external diff, where that broader heuristic's false-positive
    risk is much lower and was config.sh's original intent for that caller.

    Note on parity with config.sh: bash's version ran two separate
    `grep ... "$1"` passes over the SAME "$1" — for a real file this works,
    but silently drops the second pass's matches when "$1" is a pipe/fifo
    (e.g. /dev/stdin, the form pipeline/run.sh's secret scan used) — reading
    a pipe twice returns EOF the second time. That made the broader pattern
    a dead branch on bash's diff-scan path specifically (never actually
    evaluated), which is effectively shaped_only=True — this port makes that
    the explicit, documented default instead of an accidental one, rather
    than "fixing" it into a stricter gate with no fixture coverage.
    """
    if isinstance(source, (str, Path)):
        try:
            with open(source, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            return []
    else:
        lines = list(source)

    shaped_re = re.compile(r'(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{12,}|Bearer\s+[A-Za-z0-9._-]{10,})')
    key_secret_re = re.compile(r'[A-Z0-9_]*(KEY|TOKEN|SECRET)\s*[:=]\s*"?[A-Za-z0-9_/+=.-]{8,}"?', re.IGNORECASE)
    placeholder_re = re.compile(r'=\s*"?(null|none|changeme|your_|xxx|<.*>|\$\{)', re.IGNORECASE)
    schema_field_re = re.compile(r'(KEY|TOKEN|SECRET)_(ENUM|SCHEMA|NAME|FIELD)', re.IGNORECASE)

    hits = []
    for i, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\n")
        if shaped_re.search(line):
            hits.append(f"{i}:{line}")
            continue
        if not shaped_only and key_secret_re.search(line) and not placeholder_re.search(line) and not schema_field_re.search(line):
            hits.append(f"{i}:{line}")
    return hits


@contextlib.contextmanager
def acquire_lock(lock_dir, max_age=3600):
    """Atomic mkdir lock. A lock older than max_age seconds is assumed
    abandoned and reclaimed once (the reclaim mkdir is still atomic, so a
    genuine concurrent holder always wins the race). Yields True (lock held —
    caller must still let the `with` block exit to release it) or False
    (still held by a live run)."""
    lock_dir = Path(lock_dir)
    try:
        lock_dir.mkdir()
    except FileExistsError:
        age = time.time() - lock_dir.stat().st_mtime
        if age > max_age:
            print(f"acquire_lock: reclaiming stale lock ({age:.0f}s old, >{max_age}s): {lock_dir}", file=sys.stderr)
            lock_dir.rmdir()
            lock_dir.mkdir()
        else:
            yield False
            return
    try:
        yield True
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def date_offset(base, days, fmt):
    """<days> calendar days from `base` (YYYY-MM-DD, "" = today), rendered
    with a subset of strftime-compatible tokens (%Y-%m-%d, %G, %V, %b, %d,
    %m, %u) — the only ones config.sh's callers actually use. Python's
    datetime.strftime already handles %Y/%m/%d/%b directly; %G/%V (ISO
    week-year/week) come from date.isocalendar(), %u from isoweekday()."""
    from datetime import date, timedelta
    if base:
        y, m, d = (int(x) for x in base.split("-"))
        start = date(y, m, d)
    else:
        start = date.today()
    target = start + timedelta(days=int(days))
    iso_year, iso_week, iso_weekday = target.isocalendar()
    out = fmt
    out = out.replace("%Y-%m-%d", target.strftime("%Y-%m-%d"))
    out = out.replace("%G", f"{iso_year:04d}")
    out = out.replace("%V", f"{iso_week:02d}")
    out = out.replace("%b", target.strftime("%b"))
    out = out.replace("%d", f"{target.day:02d}")
    out = out.replace("%m", f"{target.month:02d}")
    out = out.replace("%u", str(iso_weekday))
    return out


def validate_config():
    """Sanity-check the shared config. Ported from config.sh's
    validate_config, which ran automatically as a side effect of `source
    config.sh` and never aborted anything — every caller printed its own
    warning and carried on regardless. Python has no import-time side
    effects (see module docstring), so callers that want this check call it
    explicitly; it stays warn-only here too, matching bash exactly: never
    raises, never dictates a caller's own exit code — just returns
    True/False so the caller can decide whether to print the generic
    follow-up warning."""
    for name, val in (
        ("WORKSPACE", WORKSPACE), ("BRAIN", BRAIN), ("RAW", RAW),
        ("LOG_DIR", LOG_DIR), ("AGENT_COMMAND", AGENT_COMMAND),
        ("AGENT_PROVIDER", AGENT_PROVIDER),
    ):
        if not val:
            print(f"config.py: {name} is unset/empty", file=sys.stderr)
            return False
    if not WORKSPACE.is_dir():
        print(f"config.py: WORKSPACE dir missing: {WORKSPACE}", file=sys.stderr)
        return False
    if not BRAIN.is_dir():
        print(f"config.py: warning: BRAIN dir missing: {BRAIN}", file=sys.stderr)
    return True


def week_info(today=None):
    """Monday-anchored ISO week info for `today` (a datetime.date; default
    date.today()). Returns (monday, year, week_num, week_label):
      monday     -- date object for the Monday of today's ISO week
      year       -- ISO week-year (%G, pairs with week_num/%V), zero-padded
      week_num   -- zero-padded ISO week string, e.g. "05"
      week_label -- human label, e.g. "Jul 20-24" (or "Jun 30 - Jul 4"
                    across a month edge)
    Shared by ensure_current_week_raw_folder() below and monday_init.py's
    own note/Master-Note-row math — config.sh/monday_init.sh independently
    duplicated this same calculation in two places; this port keeps ONE
    implementation. `today` is injectable so both monday_init.py's
    --self-test and any future caller can exercise edge cases (a Sunday
    anchoring back to Monday, a month-crossing label, an ISO-year rollover
    like 2025-12-29 -> 2026-W01) without depending on the real system
    clock."""
    from datetime import timedelta
    from datetime import date as _date
    if today is None:
        today = _date.today()
    dow = today.isoweekday()  # 1=Mon .. 7=Sun
    monday = today - timedelta(days=dow - 1)
    iso_year, iso_week, _unused = monday.isocalendar()
    friday = monday + timedelta(days=4)
    mon_abbr, d_start = monday.strftime("%b"), monday.day
    end_mon, d_end = friday.strftime("%b"), friday.day
    if end_mon == mon_abbr:
        week_label = f"{mon_abbr} {d_start}-{d_end}"
    else:
        week_label = f"{mon_abbr} {d_start} - {end_mon} {d_end}"
    return monday, f"{iso_year:04d}", f"{iso_week:02d}", week_label


def ensure_current_week_raw_folder():
    """mkdir -p the current ISO week's brain/raw/YYYY/Wnn label/ folder so a
    note always has somewhere to land, regardless of whether monday_init.py
    has run yet this week. Idempotent. Ported from config.sh. Returns the
    created/existing Path."""
    _monday, year, week_num, week_label = week_info()
    raw_dir = RAW / year / f"W{week_num} {week_label}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    # Library module — smoke-test only.
    ok = resolve_agent_provider()
    print(f"resolve_agent_provider(): {ok} -> provider={AGENT_PROVIDER!r} command={AGENT_COMMAND!r}")
    sys.exit(0 if ok else 1)
