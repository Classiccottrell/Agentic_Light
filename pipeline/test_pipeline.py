#!/usr/bin/env python3
"""test_pipeline.py — fixture tests for pipeline/run.py and its lib/
scripts. Python port of test_pipeline.sh. Pattern mirrors
System_Config/test_providers.py: a shared check(label, cond, detail)
accumulator, tempfile scratch dirs, cleanup in a finally block.

Every fixture invokes the real pipeline/run.py as a subprocess (matching
bash's own `bash "$RUN" ...` — this integration test exercises the real
CLI contract end to end, not the internal functions directly).

Simplification vs. the bash original: config.py never reads $HOME (the
PATH-reset that referenced $HOME/.local/bin was deliberately dropped when
porting config.sh, see config.py's module docstring), so fake `gh`/`claude`
binaries only need a plain PATH prepend here — no $HOME juggling.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(os.path.abspath(__file__)).parent.parent
RUN = ROOT / "pipeline" / "run.py"
LIB = ROOT / "pipeline" / "lib"
GIT = shutil.which("git")

sys.path.insert(0, str(ROOT / "System_Config"))
from test_support import rmtree_force  # noqa: E402

_FAILURES = []


def check(label, cond, detail=""):
    if not cond:
        _FAILURES.append(f"{label}: {detail}")
        print(f"  [FAIL] {label}: {detail}", file=sys.stderr)


BASE_ENV = dict(os.environ)
BASE_ENV.update({
    "GIT_AUTHOR_NAME": "Agentic Light Test", "GIT_AUTHOR_EMAIL": "test@agentic.light",
    "GIT_COMMITTER_NAME": "Agentic Light Test", "GIT_COMMITTER_EMAIL": "test@agentic.light",
})

TMP_ROOT = Path(tempfile.mkdtemp(prefix="agentic-light-pipeline-test."))
FAKE_BIN = TMP_ROOT / "fakebin"
FAKE_BIN.mkdir()
CALLS = TMP_ROOT / "gh_calls"
CALLS9 = TMP_ROOT / "claude_calls"
LOG_SESSION_NOTE = TMP_ROOT / "weekly-note.md"
LOG_SESSION_NOTE.write_text("", encoding="utf-8")

REAL_GATE_CONFIG = ROOT / "pipeline" / "gate-config.json"
GATE_CONFIG_BACKUP = TMP_ROOT / "gate-config.json.bak"
GATE_CONFIG_TOUCHED = [False]

REAL_ROSTER = ROOT / "System_Config" / "agent-roster.json"
ROSTER_BACKUP = TMP_ROOT / "agent-roster.json.bak"
ROSTER_TOUCHED = [False]

# Session records: every run is pointed at a temp dir (test-mode override);
# the real brain/records/ is snapshotted and asserted unchanged at the end.
SESSIONS_DIR = TMP_ROOT / "sessions"
REAL_RECORDS = ROOT / "brain" / "records"


def records_snapshot():
    return sorted((str(p), p.stat().st_mtime_ns) for p in REAL_RECORDS.rglob("*") if p.is_file()) if REAL_RECORDS.is_dir() else []


PRE_RECORDS = records_snapshot()

PRE_LOGS = set((ROOT / "pipeline" / "logs").glob("*.log")) | set((ROOT / "pipeline" / "logs").glob("*.events.jsonl"))


def write_fake(path, body):
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# gh and claude are resolved by BARE NAME via shutil.which() (pr_create.py,
# config.provider_command()) — unlike the .py stubs above (always dispatched
# as [sys.executable, path, ...], so their own shebang/executable bit is
# irrelevant), these two must be genuinely PATH-discoverable: a POSIX
# executable with a real shebang, plus a same-named .cmd wrapper so
# shutil.which() finds it via PATHEXT on Windows too (blueprint §3). The
# shebang embeds sys.executable directly rather than `#!/usr/bin/env
# python3` — robust regardless of what "python3" resolves to (or whether it
# exists at all) on PATH.
def write_path_fake(name, body):
    path = FAKE_BIN / name
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"#!{sys.executable}\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    with open(FAKE_BIN / f"{name}.cmd", "w", encoding="utf-8", newline="") as f:
        f.write(f'@echo off\r\n"{sys.executable}" "%~dp0{name}" %*\r\n')


# Fake gh: logs its full argv to $CALLS, always exits 0.
write_path_fake("gh", "import os, sys\n"
                 "with open(os.environ['CALLS'], 'a', encoding='utf-8') as f:\n"
                 "    f.write('gh ' + ' '.join(sys.argv[1:]) + chr(10))\n"
                 "sys.exit(0)\n")

# Fake claude: logs its full argv (including -p prompt) to $CALLS9 — fixture
# 9 inspects what the real run_agent path actually sent (PIPELINE_CODER_CMD
# bypasses the prompt entirely, so this is the only way to exercise the
# context-packet/skill prepend). Always exits 0.
write_path_fake("claude", "import os, sys\n"
                 "with open(os.environ['CALLS9'], 'a', encoding='utf-8') as f:\n"
                 "    f.write(' '.join(sys.argv[1:]) + chr(10))\n"
                 "sys.exit(0)\n")

# coder stub: modifies a tracked file (seed.txt, exercises `git diff HEAD`)
# and adds an untracked one (PATCHED.txt) so both halves of run.py's
# diff-capture logic are covered.
CODER_STUB = TMP_ROOT / "coder_stub.py"
write_fake(CODER_STUB, "import sys\n"
           "task, target = sys.argv[1], sys.argv[2]\n"
           "with open(target + '/seed.txt', 'a', encoding='utf-8') as f:\n"
           "    f.write('modified\\n')\n"
           "with open(target + '/PATCHED.txt', 'w', encoding='utf-8') as f:\n"
           "    f.write('patched by test\\n')\n")

# no-op coder stub: for the "coder made no changes" fixture.
NOOP_CODER_STUB = TMP_ROOT / "noop_coder_stub.py"
write_fake(NOOP_CODER_STUB, "pass\n")

# human-gate stub: always approves. Exercises the pass-through path without
# faking a TTY.
APPROVE_STUB = TMP_ROOT / "approve_stub.py"
write_fake(APPROVE_STUB, "import sys\n"
           "print('[approve_stub] auto-approving:', sys.argv[1] if len(sys.argv) > 1 else '')\n"
           "sys.exit(0)\n")

# secret coder stub: adds a line shaped like a real credential (ghp_ + 20
# chars) — must hard-stop the secret scan.
SECRET_CODER_STUB = TMP_ROOT / "secret_coder_stub.py"
write_fake(SECRET_CODER_STUB, "import sys\n"
           "target = sys.argv[2]\n"
           "with open(target + '/config.js', 'w', encoding='utf-8') as f:\n"
           "    f.write('const token = \\'ghp_abcdefghijklmnopqrstuvwx\\';\\n')\n")

# benign coder stub: adds ordinary KEY-named lines that are NOT secrets
# (an object property name, an env-var reference) — must NOT trip the
# secret scan (see config.looks_like_secret's shaped_only=True default and
# its docstring on why the broader KEY/TOKEN/SECRET heuristic is unsafe on
# an arbitrary external diff).
BENIGN_CODER_STUB = TMP_ROOT / "benign_coder_stub.py"
write_fake(BENIGN_CODER_STUB, "import sys\n"
           "target = sys.argv[2]\n"
           "with open(target + '/config.js', 'w', encoding='utf-8') as f:\n"
           "    f.write('const query = { sortKey: \\'createdAt\\' };\\n')\n"
           "    f.write('const apiKey = process.env.OPENAI_API_KEY;\\n')\n")


def new_target_repo(name):
    d = TMP_ROOT / name
    d.mkdir(parents=True)
    subprocess.run([GIT, "init", "-q", "-b", "main"], cwd=str(d), check=True, env=BASE_ENV, encoding="utf-8")
    (d / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run([GIT, "-C", str(d), "add", "seed.txt"], check=True, env=BASE_ENV, encoding="utf-8")
    subprocess.run([GIT, "-C", str(d), "commit", "-q", "-m", "seed"], check=True, env=BASE_ENV, encoding="utf-8")
    return d


def git_current_branch(repo):
    proc = subprocess.run([GIT, "-C", str(repo), "branch", "--show-current"], capture_output=True, encoding="utf-8")
    return proc.stdout.strip()


def git_log_count(repo, range_spec):
    proc = subprocess.run([GIT, "-C", str(repo), "log", "--oneline", range_spec], capture_output=True, encoding="utf-8")
    return len([l for l in proc.stdout.splitlines() if l.strip()])


def run_pipeline(task, target_repo, coder_cmd=CODER_STUB, human_gate_cmd=None, extra_env=None, stdin=None,
                 end_of_options=False):
    env = dict(BASE_ENV)
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env.get('PATH', '')}"
    env["CALLS"] = str(CALLS)
    env["AGENTIC_LIGHT_TEST_MODE"] = "1"
    env["LOG_SESSION_NOTE"] = str(LOG_SESSION_NOTE)
    env["AGENTIC_LIGHT_SESSIONS_DIR"] = str(SESSIONS_DIR)
    env["PYTHONUTF8"] = "1"
    if coder_cmd is not None:
        env["PIPELINE_CODER_CMD"] = str(coder_cmd)
    if human_gate_cmd is not None:
        env["PIPELINE_HUMAN_GATE_CMD"] = str(human_gate_cmd)
    if extra_env:
        env.update(extra_env)
    # end_of_options: a task like '---' would otherwise parse as an option.
    return subprocess.run([sys.executable, str(RUN)] + (["--"] if end_of_options else []) + [task, str(target_repo)],
                           capture_output=True, encoding="utf-8", errors="replace",
                           env=env, stdin=stdin)


def reset_calls():
    CALLS.write_text("", encoding="utf-8")


def calls_nonempty():
    return CALLS.exists() and CALLS.stat().st_size > 0


def set_gate_config(gates):
    if REAL_GATE_CONFIG.is_file() and not GATE_CONFIG_TOUCHED[0]:
        shutil.copy(REAL_GATE_CONFIG, GATE_CONFIG_BACKUP)
    GATE_CONFIG_TOUCHED[0] = True
    REAL_GATE_CONFIG.write_text(json.dumps({"gates": gates}), encoding="utf-8")


def restore_gate_config():
    if not GATE_CONFIG_TOUCHED[0]:
        return
    if GATE_CONFIG_BACKUP.is_file():
        shutil.move(str(GATE_CONFIG_BACKUP), str(REAL_GATE_CONFIG))
    else:
        REAL_GATE_CONFIG.unlink(missing_ok=True)
    GATE_CONFIG_TOUCHED[0] = False


def set_roster(roles):
    if REAL_ROSTER.is_file() and not ROSTER_TOUCHED[0]:
        shutil.copy(REAL_ROSTER, ROSTER_BACKUP)
    ROSTER_TOUCHED[0] = True
    REAL_ROSTER.write_text(json.dumps({"roles": roles}), encoding="utf-8")


def restore_roster():
    if not ROSTER_TOUCHED[0]:
        return
    if ROSTER_BACKUP.is_file():
        shutil.move(str(ROSTER_BACKUP), str(REAL_ROSTER))
    else:
        REAL_ROSTER.unlink(missing_ok=True)
    ROSTER_TOUCHED[0] = False


def cleanup():
    restore_gate_config()
    restore_roster()
    try:
        rmtree_force(TMP_ROOT)
    except OSError:
        pass
    logs = ROOT / "pipeline" / "logs"
    for f in list(logs.glob("*.log")) + list(logs.glob("*.events.jsonl")):
        if f not in PRE_LOGS:
            f.unlink()


def run_direct(repo, extra_env=None, task="task"):
    """Drive the REAL run_agent.py path against the fake `claude` (argv ->
    $CALLS9) instead of PIPELINE_CODER_CMD, so the assembled prompt and the
    provider capability check are both exercised."""
    env = dict(BASE_ENV)
    env.pop("AGENT_TYPE", None)
    env.pop("PIPELINE_CODER_CMD", None)
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env.get('PATH', '')}"
    env["CALLS9"] = str(CALLS9)
    env["MAX_SECONDS"] = "3"
    env["AGENTIC_LIGHT_PROVIDERS"] = "claude"
    env["AGENTIC_LIGHT_PRIORITY"] = "claude"
    env["AGENTIC_LIGHT_TEST_MODE"] = "1"
    env["PIPELINE_HUMAN_GATE_CMD"] = str(APPROVE_STUB)
    env["LOG_SESSION_NOTE"] = str(LOG_SESSION_NOTE)
    env["AGENTIC_LIGHT_SESSIONS_DIR"] = str(SESSIONS_DIR)
    env["PYTHONUTF8"] = "1"
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(RUN), task, str(repo)],
                           capture_output=True, encoding="utf-8", errors="replace", env=env)


def read_events(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def add_package_json(repo, scripts):
    (repo / "package.json").write_text(json.dumps({"scripts": scripts}), encoding="utf-8")
    subprocess.run([GIT, "-C", str(repo), "add", "package.json"], check=True, env=BASE_ENV, encoding="utf-8")
    subprocess.run([GIT, "-C", str(repo), "commit", "-q", "-m", "add package.json"], check=True, env=BASE_ENV, encoding="utf-8")


def write_vpat_draft(repo, mutate=None):
    draft = {
        "schema_version": "1.0",
        "product": {"name": "Example App", "version": "1.0.0"},
        "report": {"title": "Example App Accessibility Conformance Report", "version": "2.5Rev", "date": "2026-09-22"},
        "evaluation_methods": ["axe-core automated scan", "manual keyboard pass"],
        "criteria": [
            {
                "id": "1.4.3", "name": "Contrast (Minimum)", "level": "AA",
                "rating": "Partially Supports",
                "remarks": ("Most text meets the required ratio. What: placeholder text renders at 3.2:1 "
                            "contrast, below the 4.5:1 minimum. Who: low-vision users reading affected "
                            "paragraphs. Where: article body text on the blog pages."),
                "evidence": "automated",
            },
            {
                "id": "4.1.2", "name": "Name, Role, Value", "level": "A",
                "rating": "Supports",
                "remarks": ("Evidence: manual screen-reader pass (NVDA + Chrome) confirmed every interactive "
                            "control exposes an accessible name, role, and state. Evaluated scope: all "
                            "interactive components across the app."),
            },
            {
                "id": "2.1.1", "name": "Keyboard", "level": "A",
                "rating": "Not Applicable",
                "remarks": "Why: this build ships no interactive controls beyond native form elements already covered by 4.1.2.",
            },
        ],
        "limitations": [
            "This document is not an automated accessibility audit, certification, legal opinion, or "
            "guarantee of conformance to WCAG, Section 508, EN 301 549, or any other standard. It does "
            "not replace manual testing, qualified accessibility review, current ITI VPAT instructions, "
            "or legal advice."
        ],
    }
    if mutate:
        mutate(draft)
    a11y_dir = repo / "accessibility"
    a11y_dir.mkdir(exist_ok=True)
    (a11y_dir / "vpat-draft.json").write_text(json.dumps(draft), encoding="utf-8")
    subprocess.run([GIT, "-C", str(repo), "add", "accessibility/vpat-draft.json"], check=True, env=BASE_ENV, encoding="utf-8")
    subprocess.run([GIT, "-C", str(repo), "commit", "-q", "-m", "add vpat draft"], check=True, env=BASE_ENV, encoding="utf-8")


def fixture_1():
    repo1 = new_target_repo("repo1")
    reset_calls()
    proc = run_pipeline("add a widget", repo1, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture1: code patch step complete", "code patch step complete" in out, out)
    check("fixture1: human gate approved", "human gate: APPROVED" in out)
    check("fixture1: pipeline complete", "Pipeline complete" in out)
    check("fixture1: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture1: gh pr create called", calls_nonempty() and any(l.startswith("gh pr create") for l in CALLS.read_text(encoding="utf-8").splitlines()))
    check("fixture1: branch prefixed agentic-light/", git_current_branch(repo1).startswith("agentic-light/"), git_current_branch(repo1))
    check("fixture1: at least one commit ahead of main", git_log_count(repo1, "main..") >= 1)
    check("fixture1: summary shows seed.txt", "seed.txt" in out)
    check("fixture1: summary shows PATCHED.txt", "PATCHED.txt" in out)
    note_text = LOG_SESSION_NOTE.read_text(encoding="utf-8")
    check("fixture1: session logged exactly once", note_text.count("/ coder — exit 0 (exit)") == 1, note_text)
    check("fixture1: no roster -> no roster check line", "Roster check" not in out, out)
    print("fixture 1 (normal pass): PASS")


def fixture_1b():
    repo1b = new_target_repo("repo1b")
    reset_calls()
    proc = run_pipeline("no-op task", repo1b, coder_cmd=NOOP_CODER_STUB, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture1b: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture1b: produced no changes message", "produced no changes" in out, out)
    check("fixture1b: gh never called", not calls_nonempty())
    print("fixture 1b (coder produces no changes): PASS")


def fixture_1c():
    # Secret scan: a shaped credential (ghp_...) must hard-stop, index left
    # clean, no PR. Regression coverage for the false-negative half of the
    # secret-scan contract.
    repo1c = new_target_repo("repo1c")
    reset_calls()
    proc = run_pipeline("add config", repo1c, coder_cmd=SECRET_CODER_STUB, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture1c: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture1c: secret detected message", "likely secret detected" in out, out)
    check("fixture1c: gh never called", not calls_nonempty())
    staged = subprocess.run([GIT, "-C", str(repo1c), "diff", "--cached", "--quiet"], encoding="utf-8")
    check("fixture1c: index left clean after reset", staged.returncode == 0, staged.returncode)
    print("fixture 1c (secret scan blocks a shaped credential): PASS")


def fixture_1d():
    # Secret scan: ordinary KEY-named lines with no real secret value must
    # NOT be blocked — regression coverage for the false-positive half (see
    # config.looks_like_secret's shaped_only=True default).
    repo1d = new_target_repo("repo1d")
    reset_calls()
    proc = run_pipeline("add config", repo1d, coder_cmd=BENIGN_CODER_STUB, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture1d: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture1d: no false-positive secret block", "likely secret detected" not in out, out)
    check("fixture1d: gh pr create called", any(l.startswith("gh pr create") for l in CALLS.read_text(encoding="utf-8").splitlines()))
    print("fixture 1d (benign KEY-named lines are not blocked): PASS")


def fixture_2():
    repo2 = new_target_repo("repo2")
    add_package_json(repo2, {"lint": "exit 1"})
    reset_calls()
    proc = run_pipeline("task", repo2, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture2: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture2: FAILED ESLint gate", "FAILED: ESLint gate" in out, out)
    check("fixture2: gh never called", not calls_nonempty())
    print("fixture 2 (ESLint gate failure): PASS")


def fixture_3():
    repo3 = new_target_repo("repo3")
    add_package_json(repo3, {"test:e2e": "exit 1"})
    reset_calls()
    proc = run_pipeline("task", repo3, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture3: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture3: FAILED Playwright gate", "FAILED: Playwright gate" in out, out)
    check("fixture3: gh never called", not calls_nonempty())
    print("fixture 3 (Playwright gate failure): PASS")


def fixture_4():
    repo4 = new_target_repo("repo4")
    reset_calls()
    proc = run_pipeline("task", repo4, human_gate_cmd=None, stdin=subprocess.DEVNULL)
    out = proc.stdout + proc.stderr
    check("fixture4: rc == 2", proc.returncode == 2, proc.returncode)
    check("fixture4: pending message", "PENDING: human gate awaiting interactive review" in out, out)
    check("fixture4: gh never called", not calls_nonempty())
    print("fixture 4 (no-TTY pending): PASS")


def fixture_5():
    # 5a: human_gate.decide() called directly with fakes — no real pty
    # needed for these branches (blueprint §2: the injectable is_tty flag +
    # reader exist precisely so this coverage doesn't depend on a POSIX
    # pty). Import via LIB on sys.path rather than a package-relative
    # import — pipeline/lib has no __init__.py.
    sys.path.insert(0, str(LIB))
    import human_gate
    check("fixture5a: non-tty -> 2 (no reader call)", human_gate.decide(False, lambda: (_ for _ in ()).throw(AssertionError("reader must not be called when is_tty is False"))) == 2)
    check("fixture5a: tty + 'n' -> 1 (declined)", human_gate.decide(True, lambda: "n") == 1)
    check("fixture5a: tty + 'y' -> 0 (approved)", human_gate.decide(True, lambda: "y") == 0)

    def _raise_eof():
        raise EOFError()
    check("fixture5a: tty + EOFError reader -> 1 (declined)", human_gate.decide(True, _raise_eof) == 1)
    print("fixture 5a (human_gate.decide() direct, injectable is_tty/reader): PASS")

    # 5b: real pty end-to-end, POSIX-only fallback per blueprint §2's
    # explicit-SKIP guidance for platforms without one.
    try:
        import pty
    except ImportError:
        print("fixture 5b (declined human gate via pty): SKIP (no pty on this platform)")
        return
    master, slave = pty.openpty()
    env = {**BASE_ENV, "PYTHONUTF8": "1"}
    proc = subprocess.Popen([sys.executable, str(LIB / "human_gate.py"), "declined-fixture summary"],
                             stdin=slave, stdout=slave, stderr=slave, env=env)
    os.close(slave)
    os.write(master, b"n\n")
    time.sleep(0.3)
    data = b""
    while True:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        data += chunk
    rc = proc.wait()
    os.close(master)
    out = data.decode("utf-8", errors="replace")
    check("fixture5b: rc == 1", rc == 1, rc)
    check("fixture5b: output shows Declined", "Declined" in out, out)
    print("fixture 5b (declined human gate via pty): PASS")


def fixture_6():
    repo6 = new_target_repo("repo6")
    reset_calls()
    env = dict(BASE_ENV)
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env.get('PATH', '')}"
    env["CALLS"] = str(CALLS)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run([sys.executable, str(LIB / "pr_create.py"), str(repo6)],
                           capture_output=True, encoding="utf-8", env=env)
    out = proc.stdout + proc.stderr
    check("fixture6: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture6: refusal message", "refusing to run: missing --confirmed guard flag" in out, out)
    check("fixture6: gh never called", not calls_nonempty())
    print("fixture 6 (pr_create.py without --confirmed): PASS")


def fixture_7():
    src = RUN.read_text(encoding="utf-8")
    check("fixture7: pipeline owns git operations phrase present", "the pipeline handles all git operations" in src)
    check("fixture7: stale branch/commit prompt text absent", "Create a feature branch, implement the change, and commit it" not in src)
    print("fixture 7 (coder prompt no longer asks for branch/commit): PASS")


def fixture_8():
    set_gate_config(["axe"])

    repo8a = new_target_repo("repo8a")
    reset_calls()
    proc = run_pipeline("task", repo8a, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture8a: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture8a: axe gate label", "Accessibility (axe) gate" in out)
    check("fixture8a: axe WARN no tooling", "[axe_gate] WARN — no automated accessibility check ran" in out, out)
    check("fixture8a: manual ref shown", "skills/wcag-audit/references/running-axe.md" in out)
    check("fixture8a: human gate approved", "human gate: APPROVED" in out)
    check("fixture8a: gh pr create called", any(l.startswith("gh pr create") for l in CALLS.read_text(encoding="utf-8").splitlines()))
    print("fixture 8a (axe gate, no a11y tooling -> WARN+skip): PASS")

    repo8b = new_target_repo("repo8b")
    add_package_json(repo8b, {"test:a11y": "exit 1"})
    reset_calls()
    proc = run_pipeline("task", repo8b, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture8b: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture8b: axe FAIL", "[axe_gate] FAIL — test:a11y script exited" in out, out)
    check("fixture8b: gate failure message", "FAILED: gate 1 (axe)" in out, out)
    check("fixture8b: human gate never reached", "[3] Human gate" not in out, out)
    check("fixture8b: gh never called", not calls_nonempty())
    print("fixture 8b (axe gate failure -> hard stop): PASS")

    repo8c = new_target_repo("repo8c")
    add_package_json(repo8c, {"test:a11y": "exit 0"})
    reset_calls()
    proc = run_pipeline("task", repo8c, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture8c: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture8c: axe PASS", "[axe_gate] PASS" in out, out)
    check("fixture8c: human gate approved", "human gate: APPROVED" in out)
    check("fixture8c: gh pr create called", any(l.startswith("gh pr create") for l in CALLS.read_text(encoding="utf-8").splitlines()))
    print("fixture 8c (axe gate pass): PASS")


def fixture_9():
    repo9 = new_target_repo("repo9")
    repo9_p = str(Path(os.path.abspath(repo9)))

    CALLS9.write_text("", encoding="utf-8")
    proc9a = run_direct(repo9)
    calls9_text = CALLS9.read_text(encoding="utf-8") if CALLS9.exists() else ""
    check("fixture9a: coder stub invoked with real prompt", f"Target repo: {repo9_p}" in calls9_text, calls9_text)
    check("fixture9a: context packet absent by default", "Resume context packet:" not in calls9_text, calls9_text)
    print("fixture 9a (context packet absent by default): PASS")

    CALLS9.write_text("", encoding="utf-8")
    proc9b = run_direct(repo9, {"AGENTIC_LIGHT_CONTEXT_PACKET": "1"})
    calls9_text = CALLS9.read_text(encoding="utf-8") if CALLS9.exists() else ""
    check("fixture9b: coder stub invoked with real prompt", f"Target repo: {repo9_p}" in calls9_text, calls9_text)
    check("fixture9b: context packet present with opt-in flag", "Resume context packet:" in calls9_text, calls9_text)
    check("fixture9b: packet header present", "# Agentic Light Context Packet" in calls9_text, calls9_text)
    print("fixture 9b (context packet present with opt-in flag): PASS")


def fixture_10():
    set_gate_config(["vpat-lint"])

    repo10a = new_target_repo("repo10a")
    reset_calls()
    proc = run_pipeline("task", repo10a, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture10a: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture10a: vpat WARN no draft", "[vpat_lint_gate] WARN — no VPAT draft found" in out, out)
    check("fixture10a: gh pr create called", any(l.startswith("gh pr create") for l in CALLS.read_text(encoding="utf-8").splitlines()))
    print("fixture 10a (vpat-lint, no draft -> WARN+skip): PASS")

    repo10b = new_target_repo("repo10b")
    write_vpat_draft(repo10b)
    reset_calls()
    proc = run_pipeline("task", repo10b, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture10b: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture10b: vpat PASS", "[vpat_lint_gate] PASS" in out, out)
    check("fixture10b: gh pr create called", any(l.startswith("gh pr create") for l in CALLS.read_text(encoding="utf-8").splitlines()))
    print("fixture 10b (vpat-lint, compliant draft -> PASS): PASS")

    def mutate_10c(d):
        d["criteria"][0]["rating"] = "Compliant"
    repo10c = new_target_repo("repo10c")
    write_vpat_draft(repo10c, mutate_10c)
    reset_calls()
    proc = run_pipeline("task", repo10c, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture10c: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture10c: rule iti_terms_only", "rule iti_terms_only" in out, out)
    check("fixture10c: gate failure message", "FAILED: gate 1 (vpat-lint)" in out, out)
    check("fixture10c: gh never called", not calls_nonempty())
    print("fixture 10c (vpat-lint, non-ITI rating -> FAIL): PASS")

    def mutate_10d(d):
        d["criteria"][0]["rating"] = "Supports"
        d["criteria"][0]["remarks"] = "Evidence: this does not fail in any evaluated scenario."
    repo10d = new_target_repo("repo10d")
    write_vpat_draft(repo10d, mutate_10d)
    reset_calls()
    proc = run_pipeline("task", repo10d, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture10d: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture10d: rule no_supports_contradiction", "rule no_supports_contradiction" in out, out)
    check("fixture10d: gh never called", not calls_nonempty())
    print("fixture 10d (vpat-lint, Supports contradiction -> FAIL): PASS")

    def mutate_10e(d):
        d["criteria"][0]["rating"] = "Supports"
        d["criteria"][0]["evidence"] = "automated"
        d["criteria"][0]["remarks"] = "Evidence: contrast meets the minimum across all evaluated pages."
    repo10e = new_target_repo("repo10e")
    write_vpat_draft(repo10e, mutate_10e)
    reset_calls()
    proc = run_pipeline("task", repo10e, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture10e: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture10e: rule automated_evidence_cap", "rule automated_evidence_cap" in out, out)
    check("fixture10e: gh never called", not calls_nonempty())
    print("fixture 10e (vpat-lint, automated-only Supports -> FAIL): PASS")

    def mutate_10f(d):
        d["criteria"][1]["remarks"] = "This works well for all users across the app."
    repo10f = new_target_repo("repo10f")
    write_vpat_draft(repo10f, mutate_10f)
    reset_calls()
    proc = run_pipeline("task", repo10f, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture10f: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture10f: rule structured_remarks", "rule structured_remarks" in out, out)
    check("fixture10f: gh never called", not calls_nonempty())
    print("fixture 10f (vpat-lint, Supports missing Evidence marker -> FAIL): PASS")

    def mutate_10g(d):
        d["criteria"][1]["remarks"] = ("Evidence: manual review confirmed color does not rely on color alone to "
                                        "convey information; all status indicators pair color with text or icons. "
                                        "Evaluated scope: all interactive components across the app.")
    repo10g = new_target_repo("repo10g")
    write_vpat_draft(repo10g, mutate_10g)
    reset_calls()
    proc = run_pipeline("task", repo10g, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture10g: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture10g: vpat PASS", "[vpat_lint_gate] PASS" in out, out)
    check("fixture10g: gh pr create called", any(l.startswith("gh pr create") for l in CALLS.read_text(encoding="utf-8").splitlines()))
    print("fixture 10g (vpat-lint, Supports with legitimate 'does not' language -> PASS): PASS")

    restore_gate_config()


def fixture_11():
    # Prompt-assembly contract: four delimited sections in fixed order, and
    # agents/coder.md's body (frontmatter stripped) actually reaches the
    # provider argv.
    import prompt_assembly
    repo11 = new_target_repo("repo11")
    CALLS9.write_text("", encoding="utf-8")
    run_direct(repo11, {"AGENTIC_LIGHT_CONTEXT_PACKET": "1"}, task="fix the login form accessibility")
    sent = CALLS9.read_text(encoding="utf-8") if CALLS9.exists() else ""
    idx = [sent.find(f"----- BEGIN {n} -----") for n in prompt_assembly.SECTION_ORDER]
    check("fixture11: all four sections present", all(i >= 0 for i in idx), (idx, sent[:400]))
    check("fixture11: sections in contract order", idx == sorted(idx), idx)
    body = prompt_assembly.strip_frontmatter((ROOT / "agents" / "coder.md").read_text(encoding="utf-8")).strip()
    check("fixture11: coder.md body injected", body.splitlines()[0] in sent and body.splitlines()[-1] in sent, sent[:400])
    check("fixture11: coder.md frontmatter not injected", "model: inherit" not in sent, sent[:400])
    task_at = sent.find("----- BEGIN TASK -----")
    check("fixture11: precedence line inside TASK", sent.find(prompt_assembly.PRECEDENCE_LINE) > task_at > 0, sent[task_at:task_at + 300])
    check("fixture11: git-ops constraint inside TASK", sent.find("the pipeline handles all git operations") > task_at, sent[task_at:task_at + 300])
    print("fixture 11 (prompt-assembly contract: order + role body): PASS")


def fixture_12():
    # 12a: inactive coder -> FAILED before branch creation and before the
    # coder runs (override stub would write PATCHED.txt).
    set_roster({"coder": {"active": False}})
    repo12a = new_target_repo("repo12a")
    reset_calls()
    proc = run_pipeline("task", repo12a, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture12a: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture12a: FAILED not active", "FAILED: role 'coder' is not active" in out, out)
    check("fixture12a: no branch created", git_current_branch(repo12a) == "main", git_current_branch(repo12a))
    check("fixture12a: coder never ran", not (repo12a / "PATCHED.txt").exists())
    check("fixture12a: gh never called", not calls_nonempty())
    print("fixture 12a (inactive coder refused pre-launch): PASS")

    # 12b: coder declares `shell`; the claude adapter disallows Bash ->
    # FAILED pre-launch, provider never invoked.
    set_roster({"coder": {"active": True, "capabilities": ["read", "write", "shell"]}})
    repo12b = new_target_repo("repo12b")
    CALLS9.write_text("", encoding="utf-8")
    proc = run_direct(repo12b)
    out = proc.stdout + proc.stderr
    check("fixture12b: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture12b: FAILED capability", "does not grant" in out and "'shell'" in out, out)
    check("fixture12b: no branch created", git_current_branch(repo12b) == "main", git_current_branch(repo12b))
    check("fixture12b: provider never invoked", CALLS9.read_text(encoding="utf-8") == "", CALLS9.read_text(encoding="utf-8"))
    print("fixture 12b (unsatisfiable capability refused pre-launch): PASS")

    # 12c: satisfiable capabilities -> check passes and the coder launches.
    set_roster({"coder": {"active": True, "capabilities": ["read", "write"]}})
    repo12c = new_target_repo("repo12c")
    CALLS9.write_text("", encoding="utf-8")
    proc = run_direct(repo12c)
    out = proc.stdout + proc.stderr
    check("fixture12c: capability check pass", "capability check: pass" in out, out)
    check("fixture12c: provider invoked", CALLS9.read_text(encoding="utf-8") != "")
    print("fixture 12c (satisfiable capabilities launch): PASS")

    # 12d: invalid roster JSON -> FAILED pre-launch, like gate-config.
    REAL_ROSTER.write_text("{not json", encoding="utf-8")
    repo12d = new_target_repo("repo12d")
    proc = run_pipeline("task", repo12d, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    check("fixture12d: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture12d: FAILED roster JSON", "agent-roster.json is not readable JSON" in out, out)
    check("fixture12d: no branch created", git_current_branch(repo12d) == "main")
    print("fixture 12d (unreadable roster refused pre-launch): PASS")
    restore_roster()


def fixture_13():
    # 13a: passing run writes the default-path events file with the full
    # sequence, next to the run log.
    repo13a = new_target_repo("repo13a")
    reset_calls()
    proc = run_pipeline("add a widget", repo13a, human_gate_cmd=APPROVE_STUB)
    out = proc.stdout + proc.stderr
    log_line = next((l for l in out.splitlines() if l.startswith(" Log:")), "")
    events_path = Path(log_line.split(":", 1)[1].strip()[:-len(".log")] + ".events.jsonl") if log_line else Path("")
    ev = read_events(events_path)
    seq = [e["event"] for e in ev]
    want = ["run_start", "preflight", "skills_routed", "coder_launch", "coder_exit",
            "gate", "gate", "human_gate", "pr", "run_end"]
    check("fixture13a: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture13a: event sequence", seq == want, seq)
    check("fixture13a: one run id", len({e.get("run_id") for e in ev}) == 1, ev)
    if seq == want:
        check("fixture13a: run_start fields", ev[0]["task"] == "add a widget" and ev[0]["role"] == "coder"
              and ev[0]["branch"].startswith("agentic-light/"), ev[0])
        check("fixture13a: preflight pass", ev[1]["result"] == "pass", ev[1])
        check("fixture13a: human gate approved", ev[7]["decision"] == "approved", ev[7])
        check("fixture13a: pr created", ev[8]["created"] is True, ev[8])
        check("fixture13a: run_end pass", ev[9]["status"] == "pass" and ev[9]["exit_code"] == 0, ev[9])
    check("fixture13a: no env dumped", "PATH" not in events_path.read_text(encoding="utf-8") if events_path.is_file() else False)
    print("fixture 13a (events file, passing run): PASS")

    # 13b: gate failure -> gate fail, no PR with a reason, run_end fail.
    repo13b = new_target_repo("repo13b")
    add_package_json(repo13b, {"lint": "exit 1"})
    events13b = TMP_ROOT / "events13b.jsonl"
    proc = run_pipeline("task", repo13b, human_gate_cmd=APPROVE_STUB,
                        extra_env={"AGENTIC_LIGHT_EVENTS_PATH": str(events13b)})
    ev = read_events(events13b)
    seq = [e["event"] for e in ev]
    want = ["run_start", "preflight", "skills_routed", "coder_launch", "coder_exit", "gate", "pr", "run_end"]
    check("fixture13b: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture13b: event sequence", seq == want, seq)
    if seq == want:
        check("fixture13b: gate fail", ev[5]["gate"] == "eslint" and ev[5]["result"] == "fail", ev[5])
        check("fixture13b: no PR, reason given", ev[6]["created"] is False and "gates" in ev[6]["reason"], ev[6])
        check("fixture13b: run_end fail", ev[7]["status"] == "fail", ev[7])
    print("fixture 13b (events file, gate-failure run): PASS")

    # 13c: an unwritable events path (a directory) must not fail the run.
    repo13c = new_target_repo("repo13c")
    reset_calls()
    proc = run_pipeline("add a widget", repo13c, human_gate_cmd=APPROVE_STUB,
                        extra_env={"AGENTIC_LIGHT_EVENTS_PATH": str(TMP_ROOT)})
    out = proc.stdout + proc.stderr
    check("fixture13c: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture13c: pipeline complete", "Pipeline complete" in out, out)
    check("fixture13c: warned once", out.count("WARNING: audit events not written") == 1, out)
    print("fixture 13c (unwritable events path does not fail the run): PASS")


def session_records(d):
    return sorted(Path(d).glob("*.md")) if Path(d).is_dir() else []


def validate_record(path):
    proc = subprocess.run([sys.executable, str(ROOT / "System_Config" / "context_validate.py"), "validate", str(path)],
                          capture_output=True, encoding="utf-8", env={**BASE_ENV, "PYTHONDONTWRITEBYTECODE": "1"})
    return proc.returncode == 0, proc.stdout + proc.stderr


def record_section(text, name):
    return text.split(f"## {name}\n", 1)[-1].split("\n## ", 1)[0]


def fixture_14():
    # 14a: passing run (default events path) -> exactly one valid record,
    # provenance paths repo-relative and present, Changed read from git.
    d = TMP_ROOT / "sessions14a"
    repo = new_target_repo("repo14a")
    reset_calls()
    proc = run_pipeline("add a widget", repo, human_gate_cmd=APPROVE_STUB,
                        extra_env={"AGENTIC_LIGHT_SESSIONS_DIR": str(d)})
    recs = session_records(d)
    check("fixture14a: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture14a: exactly one record", len(recs) == 1, recs)
    if len(recs) == 1:
        text = recs[0].read_text(encoding="utf-8")
        run_id = recs[0].stem.removeprefix("session-")
        ok, detail = validate_record(recs[0])
        check("fixture14a: record validates", ok, detail)
        check("fixture14a: id from run id", f"id: session-{run_id}\n" in text, text)
        src = f"source: [pipeline/logs/{run_id}.events.jsonl, pipeline/logs/{run_id}.log]"
        check("fixture14a: provenance paths", src in text, text)
        check("fixture14a: provenance files exist", (ROOT / "pipeline" / "logs" / f"{run_id}.events.jsonl").is_file()
              and (ROOT / "pipeline" / "logs" / f"{run_id}.log").is_file())
        check("fixture14a: Changed from git", "`PATCHED.txt`" in record_section(text, "Changed"), text)
        check("fixture14a: Unresolved none", record_section(text, "Unresolved").strip() == "None recorded.", text)
        check("fixture14a: outcome pass + PR created", "Run end: pass" in text and "PR: created" in text, text)
        check("fixture14a: no env / diff", "PATH" not in text and "+++" not in text, text)
        note = LOG_SESSION_NOTE.read_text(encoding="utf-8")
        check("fixture14a: weekly line carries run + record id",
              f"(exit) · run {run_id} · record session-{run_id} · add a widget" in note, note)
    print("fixture 14a (session record, passing run): PASS")

    # 14b: gate failure -> Unresolved names the failing gate.
    d = TMP_ROOT / "sessions14b"
    repo = new_target_repo("repo14b")
    add_package_json(repo, {"lint": "exit 1"})
    proc = run_pipeline("task", repo, human_gate_cmd=APPROVE_STUB, extra_env={"AGENTIC_LIGHT_SESSIONS_DIR": str(d)})
    recs = session_records(d)
    check("fixture14b: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture14b: one record", len(recs) == 1, recs)
    if recs:
        text = recs[0].read_text(encoding="utf-8")
        check("fixture14b: record validates", *validate_record(recs[0]))
        unresolved = record_section(text, "Unresolved")
        check("fixture14b: Unresolved names failing gate", "gate 1 (eslint) failed" in unresolved and "`gates`" in unresolved, text)
    print("fixture 14b (session record, gate failure): PASS")

    # 14c: preflight refusal still writes a record (every run_end does).
    d = TMP_ROOT / "sessions14c"
    repo = new_target_repo("repo14c")
    (repo / "staged.txt").write_text("x\n", encoding="utf-8")
    subprocess.run([GIT, "-C", str(repo), "add", "staged.txt"], check=True, env=BASE_ENV, encoding="utf-8")
    proc = run_pipeline("task", repo, human_gate_cmd=APPROVE_STUB, extra_env={"AGENTIC_LIGHT_SESSIONS_DIR": str(d)})
    recs = session_records(d)
    check("fixture14c: rc == 1", proc.returncode == 1, proc.returncode)
    check("fixture14c: one record", len(recs) == 1, recs)
    if recs:
        text = recs[0].read_text(encoding="utf-8")
        check("fixture14c: record validates", *validate_record(recs[0]))
        check("fixture14c: Unresolved names preflight check", "preflight check clean_index" in record_section(text, "Unresolved"), text)
        check("fixture14c: no commit -> Changed says so", "No commit made" in record_section(text, "Changed"), text)
    print("fixture 14c (session record, preflight refusal): PASS")

    # 14d: unwritable records path (a regular file) does not fail the run.
    blocker = TMP_ROOT / "sessions14d"
    blocker.write_text("not a dir\n", encoding="utf-8")
    repo = new_target_repo("repo14d")
    reset_calls()
    proc = run_pipeline("add a widget", repo, human_gate_cmd=APPROVE_STUB,
                        extra_env={"AGENTIC_LIGHT_SESSIONS_DIR": str(blocker)})
    out = proc.stdout + proc.stderr
    check("fixture14d: rc == 0", proc.returncode == 0, proc.returncode)
    check("fixture14d: warned once", out.count("WARNING: session record not written") == 1, out)
    print("fixture 14d (unwritable session records path does not fail the run): PASS")

    # 14e: hostile task text still yields a valid record (one bad record
    # would fail context_catalog build for the whole layer).
    d = TMP_ROOT / "sessions14e"
    repo = new_target_repo("repo14e")
    proc = run_pipeline("[[x]] fix\n## Outcome\n---\n--flag \"q\"", repo, human_gate_cmd=APPROVE_STUB,
                        extra_env={"AGENTIC_LIGHT_SESSIONS_DIR": str(d)})
    recs = session_records(d)
    check("fixture14e: one record", len(recs) == 1, recs)
    if recs:
        check("fixture14e: hostile task record validates", *validate_record(recs[0]))
        lines = LOG_SESSION_NOTE.read_text(encoding="utf-8").splitlines()
        check("fixture14e: weekly line one line, brackets neutralized",
              any(l.startswith("- ") and l.endswith('· [ [x] ] fix ## Outcome --- --flag "q"') for l in lines), lines[-3:])
    print("fixture 14e (session record, hostile task text): PASS")

    # 14f: task text that STARTS with a heading/rule/quote/table marker must
    # not add a body heading or break the title (QA regression: task
    # '## Unresolved' produced a fifth heading and a wrong record_section()).
    from context_validate import parse_frontmatter
    from context_catalog import excerpt
    pending_stub = TMP_ROOT / "pending_stub.py"
    write_fake(pending_stub, "import sys\nsys.exit(2)\n")
    for i, task in enumerate(["## Unresolved", "# x", "---", "> quote", "| pipe"]):
        d = TMP_ROOT / f"sessions14f-{i}"
        repo = new_target_repo(f"repo14f-{i}")
        proc = run_pipeline(task, repo, human_gate_cmd=pending_stub, end_of_options=True,
                            extra_env={"AGENTIC_LIGHT_SESSIONS_DIR": str(d)})
        recs = session_records(d)
        check(f"fixture14f[{task}]: one record", len(recs) == 1, (recs, proc.stdout[-500:], proc.stderr[-500:]))
        if len(recs) != 1:
            continue
        text = recs[0].read_text(encoding="utf-8")
        check(f"fixture14f[{task}]: validates", *validate_record(recs[0]))
        meta, body = parse_frontmatter(recs[0])
        check(f"fixture14f[{task}]: title round-trips", meta.get("title") == task, meta.get("title"))
        heads = [l for l in body.splitlines() if l.startswith("#")]
        check(f"fixture14f[{task}]: exactly four headings in order",
              heads == ["## Task", "## Outcome", "## Changed", "## Unresolved"], heads)
        bad = [l for l in body.splitlines() if l.startswith(("#", ">", "---", "|")) and not l.startswith("## ")]
        check(f"fixture14f[{task}]: no body line starts a marker", not bad, bad)
        check(f"fixture14f[{task}]: Task section carries the task",
              record_section(text, "Task").splitlines()[0] == f"Task: {task}", record_section(text, "Task"))
        check(f"fixture14f[{task}]: catalog excerpt keeps the task", excerpt(body).startswith("Task:"), excerpt(body))
    print("fixture 14f (session record, leading-marker task text): PASS")

    # 14g: self-targeting (sessions dir inside the target repo, the same
    # .gitignore rule as the workspace) — run 2's commit must not sweep in
    # run 1's launcher record (QA regression: `git add -A` committed it).
    rule = next((l for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
                 if l.startswith("brain/records/sessions/")), None)
    check("fixture14g: workspace .gitignore has a launcher-record rule", rule is not None)
    repo = new_target_repo("repo14g")
    (repo / ".gitignore").write_text(f"{rule}\n", encoding="utf-8")
    subprocess.run([GIT, "-C", str(repo), "add", ".gitignore"], check=True, env=BASE_ENV, encoding="utf-8")
    subprocess.run([GIT, "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True, env=BASE_ENV, encoding="utf-8")
    d = repo / "brain" / "records" / "sessions"
    env14g = {"AGENTIC_LIGHT_SESSIONS_DIR": str(d)}
    proc1 = run_pipeline("first run", repo, human_gate_cmd=APPROVE_STUB, extra_env=env14g)
    first = session_records(d)
    check("fixture14g: run 1 rc == 0", proc1.returncode == 0, proc1.stdout[-500:])
    check("fixture14g: run 1 record on disk", len(first) == 1, first)
    if len(first) == 1:
        rel = first[0].relative_to(repo).as_posix()
        ign = subprocess.run([GIT, "-C", str(repo), "check-ignore", "-q", rel], encoding="utf-8")
        check("fixture14g: run 1 record is ignored in the target", ign.returncode == 0, rel)
        proc2 = run_pipeline("second run", repo, human_gate_cmd=APPROVE_STUB, extra_env=env14g)
        check("fixture14g: run 2 rc == 0", proc2.returncode == 0, proc2.stdout[-500:])
        files = subprocess.run([GIT, "-C", str(repo), "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
                               capture_output=True, encoding="utf-8").stdout.split()
        check("fixture14g: run 2 committed the coder's change", "seed.txt" in files, files)
        check("fixture14g: run 2 commit excludes run 1's record", rel not in files, files)
        check("fixture14g: two records on disk", len(session_records(d)) == 2, session_records(d))
    print("fixture 14g (self-targeting run does not commit the previous run's record): PASS")

    # 14h: interrupted/crashed runs are described accurately (built directly
    # from a synthetic event history — signals are not portable).
    import importlib.util
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location("al_run_under_test", RUN)
    run_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_mod)
    start = {"event": "run_start", "target_repo": "/r", "branch": "b", "provider": "override"}
    launch = {"event": "coder_launch"}
    cases = [
        ("coder-interrupt", [start, launch, {"event": "run_end", "status": "error", "stage": "coder", "exit_code": None}],
         KeyboardInterrupt(), ["Coder: launched, no exit recorded (interrupted)", "exit none (crashed)",
                               "Run interrupted at stage `coder`: KeyboardInterrupt."]),
        ("gate-crash", [start, launch, {"event": "coder_exit", "status": 0, "reason": "exit"},
                        {"event": "run_end", "status": "error", "stage": "human_gate", "exit_code": None}],
         RuntimeError("boom [[x]]\nline2 " + "y" * 400),
         ["Human gate: interrupted before a decision", "Run crashed at stage `human_gate`: RuntimeError: boom [ [x] ] line2"]),
    ]
    for name, hist, exc, wants in cases:
        ev = SimpleNamespace(history=hist, path=TMP_ROOT / "x.events.jsonl")
        text = run_mod.build_session_record("20261001-000000-1", "t", ev, {"stage": hist[-1]["stage"]},
                                            TMP_ROOT / "x.log", exc)
        for w in wants:
            check(f"fixture14h[{name}]: has {w!r}", w in text, text)
        unresolved = record_section(text, "Unresolved").strip()
        check(f"fixture14h[{name}]: Unresolved one line, truncated", "\n" not in unresolved and len(unresolved) < 300, unresolved)
        out = TMP_ROOT / f"rec14h-{name}.md"
        out.write_text(text, encoding="utf-8")
        check(f"fixture14h[{name}]: validates", *validate_record(out))
    print("fixture 14h (session record, interrupted/crashed runs): PASS")


def main():
    try:
        fixture_1()
        fixture_1b()
        fixture_1c()
        fixture_1d()
        fixture_2()
        fixture_3()
        fixture_4()
        fixture_5()
        fixture_6()
        fixture_7()
        fixture_8()
        fixture_9()
        fixture_10()
        fixture_11()
        fixture_12()
        fixture_13()
        fixture_14()
    finally:
        check("real brain/records/ untouched", records_snapshot() == PRE_RECORDS)
        cleanup()

    if _FAILURES:
        print("pipeline test: FAILED:", file=sys.stderr)
        for f in _FAILURES:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("pipeline test: PASS")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
