#!/usr/bin/env python3
"""run.py — Agentic Light pipeline orchestrator. Python port of run.sh.
Task Input -> coder -> configured gates -> Human Gate -> gh pr create
Usage: run.py "<task description>" [target-repo-path]
  target-repo-path defaults to the current directory. This pipeline operates
  against an EXTERNAL target repo, not against Agentic_Light itself.
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "System_Config"))
import config              # noqa: E402  resolve_agent_provider(), acquire_lock(), looks_like_secret(), WORKSPACE
import run_agent as ra     # noqa: E402  run_agent()
import route_skill         # noqa: E402  route() — imported and called directly, not subprocessed (nothing overrides it via env var)
import context_packet      # noqa: E402  build_packet() — same reasoning
import prompt_assembly     # noqa: E402  assemble(), check_launch() — the role launch contract

PIPELINE_DIR = ROOT / "pipeline"
LIB = PIPELINE_DIR / "lib"

GATE_MODULES = {
    "eslint": "eslint_gate.py",
    "playwright": "playwright_gate.py",
    "axe": "axe_gate.py",
    "vpat-lint": "vpat_lint_gate.py",
}


class Tee:
    """Swapped onto sys.stdout/sys.stderr for _run()'s duration — mirrors
    bash's `exec > >(tee -a "$RUN_LOG") 2>&1` for THIS script's own text
    output. Subprocess children (gates, human_gate, pr_create) inherit the
    real fd directly and are NOT captured into RUN_LOG this way — a small,
    documented fidelity gap vs. bash's fd-level redirect (which every child
    inherited for free); doing a true OS-level fd tee was assessed as out of
    scope/risk for this port. The coder's own transcript IS captured (see
    run_agent.run_agent()'s `log=` parameter, a direct file redirect,
    independent of this class)."""

    def __init__(self, log_f, real_stream):
        self._log_f = log_f
        self._real = real_stream

    def write(self, text):
        self._real.write(text)
        self._real.flush()  # avoid buffering skew against subprocess children writing to the same inherited fd
        self._log_f.write(text.encode("utf-8", errors="replace"))
        self._log_f.flush()

    def flush(self):
        self._real.flush()
        self._log_f.flush()

    def isatty(self):
        return self._real.isatty()

    @property
    def buffer(self):
        return self._real.buffer

    @property
    def log_f(self):
        return self._log_f


class EventLog:
    """Provider-neutral audit trail for one run: JSON Lines appended to
    pipeline/logs/<run-id>.events.jsonl. The launcher's record of truth —
    log_session.py's weekly-note line is compatibility output, and provider
    hooks may only adapt to this file. Best-effort by contract: a failed
    write warns once on stderr and never changes the pipeline's outcome.
    Callers pass explicit fields only — never the environment, the prompt,
    or the diff."""

    def __init__(self, path, run_id):
        self.path = path
        self.run_id = run_id
        self._warned = False

    def emit(self, event, **fields):
        record = {"v": 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "run_id": self.run_id, "event": event, **fields}
        try:
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:  # noqa: BLE001 — audit writes must never fail the run
            if not self._warned:
                self._warned = True
                print(f"WARNING: audit events not written to {self.path} ({type(e).__name__}) — continuing.", file=sys.stderr)


def _events_path(run_id):
    """pipeline/logs/<run-id>.events.jsonl; AGENTIC_LIGHT_EVENTS_PATH
    overrides it only under AGENTIC_LIGHT_TEST_MODE=1 (same test-only
    contract as PIPELINE_HUMAN_GATE_CMD)."""
    override = os.environ.get("AGENTIC_LIGHT_EVENTS_PATH")
    if override and os.environ.get("AGENTIC_LIGHT_TEST_MODE") == "1":
        return Path(override)
    return PIPELINE_DIR / "logs" / f"{run_id}.events.jsonl"


def _resolve_provider_quietly():
    """Provider run_agent() will pick, for the audit trail and capability
    check. resolve_agent_provider() is idempotent and run_agent() re-runs it
    (and prints its own errors) at launch, so its stderr is muted here."""
    with contextlib.redirect_stderr(io.StringIO()):
        return config.AGENT_PROVIDER if config.resolve_agent_provider() else None


def _child_env():
    """env for a spawned Python child — PYTHONUTF8=1 so its own default I/O
    encoding is UTF-8 regardless of platform. Harmless (an unused env var)
    for a non-Python child (a custom gate script, or a PIPELINE_*_CMD
    override pointing at an arbitrary binary)."""
    return {**os.environ, "PYTHONUTF8": "1"}


def _spawn(argv, cwd=None):
    """Spawn argv and return its exit code. When sys.stdout is a Tee (the
    normal case inside _run_body — see main()/_run()), relays the child's
    combined stdout+stderr into RUN_LOG in byte chunks (not line-oriented —
    a line relay would swallow/delay human_gate.py's no-trailing-newline
    prompt text) so gate verdicts, the human-gate diff, and pr_create's own
    output all land in the log, matching bash's `exec > >(tee)` behavior for
    every child (see the Tee docstring's note on why that isn't automatic
    here). Stdin is left inherited throughout, so human_gate.py's
    interactive TTY prompt still works. Falls back to a plain, fd-inherited
    subprocess.run when sys.stdout isn't a Tee (e.g. a future caller outside
    _run_body) — same observable behavior as before this relay existed."""
    env = _child_env()
    cwd_str = str(cwd) if cwd else None
    if not isinstance(sys.stdout, Tee):
        return subprocess.run(argv, cwd=cwd_str, encoding="utf-8", env=env).returncode
    proc = subprocess.Popen(argv, cwd=cwd_str, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    real_buffer = sys.stdout.buffer
    log_f = sys.stdout.log_f
    for chunk in iter(lambda: proc.stdout.read(4096), b""):
        real_buffer.write(chunk)
        real_buffer.flush()
        log_f.write(chunk)
        log_f.flush()
    proc.wait()
    return proc.returncode


def _dispatch(script_path, args, cwd=None):
    """Custom-gate / PIPELINE_CODER_CMD / PIPELINE_HUMAN_GATE_CMD dispatch:
    a .py path is run under this same interpreter; anything else is invoked
    directly. No shell tokenizing — a narrowed, documented contract (single
    executable path only), matching blueprint §2. Returns the exit code
    (int), not a CompletedProcess — see _spawn()."""
    script_path = Path(script_path)
    argv = [sys.executable, str(script_path), *args] if script_path.suffix == ".py" else [str(script_path), *args]
    return _spawn(argv, cwd=cwd)


def run_custom_gate(gate, target_repo):
    target_p = target_repo.resolve()
    cwd_abs = target_repo / gate.get("cwd", ".")
    if not cwd_abs.is_dir():
        print(f"FAILED: custom gate cwd does not resolve to a directory: {cwd_abs}")
        return 1
    cwd_p = cwd_abs.resolve()
    if cwd_p != target_p and target_p not in cwd_p.parents:
        print(f"FAILED: custom gate cwd escapes target repo: {gate.get('cwd')} (resolved: {cwd_p})")
        return 1
    script_abs = target_repo / gate["script"]
    if not script_abs.is_file():
        print(f"FAILED: custom gate script not found: {script_abs}")
        return 1
    if script_abs.is_symlink():
        print(f"FAILED: custom gate script is a symlink, refusing (its target may resolve outside the target repo): {gate['script']}")
        return 1
    script_p = script_abs.resolve()
    if script_p != target_p and target_p not in script_p.parents:
        print(f"FAILED: custom gate script escapes target repo: {gate['script']} (resolved: {script_p})")
        return 1
    print(f"-> custom gate: {gate['script']}")
    return _dispatch(script_p, gate.get("args", []), cwd=cwd_p)


def run_gate(gate, n, target_repo):
    """gate is a known gate name (str) or a custom-gate dict. Returns the
    gate's exit code."""
    if isinstance(gate, str):
        label = {"eslint": "ESLint gate", "playwright": "Playwright E2E gate",
                  "axe": "Accessibility (axe) gate", "vpat-lint": "VPAT draft lint gate"}[gate]
        print(f"-> [gate {n}] {label}")
        script = LIB / GATE_MODULES[gate]
        return _dispatch(script, [str(target_repo)])
    print(f"-> [gate {n}] custom gate: {gate.get('script')}")
    return run_custom_gate(gate, target_repo)


