#!/usr/bin/env python3
"""bootstrap.py — one-command setup for Agentic Light. Python port of
bootstrap.sh.

Operates IN PLACE at the location you cloned to. Idempotent and safe:
never deletes or overwrites your data. Re-run it any time.

  python3 bootstrap.py

Deviation from bootstrap.sh (per the porting blueprint's §2, intentional):
the "make scripts executable" step is dropped entirely. Windows has no
execute bit / shebang dispatch, and every script here is now invoked as
`python script.py` (or `py -3 script.py`), never run directly — chmod +x
has nothing left to do.

Flag handling deliberately does NOT use argparse (a documented deviation
from this port's usual argparse-for-any-flag baseline, same justification
new_agent.py already gives for its own deviation): bootstrap.sh's case
statement silently falls through to the normal interactive setup for
EITHER no argument OR any bare non-flag positional, and only errors on an
unrecognized `--flag`. argparse's own default handling of an unexpected
positional (reject it) doesn't reproduce that fall-through without real
contortion, so this stays a plain `sys.argv[1:]` dispatch, matching
bootstrap.sh's exact case-statement semantics including that quirk.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.path.abspath(__file__)).parent
SYSCFG = ROOT / "System_Config"

sys.path.insert(0, str(SYSCFG))
import config  # noqa: E402  config_value(), validate_provider_lists()

PROVIDERS_ALL = ("claude", "gemini", "codex", "ollama")

HELP_TEXT = """Usage: python3 bootstrap.py [--check|--check-deps|--uninstall|--help]
  (no args)    run the interactive setup
  --check      read-only doctor: report tool status
  --check-deps alias for --check
  --uninstall  explain there is no background automation to remove"""


def _atomic_write_text(path, text, mode=None):
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    if mode is not None:
        os.chmod(path, mode)


def _ask_raw(prompt):
    """print(prompt) with no trailing newline, then read one line. EOF on
    stdin (`read -r || reply=""` in bash) reads as an empty reply."""
    print(prompt, end="")
    sys.stdout.flush()
    try:
        return input()
    except EOFError:
        return ""


def _ask_yes_no(prompt, default_yes):
    """`${reply:-$default}` then a case-sensitive y/Y/yes/YES match — an
    empty reply falls back to `default_yes`'s literal Y/N, which is itself
    then matched against the same accept set (so default_yes=False can
    never accept). Matches bash's exact case-sensitivity: "No" (mixed
    case) is NOT a decline for a [Y/n] prompt, it falls through to accept."""
    reply = _ask_raw(prompt).strip()
    if not reply:
        reply = "Y" if default_yes else "N"
    return reply in ("y", "Y", "yes", "YES")


def cmd_check():
    print("=" * 50)
    print(" Agentic Light — check")
    print("=" * 50)
    print()
    print("→ Tools:")
    for t in ("claude", "agy", "gemini", "codex", "ollama", "gh", "node", "npx", "python3"):
        p = shutil.which(t)
        if p:
            print(f"  [ok] {t} {p}")
            if t == "gh":
                proc = subprocess.run(["gh", "auth", "status"], capture_output=True, encoding="utf-8")
                if proc.returncode == 0:
                    print("       gh auth status: ok")
                else:
                    print("       gh auth status: unauthenticated")
        else:
            print(f"  [--] {t} missing")

    conf = ROOT / ".agentic-light.conf"
    if conf.is_file():
        print()
        print("→ Provider config:")
        providers = config.config_value("PROVIDERS")
        priority = config.config_value("PRIORITY")
        if providers:
            print(f"  enabled: {providers}")
        if priority:
            print(f"  priority: {priority}")
    else:
        print()
        print("→ Provider config: not created (run python3 bootstrap.py)")

    print()
    print("→ Automation:")
    print("  No background automation (Agentic Light is manual-trigger only).")
    return 0


def cmd_uninstall():
    print("=" * 50)
    print(" Agentic Light — uninstall")
    print("=" * 50)
    print()
    print("Agentic Light has no background automation to remove; delete the")
    print("Agentic_Light/ folder to uninstall.")
    print()
    if not sys.stdin.isatty():
        print("Non-interactive session — nothing to confirm, exiting.")
        return 0
    reply = _ask_raw("Acknowledge? [y/N]: ").strip()
    if reply in ("y", "Y", "yes", "YES"):
        print("→ Nothing removed (no automation installed). Delete Agentic_Light/ manually to uninstall.")
    else:
        print("→ Aborted. No changes made.")
    return 0


def _scaffold_directories():
    print("→ Scaffolding directory tree…")
    for d in (
        ".obsidian",
        "Projects/_TEMPLATE/active",
        "Projects/_TEMPLATE/archive",
        "System_Config/logs",
        "microsite",
        "brain/raw",
        "brain/wiki",
        "brain/weekly_logs/2026",
        "pipeline/logs",
        "pipeline/lib",
    ):
        (ROOT / d).mkdir(parents=True, exist_ok=True)


def _seed_mcp_json():
    mcp = ROOT / ".mcp.json"
    defaults = SYSCFG / "mcp.defaults.json"
    if not mcp.is_file() and defaults.is_file():
        shutil.copy(defaults, mcp)
        print("→ Created .mcp.json from System_Config/mcp.defaults.json.")
    elif mcp.is_file():
        print("→ .mcp.json already present — leaving it untouched.")
    print()


def _configure_providers():
    print("→ Configuring agent providers…")
    providers = os.environ.get("AGENTIC_LIGHT_PROVIDERS", "")
    priority = os.environ.get("AGENTIC_LIGHT_PRIORITY", "")
    model_overrides = {}

    if not providers and sys.stdin.isatty():
        enabled_list = []
        for provider in PROVIDERS_ALL:
            binary = provider
            if provider == "gemini" and shutil.which("agy"):
                binary = "agy"
            found = shutil.which(binary) is not None
            mark = "x" if found else " "
            default_label = "Y" if found else "N"
            if _ask_yes_no(f"  [{mark}] Enable {provider}? [{default_label}]: ", found):
                enabled_list.append(provider)
        providers = ",".join(enabled_list)
        priority = _ask_raw(f"  Priority, comma-separated [{providers}]: ").strip() or providers
        for provider in providers.split(",") if providers else []:
            model_overrides[provider] = _ask_raw(f"  Optional {provider} model [default]: ").strip()
    else:
        providers = providers or os.environ.get("AGENT_TYPE", "") or "claude,gemini,codex,ollama"
        priority = priority or providers

    if not config.validate_provider_lists(providers, priority):
        print("Invalid provider lists: priority must be an exact ordering of enabled providers.", file=sys.stderr)
        return 1

    lines = [f"PROVIDERS={providers}", f"PRIORITY={priority}"]
    for provider in PROVIDERS_ALL:
        env_key = f"AGENTIC_LIGHT_MODEL_{provider.upper()}"
        model = os.environ.get(env_key) or model_overrides.get(provider, "")
        if "\n" in model or "=" in model:
            print("Invalid model name.", file=sys.stderr)
            return 1
        lines.append(f"MODEL_{provider.upper()}={model}")
    _atomic_write_text(ROOT / ".agentic-light.conf", "\n".join(lines) + "\n", mode=0o600)
    print(f"    [ok] Enabled: {providers}")
    print(f"    [ok] Priority: {priority}")

    gh = shutil.which("gh")
    if gh:
        print(f"    [ok] gh found: {gh}")
        proc = subprocess.run(["gh", "auth", "status"], capture_output=True, encoding="utf-8")
        if proc.returncode != 0:
            print("         not authenticated — run: gh auth login")
    else:
        print("    [opt] gh not found — needed by pipeline/run.py for PR creation.")
    print()
    return 0


def _set_notify_key(path, template_path, key, value):
    """Idempotent replace-else-append, mode 600. Plain string formatting
    (not sed) — notify.sh needed careful backslash/&/pipe escaping only
    because sed's replacement side treats those characters specially
    (e.g. a webhook URL's own `?key=...&token=...` query string); that
    whole class of escaping bug is structurally impossible here."""
    if not path.is_file():
        seed = template_path.read_text(encoding="utf-8") if template_path.is_file() else ""
        _atomic_write_text(path, seed, mode=0o600)
    lines = path.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    replaced = False
    new_lines = []
    for line in lines:
        if line.startswith(prefix):
            new_lines.append(f'{key}="{value}"')
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f'{key}="{value}"')
    _atomic_write_text(path, "\n".join(new_lines) + "\n", mode=0o600)


def _configure_notifications():
    print("→ Notifications (optional) — desktop banner on healthcheck problems, plus optional webhook.")
    notify_env = SYSCFG / ".notify.env"
    notify_env_example = SYSCFG / ".notify.env.example"

    if not sys.stdin.isatty():
        print("  Non-interactive session — skipped. Configure later by editing System_Config/.notify.env.")
        return

    if _ask_yes_no("  Enable Slack webhook?        [y/N]: ", False):
        url = _ask_raw("    Slack webhook URL (blank = skip): ").strip()
        if url.startswith("https://"):
            _set_notify_key(notify_env, notify_env_example, "SLACK_WEBHOOK_URL", url)
            print("    [ok] Slack webhook saved.")
        elif url == "":
            print("    [--] blank — skipped.")
        else:
            print("    [!!] must start with https:// — skipped.")

    if _ask_yes_no("  Enable Google Chat webhook?  [y/N]: ", False):
        url = _ask_raw("    Google Chat webhook URL (blank = skip): ").strip()
        if url.startswith("https://"):
            _set_notify_key(notify_env, notify_env_example, "GCHAT_WEBHOOK_URL", url)
            print("    [ok] Google Chat webhook saved.")
        elif url == "":
            print("    [--] blank — skipped.")
        else:
            print("    [!!] must start with https:// — skipped.")


def cmd_setup():
    print("=" * 50)
    print(" Agentic Light — bootstrap")
    print(f" Workspace: {ROOT}")
    print("=" * 50)
    print()

    _scaffold_directories()
    _seed_mcp_json()

    rc = _configure_providers()
    if rc != 0:
        return rc

    _configure_notifications()

    print()
    print("=" * 50)
    print(" Done. Next steps:")
    print("=" * 50)
    print(" 1. (Optional) Open Agentic_Light/ in Obsidian (the folder containing")
    print("    .obsidian/) for graph view/backlinks — the context layer itself is")
    print("    plain markdown + SQLite and works with any editor or agent.")
    print(" 2. Run python3 Agentic_Light/System_Config/healthcheck.py")
    print(' 3. Run python3 Agentic_Light/System_Config/notify.py "title" "body" to test notifications.')
    print()
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    arg = argv[0] if argv else ""

    if arg == "--help":
        print(HELP_TEXT)
        return 0
    if arg in ("--check", "--check-deps"):
        return cmd_check()
    if arg == "--uninstall":
        return cmd_uninstall()
    if arg.startswith("--"):
        print(f"Unknown flag: {arg}")
        print(HELP_TEXT)
        return 1

    # Empty arg or a bare non-flag positional both fall through to the
    # normal interactive setup — bootstrap.sh's case statement has no
    # catch-all for a non-"--"-prefixed argument either, so it's silently
    # ignored there too; preserved here rather than "fixed" into an error.
    return cmd_setup()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
