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

PRE_LOGS = set((ROOT / "pipeline" / "logs").glob("*.log"))


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
           "a = sys.argv[1:]\n"
           "s = open(a[1], encoding='utf-8').read() if a[:1] == ['--summary-file'] else (a[0] if a else '')\n"
           "print('[approve_stub] auto-approving:', s)\n"
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


def run_pipeline(task, target_repo, coder_cmd=CODER_STUB, human_gate_cmd=None, extra_env=None, stdin=None):
    env = dict(BASE_ENV)
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env.get('PATH', '')}"
    env["CALLS"] = str(CALLS)
    env["AGENTIC_LIGHT_TEST_MODE"] = "1"
    env["LOG_SESSION_NOTE"] = str(LOG_SESSION_NOTE)
    env["PYTHONUTF8"] = "1"
    if coder_cmd is not None:
        env["PIPELINE_CODER_CMD"] = str(coder_cmd)
    if human_gate_cmd is not None:
        env["PIPELINE_HUMAN_GATE_CMD"] = str(human_gate_cmd)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, str(RUN), task, str(target_repo)],
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


def cleanup():
    restore_gate_config()
    try:
        rmtree_force(TMP_ROOT)
    except OSError:
        pass
    for f in (ROOT / "pipeline" / "logs").glob("*.log"):
        if f not in PRE_LOGS:
            f.unlink()


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

    def run_direct(extra_env):
        env = dict(BASE_ENV)
        env.pop("AGENT_TYPE", None)
        env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env.get('PATH', '')}"
        env["CALLS9"] = str(CALLS9)
        env["MAX_SECONDS"] = "3"
        env["AGENTIC_LIGHT_PROVIDERS"] = "claude"
        env["AGENTIC_LIGHT_PRIORITY"] = "claude"
        env["AGENTIC_LIGHT_TEST_MODE"] = "1"
        env["PIPELINE_HUMAN_GATE_CMD"] = str(APPROVE_STUB)
        env["LOG_SESSION_NOTE"] = str(LOG_SESSION_NOTE)
        env["PYTHONUTF8"] = "1"
        env.update(extra_env)
        return subprocess.run([sys.executable, str(RUN), "task", str(repo9)],
                               capture_output=True, encoding="utf-8", errors="replace", env=env)

    CALLS9.write_text("", encoding="utf-8")
    proc9a = run_direct({})
    calls9_text = CALLS9.read_text(encoding="utf-8") if CALLS9.exists() else ""
    check("fixture9a: coder stub invoked with real prompt", f"Target repo: {repo9_p}" in calls9_text, calls9_text)
    check("fixture9a: context packet absent by default", "Resume context packet:" not in calls9_text, calls9_text)
    print("fixture 9a (context packet absent by default): PASS")

    CALLS9.write_text("", encoding="utf-8")
    proc9b = run_direct({"AGENTIC_LIGHT_CONTEXT_PACKET": "1"})
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
    finally:
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