def reason_for_status(status, provider=""):
    """Maps a completed coder process's exit status to log_session.py's
    --reason vocabulary (exit|timeout|signal|refused)."""
    if status == 64:
        return "refused" if provider == "ollama" else "exit"
    if status in (137, 143):
        return "timeout"
    if status > 128:
        return "signal"
    return "exit"


def validate_gate_config(gate_config_path, schema_path):
    """Raises ValueError with a "FAILED: ..." message on any structural
    problem; returns the validated `gates` list on success. Direct
    transliteration of run.sh's embedded python validation heredoc — no
    subprocess/heredoc dance needed now that this script IS Python."""
    try:
        cfg = json.loads(gate_config_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"FAILED: pipeline/gate-config.json is not valid JSON: {e}")
    if not isinstance(cfg, dict) or "gates" not in cfg:
        raise ValueError('FAILED: pipeline/gate-config.json must be an object with a "gates" array')
    gates = cfg["gates"]
    if not isinstance(gates, list):
        raise ValueError('FAILED: pipeline/gate-config.json "gates" must be an array')
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        known = tuple(schema["definitions"]["gate"]["oneOf"][0]["enum"])
    except Exception as e:
        raise ValueError(f"FAILED: cannot read known gate names from System_Config/gate-config.schema.json: {e}")
    for i, gate in enumerate(gates):
        if isinstance(gate, str):
            if gate not in known:
                raise ValueError(f"FAILED: pipeline/gate-config.json gates[{i}] unknown gate name {gate!r} (expected one of {known} or a custom object)")
            continue
        if isinstance(gate, dict):
            if gate.get("name") != "custom":
                raise ValueError(f'FAILED: pipeline/gate-config.json gates[{i}] object gate must have "name": "custom"')
            script = gate.get("script")
            if not isinstance(script, str) or not script:
                raise ValueError(f'FAILED: pipeline/gate-config.json gates[{i}] custom gate missing required string "script"')
            cwd = gate.get("cwd", ".")
            if not isinstance(cwd, str):
                raise ValueError(f'FAILED: pipeline/gate-config.json gates[{i}] custom gate "cwd" must be a string')
            args = gate.get("args", [])
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError(f'FAILED: pipeline/gate-config.json gates[{i}] custom gate "args" must be an array of strings')
            extra = set(gate.keys()) - {"name", "script", "cwd", "args"}
            if extra:
                raise ValueError(f"FAILED: pipeline/gate-config.json gates[{i}] custom gate has unknown fields: {sorted(extra)}")
            continue
        raise ValueError(f"FAILED: pipeline/gate-config.json gates[{i}] must be a known gate name or a custom gate object")
    return gates


