#!/usr/bin/env python3
"""notify.py — minimal notification dispatch: Slack and/or Google Chat
webhook, plus an opt-in local macOS banner fallback. Python port of
notify.sh.

Deliberately smaller than a flag-based/severity/dedup design: Agentic
Light has no recurring scheduled jobs, so there's no repeat-alert to
suppress and nothing to dedup against.

  python3 notify.py "<title>" "<body>"

Config: System_Config/.notify.env (git-ignored, mode 600 on POSIX — on
Windows there is no permission lock; rely on per-user profile isolation),
parsed as plain KEY="value" data if present, never sourced/exec'd (same
discipline as config.py's config_value for .agentic-light.conf).
Recognized keys: SLACK_WEBHOOK_URL, GCHAT_WEBHOOK_URL,
GCHAT_FALLBACK_LOCAL (1 = also try a local macOS banner via osascript).
Both webhook vars may be set at once — each is attempted independently;
any one succeeding counts as delivered.

osascript is macOS-only; per the porting blueprint's §2, that channel is
gated behind `sys.platform == "darwin"` and no-ops (logged, not an error)
elsewhere rather than being replaced with a fabricated cross-platform
equivalent.

curl -> urllib.request (stdlib only, no third-party dependency).

Contract: never fails the caller for delivery reasons — returns 0 on any
successful delivery (a webhook 2xx or the local banner) and on a
deliberate no-config no-op; returns 1 only if delivery was attempted
somewhere and failed everywhere. Every attempt is logged to
System_Config/logs/notify.log.
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(os.path.abspath(__file__)).parent.parent
LOG_DIR = ROOT / "System_Config" / "logs"
LOG = LOG_DIR / "notify.log"
ENV_FILE = ROOT / "System_Config" / ".notify.env"

USAGE = 'Usage: python3 System_Config/notify.py "<title>" ["<body>"]'


def _load_env_file(path):
    """Parse KEY="value" / KEY=value lines as plain text data — never
    sourced/executed. Blank lines and #-comments are ignored; the last
    occurrence of a key wins (matches bash `source` semantics for a flat
    KEY=value file)."""
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[name] = value
    return values


def _log(message):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{ts} {message}\n")


def send_webhook(name, url, payload):
    """POST `payload` (a dict) as JSON to `url`. Returns True on a 2xx
    response. json.dumps handles escaping/encoding directly — notify.sh
    needed a hand-rolled `json_esc` (collapsing embedded newlines to
    spaces) only because bash has no JSON encoder; that lossy workaround
    is no longer necessary here."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=UTF-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _log(f"[fail] {name} webhook error: {exc}")
        return False
    if 200 <= code < 300:
        _log(f"[ok] {name} webhook delivered (http {code})")
        return True
    _log(f"[fail] {name} webhook http={code}")
    return False


def _applescript_escape(text):
    """Escapes backslash and double-quote only — AppleScript string
    literals recognize no other escape, so (unlike the JSON path above)
    embedded newlines/tabs pass through unchanged. Byte-parity with
    notify.sh's `applescript_esc`."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _local_macos_notification(title, body):
    """osascript is macOS-only (blueprint §2) — no-op (logged) on every
    other platform rather than substituting an unverified cross-platform
    notifier."""
    if sys.platform != "darwin":
        _log("[skip] GCHAT_FALLBACK_LOCAL=1 but the local banner channel is macOS-only (osascript) — non-macOS platform")
        return False
    osascript = shutil.which("osascript")
    if osascript is None:
        _log("[skip] GCHAT_FALLBACK_LOCAL=1 but osascript not found")
        return False
    script = 'display notification "%s" with title "%s"' % (_applescript_escape(body), _applescript_escape(title))
    try:
        subprocess.run([osascript, "-e", script], capture_output=True, encoding="utf-8", check=True)
        _log("[ok] local macOS notification delivered")
        return True
    except (subprocess.CalledProcessError, OSError) as exc:
        _log(f"[fail] local macOS notification failed: {exc}")
        return False


def notify(title, body=""):
    """Send `title`/`body` to every configured channel. Returns True iff at
    least one channel delivered, OR no channel is configured at all (a
    deliberate no-op, not a failure). Never raises for delivery reasons."""
    # bash's `[ -r "$ENV_FILE" ] && source "$ENV_FILE"` reassigns onto
    # whatever the process already inherited from its environment — an
    # exported SLACK_WEBHOOK_URL etc. is honored when the file is absent
    # or silent on that key, but a key the file DOES define (even as "")
    # overrides the inherited value, since `source` runs after the
    # environment is inherited. Seed from os.environ, then overlay.
    env = {
        "SLACK_WEBHOOK_URL": os.environ.get("SLACK_WEBHOOK_URL", ""),
        "GCHAT_WEBHOOK_URL": os.environ.get("GCHAT_WEBHOOK_URL", ""),
        "GCHAT_FALLBACK_LOCAL": os.environ.get("GCHAT_FALLBACK_LOCAL", "0"),
    }
    env.update(_load_env_file(ENV_FILE))
    payload = {"text": f"*{title}*\n{body}"}

    attempted = False
    delivered = False

    slack_url = env.get("SLACK_WEBHOOK_URL", "")
    if slack_url:
        attempted = True
        if send_webhook("Slack", slack_url, payload):
            delivered = True

    gchat_url = env.get("GCHAT_WEBHOOK_URL", "")
    if gchat_url:
        attempted = True
        if send_webhook("Google Chat", gchat_url, payload):
            delivered = True

    if env.get("GCHAT_FALLBACK_LOCAL", "0") == "1":
        attempted = True
        if _local_macos_notification(title, body):
            delivered = True

    if not attempted:
        _log("[noop] no channel configured (SLACK_WEBHOOK_URL / GCHAT_WEBHOOK_URL / GCHAT_FALLBACK_LOCAL all unset)")
        return True

    return delivered


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(USAGE, file=sys.stderr)
        return 1
    title = argv[0]
    body = argv[1] if len(argv) > 1 else ""
    return 0 if notify(title, body) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