def _sensitive_hits(target_repo):
    import re
    patterns = [re.compile(r'^\.env.*$'), re.compile(r'.*\.key$'), re.compile(r'.*\.pem$'), re.compile(r'^id_rsa.*$')]
    hits = []
    for dirpath, dirnames, filenames in os.walk(target_repo):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        for fname in filenames:
            if any(p.match(fname) for p in patterns):
                hits.append(str(Path(dirpath) / fname))
    return sorted(hits)


def _env_nonneg_int(name, default):
    if name not in os.environ:
        return default, None
    raw = os.environ[name]
    if raw.isdigit():
        return int(raw), None
    return default, f'  {name}="{raw}" is not a non-negative integer — falling back to {default}'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task_desc")
    parser.add_argument("target_repo", nargs="?", default=".")
    args = parser.parse_args(argv)

    target_repo = Path(os.path.abspath(args.target_repo))
    (PIPELINE_DIR / "logs").mkdir(parents=True, exist_ok=True)

    lock_key = zlib.crc32(os.path.normcase(str(target_repo)).encode("utf-8"))
    lock_dir = PIPELINE_DIR / "logs" / f".run.{lock_key}.lock"

    with config.acquire_lock(lock_dir, max_age=7200) as held:
        if not held:
            print(f"[run.py] another pipeline run holds the lock for {target_repo} ({lock_dir}) — refusing to run concurrently.", file=sys.stderr)
            return 1
        return _run(args.task_desc, target_repo)


def _run(task_desc, target_repo):
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    run_log_path = PIPELINE_DIR / "logs" / f"{run_id}.log"
    branch_name = f"agentic-light/{run_id}"

    log_f = open(run_log_path, "ab")
    real_stdout, real_stderr = sys.stdout, sys.stderr
    tee = Tee(log_f, real_stdout)
    sys.stdout = tee
    sys.stderr = Tee(log_f, real_stderr)
    events = EventLog(_events_path(run_id), run_id)
    # stage: last step reached; pr_done: a "pr" event was already emitted.
    state = {"stage": "start", "pr_done": False}
    rc = None
    try:
        rc = _run_body(task_desc, target_repo, run_id, run_log_path, branch_name, events, state)
        return rc
    finally:
        if not state["pr_done"]:
            events.emit("pr", created=False, reason=f"run halted at {state['stage']}")
        events.emit("run_end", exit_code=rc, stage=state["stage"],
                    status="error" if rc is None else "pass" if rc == 0
                    else "pending" if rc == 2 and state["stage"] == "human_gate" else "fail")
        sys.stdout, sys.stderr = real_stdout, real_stderr
        log_f.close()


def _run_body(task_desc, target_repo, run_id, run_log_path, branch_name, events, state):
    coder_cmd = os.environ.get("PIPELINE_CODER_CMD")
    provider = "override" if coder_cmd else _resolve_provider_quietly()
    events.emit("run_start", task=task_desc, target_repo=str(target_repo), branch=branch_name,
                provider=provider, role="coder", preset=prompt_assembly.active_preset(ROOT),
                log=str(run_log_path))

    def preflight_fail(check, msg):
        print(msg)
        events.emit("preflight", result="fail", check=check)
        return 1

    state["stage"] = "preflight"
    print("=" * 50)
    print(" Agentic Light Pipeline — run " + run_id)
    print(" Task:        " + task_desc)
    print(" Target repo: " + str(target_repo))
    print(" Branch:      " + branch_name)
    print(" Log:         " + str(run_log_path))
    print("=" * 50)
    print()

    # Gate-config validation up front — before anything runs.
    gate_config_path = PIPELINE_DIR / "gate-config.json"
    gates_from_config = None
    if gate_config_path.is_file():
        try:
            gates_from_config = validate_gate_config(gate_config_path, ROOT / "System_Config" / "gate-config.schema.json")
        except ValueError as e:
            return preflight_fail("gate_config", str(e))

    # Roster/capability enforcement — before any branch exists or the coder
    # runs. No System_Config/agent-roster.json = no check (unspecialized fork).
    try:
        roster_info = prompt_assembly.check_launch("coder", None if provider == "override" else provider)
    except ValueError as e:
        return preflight_fail("roster", str(e))
    if roster_info["roster"] == "present":
        print(f"-> [0] Roster check: coder active; capability check: {roster_info['capability_check']}")

    print(f"-> [0] Pre-flight sensitive-file scan: {target_repo}")
    hits = _sensitive_hits(target_repo)
    if hits:
        print(f"WARNING: {target_repo} contains file(s) matching sensitive-file patterns (.env*, *.key, *.pem, id_rsa*):")
        for h in hits:
            print(f"  {h}")
        if os.environ.get("AGENTIC_LIGHT_ALLOW_SENSITIVE_REPO") != "1":
            print("FAILED: refusing to launch the coder with these files present in its cwd (advisory filename screening, not a security boundary) — its Read/Grep tools have no path restriction beyond cwd.")
            print("  Set AGENTIC_LIGHT_ALLOW_SENSITIVE_REPO=1 to proceed anyway (e.g. once you've confirmed these are dummy/fixture files).")
            events.emit("preflight", result="fail", check="sensitive_files")
            return 1
        print("  AGENTIC_LIGHT_ALLOW_SENSITIVE_REPO=1 set — proceeding despite the match(es) above.")
    print()

    git = shutil.which("git")
    if git is None:
        return preflight_fail("git", "FAILED: git not found on PATH")

    print("-> [1] Code patch step")
    staged = subprocess.run([git, "-C", str(target_repo), "diff", "--cached", "--quiet"], encoding="utf-8")
    if staged.returncode != 0:
        return preflight_fail("clean_index", f"FAILED: {target_repo} has staged changes before the pipeline started — refusing to run. Commit or unstage them first; this pipeline assumes a clean index so its own rollback/commit steps don't touch changes it doesn't own.")
    events.emit("preflight", result="pass", roster=roster_info, sensitive_files=len(hits))

    state["stage"] = "branch"

    print(f"  creating feature branch: {branch_name}")
    branch = subprocess.run([git, "-C", str(target_repo), "checkout", "-b", branch_name], encoding="utf-8")
    if branch.returncode != 0:
        print(f"FAILED: could not create feature branch {branch_name} in {target_repo}")
        return 1

    # Skill routing — best-effort, capped at SKILL_MATCH_LIMIT matches.
    skill_match_limit, warn = _env_nonneg_int("AGENTIC_LIGHT_SKILL_MATCH_LIMIT", 3)
    if warn:
        print(warn, file=sys.stderr)
    skill_texts = []
    routed = []
    try:
        matched_skills = route_skill.route_scored(task_desc)
    except Exception:
        matched_skills = []
    for i, (skill_dir, score) in enumerate(matched_skills, start=1):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        injected = i <= skill_match_limit
        routed.append({"skill": skill_dir.name, "score": round(score, 4), "injected": injected})
        if not injected:
            print(f"  routed skill: {skill_dir} (skipped — over {skill_match_limit}-match cap)")
            continue
        print(f"  routed skill: {skill_dir}")
        skill_texts.append(skill_md.read_text(encoding="utf-8"))
    events.emit("skills_routed", cap=skill_match_limit, skills=routed)

    # Context packet — opt-in only (see context_packet.py's module docstring).
    context_packet_text = ""
    root_p = ROOT.resolve()
    target_p = target_repo.resolve()
    if os.environ.get("AGENTIC_LIGHT_CONTEXT_PACKET") == "1" or target_p == root_p:
        try:
            profile_env = os.environ.get("AGENTIC_LIGHT_CONTEXT_PROFILE")
            max_lines, _ = _env_nonneg_int("AGENTIC_LIGHT_CONTEXT_MAX_LINES", 120)
            max_bytes, _ = _env_nonneg_int("AGENTIC_LIGHT_CONTEXT_MAX_BYTES", 12000)
            packet_bytes = context_packet.build_packet(
                ROOT, profile_env or "agentic-light", bool(profile_env), "", 5, max_lines, max_bytes)
            context_packet_text = packet_bytes.decode("utf-8", errors="replace")
        except Exception:
            context_packet_text = ""

    state["stage"] = "coder"
    coder_rc = 0
    if coder_cmd:
        print(f"  using PIPELINE_CODER_CMD override: {coder_cmd}")
        events.emit("coder_launch", provider="override", role="coder", via="PIPELINE_CODER_CMD")
        coder_rc = _dispatch(coder_cmd, [task_desc, str(target_repo)])
        coder_provider = os.environ.get("AGENT_PROVIDER") or "override"
    else:
        print("  invoking coder via System_Config/run_agent.py")
        # Kept on one physical source line (not wrapped) — test_pipeline.py's
        # fixture 7 greps this .py file's raw source text for the literal
        # phrase "the pipeline handles all git operations" as a regression
        # guard; splitting it across adjacent string literals would still
        # concatenate correctly at runtime but would break that source-text
        # search.
        task_block = f"Target repo: {target_repo}. Task: {task_desc}. Implement the change on the current branch. Do not run shell commands, create branches, or commit — the pipeline handles all git operations."
        sections = prompt_assembly.assemble_sections("coder", task_block, skill_texts, context_packet_text, ROOT)
        prompt = prompt_assembly.assemble("coder", task_block, skill_texts, context_packet_text, ROOT)
        events.emit("coder_launch", provider=provider, role="coder", via="run_agent",
                    prompt_sections=[{"name": n, "bytes": len(c.encode("utf-8"))} for n, c in sections])
        coder_rc = ra.run_agent(prompt, log=str(run_log_path), brain=str(target_repo))
        coder_provider = config.AGENT_PROVIDER or "unknown"

    subprocess.run([sys.executable, str(ROOT / "System_Config" / "log_session.py"),
                     "--provider", coder_provider, "--role", "coder",
                     "--status", str(coder_rc), "--reason", reason_for_status(coder_rc, coder_provider)],
                    env=_child_env())
    events.emit("coder_exit", provider=coder_provider, status=coder_rc,
                reason=reason_for_status(coder_rc, coder_provider))

    state["stage"] = "commit"
    if coder_rc != 0:
        print(f"FAILED: code patch step (coder exited {coder_rc})")
        return 1

    print("  staging coder's changes")
    add = subprocess.run([git, "-C", str(target_repo), "add", "-A"], encoding="utf-8")
    if add.returncode != 0:
        print(f"FAILED: could not stage coder's changes in {target_repo}")
        return 1
    diff_proc = subprocess.run([git, "-C", str(target_repo), "diff", "--cached"], capture_output=True, encoding="utf-8", errors="replace")
    diff = diff_proc.stdout or ""
    if not diff.strip():
        print("FAILED: code patch step produced no changes — nothing to commit, no PR will be created")
        return 1

    # Secret scan (hard stop) — reuses config.looks_like_secret, the same
    # pattern set healthcheck.py's Config Security Scan will use once
    # ported. Scanned lines only (added lines, excluding the "+++ b/..."
    # diff header).
    added_lines = [l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    secret_hits = config.looks_like_secret(added_lines, shaped_only=True)
    if secret_hits:
        print("FAILED: likely secret detected in staged changes — refusing to commit.")
        print(f"  match: {secret_hits[0]}")
        subprocess.run([git, "-C", str(target_repo), "reset", "-q"], encoding="utf-8")
        return 1

    print("  committing coder's changes")
    commit = subprocess.run([git, "-C", str(target_repo), "commit", "-q", "-m", f"Agentic Light: {task_desc}"], encoding="utf-8")
    if commit.returncode != 0:
        print(f"FAILED: could not commit coder's changes in {target_repo}")
        return 1
    print("  code patch step complete")
    print()

    # Gates — hard stop, no further steps, on any gate failure.
    state["stage"] = "gates"

    def gate_event(n, gate, rc):
        events.emit("gate", n=n, gate=gate if isinstance(gate, str) else "custom",
                    script=None if isinstance(gate, str) else gate.get("script"),
                    rc=rc, result="pass" if rc == 0 else "fail")

    if gates_from_config is not None:
        print("-> [2] Gates (from pipeline/gate-config.json)")
        for n, gate in enumerate(gates_from_config, start=1):
            rc = run_gate(gate, n, target_repo)
            gate_event(n, gate, rc)
            if rc != 0:
                label = gate if isinstance(gate, str) else "custom"
                print(f"FAILED: gate {n} ({label}) — halting, no further steps, no PR will be created")
                return 1
            print()
    else:
        print("-> [2] Gates (no gate-config.json found — using default eslint+playwright)")
        rc = run_gate("eslint", 1, target_repo)
        gate_event(1, "eslint", rc)
        if rc != 0:
            print("FAILED: ESLint gate — halting, no further steps, no PR will be created")
            return 1
        print()
        rc = run_gate("playwright", 2, target_repo)
        gate_event(2, "playwright", rc)
        if rc != 0:
            print("FAILED: Playwright gate — halting, no further steps, no PR will be created")
            return 1
        print()

    # Human Gate — blocks on TTY y/N; never auto-approves.
    state["stage"] = "human_gate"
    print("-> [3] Human gate")
    summary = (f"Task: {task_desc}\nTarget repo: {target_repo}\nBranch:      {branch_name}\n"
               "Gates: passed/skipped (see log above)\n\n"
               f"--- diff (already committed to {branch_name} in step 1) ---\n{diff or '<no diff available>'}")

    human_gate_cmd = LIB / "human_gate.py"
    override = os.environ.get("PIPELINE_HUMAN_GATE_CMD")
    if override:
        if os.environ.get("AGENTIC_LIGHT_TEST_MODE") == "1":
            human_gate_cmd = override
        else:
            print("WARNING: PIPELINE_HUMAN_GATE_CMD is set but AGENTIC_LIGHT_TEST_MODE=1 is not — ignoring override, using the real human gate (PIPELINE_HUMAN_GATE_CMD is test-only).", file=sys.stderr)
    gate_rc = _dispatch(human_gate_cmd, [summary])
    events.emit("human_gate", rc=gate_rc,
                decision={0: "approved", 2: "pending"}.get(gate_rc, "declined"))

    if gate_rc == 0:
        print("  human gate: APPROVED")
    elif gate_rc == 2:
        print("PENDING: human gate awaiting interactive review — exiting without creating a PR")
        return 2
    else:
        print("FAILED: human gate declined — no PR will be created")
        return 1
    print()

    # PR creation — only reachable after explicit approval above. Bash's
    # `set -euo pipefail` aborts run.sh immediately, with no completion
    # banner, if this step fails — the banner below is only ever reached on
    # success, and run.sh's own overall exit code in that case is always 0
    # (the last command run is a successful `echo`), never pr_create's own
    # code. Mirror both halves explicitly rather than always returning
    # pr_create's return code.
    state["stage"] = "pr"
    print("-> [4] PR creation")
    # --confirmed must be the LAST argv element — see pr_create.py's module
    # docstring on the argparse chunk-matching quirk this order avoids.
    pr_rc = _dispatch(LIB / "pr_create.py", [str(target_repo), task_desc, "--confirmed"])
    state["pr_done"] = True
    events.emit("pr", created=pr_rc == 0, rc=pr_rc,
                reason=None if pr_rc == 0 else "pr_create.py failed")
    if pr_rc != 0:
        return pr_rc
    state["stage"] = "done"
    print()
    print("=" * 50)
    print(f" Pipeline complete — run {run_id}")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    # Reconfigure the REAL streams before main() ever swaps sys.stdout/
    # sys.stderr for a Tee instance (Tee has no .reconfigure() of its own —
    # this must happen first).
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
