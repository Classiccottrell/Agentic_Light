#!/usr/bin/env python3
"""
gen_governance.py -- generate GOVERNANCE.md from the live agent roster,
pipeline gate config, and this fork's specialization state.

GOVERNANCE.md makes the pipeline's existing gate -> human-gate -> PR flow
(pipeline/run.sh) legible as a governance layer, instead of leaving it
implicit in a shell script. Nothing here invents new mechanism -- every
claim is pulled from a file that already governs real agent behavior.

Sources:
  agents/*.md                     -- per-role scope: frontmatter description
                                      + granted tools
  System_Config/agent-roster.json -- active roles + capabilities for THIS
                                      fork (absent on an unspecialized fork)
  pipeline/gate-config.json       -- ordered gate list for THIS fork (absent
                                      => default eslint+playwright, per
                                      pipeline/run.sh's own fallback)
  System_Config/.active-preset    -- named preset this fork was specialized
                                      with, if any (written by specialize.sh
                                      only on its --preset path; absent for
                                      interactive/env-override runs and on an
                                      unspecialized fork)
  System_Config/presets.json      -- looked up by the preset name above for
                                      an optional per-role `role_notes`
                                      overlay, rendered additively alongside
                                      each role's generic scope in agents/*.md
  pipeline/README.md, System_Config/log_session.sh, System_Config/healthcheck.sh
                                      -- referenced, not parsed; the flow/
                                      logging/security text below is fixed
                                      policy prose describing what those
                                      files already do.

Generated vs. static: sections wrapped in <!-- gen:*-start/end --> markers
(same convention as microsite/index.html, see gen_site.py) are rebuilt from
the sources above every run. Sections outside any marker are fixed policy
prose describing mechanism that doesn't vary per fork (the gate flow
itself, the logging mechanism, the security-scan framing) -- edit those
here in the script, not by hand-patching GOVERNANCE.md.

Usage:
  python3 System_Config/gen_governance.py          # write GOVERNANCE.md
  python3 System_Config/gen_governance.py --check  # exit 1 if stale
  python3 System_Config/gen_governance.py --dry-run # preview, no write
"""
import os, re, glob, json, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
AGENTS_DIR = os.path.join(ROOT, 'agents')
ROSTER_PATH = os.path.join(SCRIPT_DIR, 'agent-roster.json')
GATE_CONFIG_PATH = os.path.join(ROOT, 'pipeline', 'gate-config.json')
PRESETS_PATH = os.path.join(SCRIPT_DIR, 'presets.json')
ACTIVE_PRESET_PATH = os.path.join(SCRIPT_DIR, '.active-preset')
OUT_PATH = os.path.join(ROOT, 'GOVERNANCE.md')

ALL_ROLES = ['architect', 'coder', 'creative-director', 'curator', 'eng-manager', 'qa']


def read_frontmatter(path):
    with open(path) as f:
        content = f.read()
    if not content.startswith('---'):
        return None
    end = content.find('---', 3)
    if end == -1:
        return None
    fm = content[3:end]
    name_m = re.search(r'^name:\s*(.+)$', fm, re.MULTILINE)
    desc_m = re.search(r'^description:\s*(.+)$', fm, re.MULTILINE)
    tools_m = re.search(r'^tools:\s*(.+)$', fm, re.MULTILINE)
    if not name_m:
        return None
    return {
        'name': name_m.group(1).strip(),
        'description': desc_m.group(1).strip() if desc_m else '',
        'tools': tools_m.group(1).strip() if tools_m else '',
    }


def get_agents():
    agents = []
    for path in sorted(glob.glob(os.path.join(AGENTS_DIR, '*.md'))):
        info = read_frontmatter(path)
        if info:
            info['rel'] = 'agents/' + os.path.basename(path)
            agents.append(info)
    return agents


def load_json_or_none(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def gate_label(gate):
    if isinstance(gate, str):
        return gate
    if isinstance(gate, dict) and gate.get('name') == 'custom':
        script = gate.get('script', '')
        return 'custom (' + (script if script else 'script unconfigured') + ')'
    return str(gate)


def get_active_preset_role_notes():
    """Look up the current fork's harness-specific role_notes overlay, if any.

    Additive to the generic per-role scope in agents/*.md, never a
    replacement -- see presets.json's role_notes field. Returns
    (None, {}, {}, {}) when unspecialized, when specialized via
    interactive/env-override (no single named preset), or when the active
    preset has no role_notes.
    """
    if not os.path.exists(ACTIVE_PRESET_PATH):
        return None, {}, {}, {}
    with open(ACTIVE_PRESET_PATH) as f:
        preset_name = f.read().strip()
    presets = load_json_or_none(PRESETS_PATH) or {}
    preset = presets.get(preset_name) or {}
    return (preset_name, preset.get('role_notes', {}),
            preset.get('role_capabilities', {}), preset.get('role_handoff', {}))


def build_roles_block(agents):
    preset_name, role_notes, role_capabilities, role_handoff = get_active_preset_role_notes()
    rows = []
    for a in agents:
        rows.append(
            '| `' + a['name'] + '` | ' + a['description'] + ' | `' + a['tools'] + '` | `' + a['rel'] + '` |'
        )
    table = (
        '| Role | Stated scope (from frontmatter `description`) | Granted tools | Source |\n'
        '|---|---|---|---|\n' + '\n'.join(rows)
    )
    if not role_notes:
        return table
    # Only overlay roles active in this fork's roster; no roster => no notes.
    roster = load_json_or_none(ROSTER_PATH) or {}
    roster_roles = roster.get('roles') or {}
    overlay_rows = []
    for a in agents:
        if (roster_roles.get(a['name']) or {}).get('active') is not True:
            continue
        note = role_notes.get(a['name'])
        if note:
            note = ' '.join(str(note).split())
            extra = ''
            caps = role_capabilities.get(a['name'])
            if caps:
                extra += ' _(capabilities: ' + ', '.join('`' + c + '`' for c in caps) + ')_'
            target = role_handoff.get(a['name'])
            if target:
                extra += ' _(hands off to: `' + target + '`)_'
            overlay_rows.append('- **`' + a['name'] + '`**: ' + note + extra)
    if not overlay_rows:
        return table
    overlay = (
        '\n\n**Harness-specific overlay — preset `' + preset_name + '`** (additive to the '
        'generic scope above, not a replacement; from `System_Config/presets.json`'
        "'s `role_notes`):\n\n" + '\n'.join(overlay_rows)
    )
    return table + overlay


def build_gate_policy_block():
    roster = load_json_or_none(ROSTER_PATH)
    gate_config = load_json_or_none(GATE_CONFIG_PATH)

    lines = []
    if roster is None and gate_config is None:
        lines.append('**This fork is unspecialized** — `System_Config/agent-roster.json` and '
                      '`pipeline/gate-config.json` are both absent. `System_Config/specialize.sh` '
                      'has not been run against a preset yet.')
        lines.append('')
        lines.append('Default behavior in this state (per `pipeline/run.sh`):')
        lines.append('- All 6 roles in `agents/` are available for orchestrator dispatch.')
        lines.append('- The pipeline gate step runs the hardcoded default pair, in order: '
                      '`eslint` (`pipeline/lib/eslint_gate.sh`), then `playwright` '
                      '(`pipeline/lib/playwright_gate.sh`).')
        return '\n'.join(lines)

    lines.append('This fork has been specialized (`System_Config/specialize.sh`). Current state:')
    lines.append('')
    if roster is not None:
        roles = roster.get('roles', {})
        lines.append('**Active roles** (`System_Config/agent-roster.json`):')
        lines.append('')
        lines.append('| Role | Active | Capabilities |')
        lines.append('|---|---|---|')
        for role in ALL_ROLES:
            r = roles.get(role, {})
            active = 'yes' if r.get('active') else 'no'
            caps = ', '.join(r.get('capabilities', [])) or '—'
            lines.append('| `' + role + '` | ' + active + ' | ' + caps + ' |')
    else:
        lines.append('**Active roles**: `System_Config/agent-roster.json` not found — all 6 roles '
                      'default active (see `pipeline/gate-config.json` below for gates alone having '
                      'been specialized).')
    lines.append('')
    if gate_config is not None:
        gates = gate_config.get('gates', [])
        lines.append('**Configured gates** (`pipeline/gate-config.json`, run in order before the human gate):')
        lines.append('')
        if not gates:
            lines.append('_No gates configured — `"gates": []` is valid and runs zero automated checks '
                          'before the human gate._')
        else:
            lines.append('| # | Gate |')
            lines.append('|---|---|')
            for i, g in enumerate(gates, 1):
                lines.append('| ' + str(i) + ' | `' + gate_label(g) + '` |')
    else:
        lines.append('**Configured gates**: `pipeline/gate-config.json` not found — `pipeline/run.sh` '
                      'falls back to the hardcoded default pair, in order: `eslint`, then `playwright`.')
    return '\n'.join(lines)


def replace_block(md, marker, new_content):
    start = '<!-- gen:' + marker + '-start -->'
    end = '<!-- gen:' + marker + '-end -->'
    pat = re.compile(re.escape(start) + r'.*?' + re.escape(end), re.DOTALL)
    return pat.sub(start + '\n' + new_content + '\n' + end, md)


STATIC_TEMPLATE = """# Governance — Agentic Light

<!-- GENERATED FILE — produced by `System_Config/gen_governance.py`. Do not
hand-edit sections inside a `<!-- gen:*-start/end -->` marker pair; they are
rebuilt from `agents/*.md`, `System_Config/agent-roster.json`, and
`pipeline/gate-config.json` every run and any manual edit is overwritten.
Text outside marker pairs is fixed policy prose maintained directly in
`gen_governance.py`, not per-fork data — edit it there. -->

This is the single place to answer: **what can an agent in this fork
actually do, and what requires a human's own explicit sign-off before it
ships?** It documents the mechanism `pipeline/run.sh` already enforces; it
does not add new mechanism.

## 1. Per-Role Scope

Pulled from each role file's own frontmatter (`description` + `tools`) in
`agents/`. This is the actual grant, not a paraphrase — see the linked file
for the full rules each role also follows (context discipline, response
style, hand-off targets).

<!-- gen:roles-start -->
{roles_block}
<!-- gen:roles-end -->

`archivist` and `rally` are excluded from the roster by design (see
`agents/README.md`) — Agentic Light has no archival pipeline and no
rally/broadcast agent.

`qa` and `eng-manager` are orchestrator-dispatched roles, not steps
`pipeline/run.sh` itself invokes — see `agents/README.md`'s "`qa` /
`eng-manager` are not part of `pipeline/run.sh`" section.

## 2. The Human Sign-Off Gate

**No code produced by this system reaches a pull request without an
explicit human approval.** This is the governance checkpoint of the whole
pipeline, enforced structurally, not by convention:

- `pipeline/run.sh` step 3, the **Human Gate** (`pipeline/lib/human_gate.sh`
  by default; `PIPELINE_HUMAN_GATE_CMD` overrides it only when
  `AGENTIC_LIGHT_TEST_MODE=1` is also set — otherwise the override is
  ignored with a warning and the real gate runs),
  renders the full diff already committed to the run's feature branch plus
  the gate-run summary, and blocks on an interactive `[y/N]` prompt.
- The gate **never auto-approves**. A non-interactive session (no TTY on
  stdin) exits `2` (pending) — the pipeline stops and creates no PR, rather
  than defaulting to yes.
- `pipeline/lib/pr_create.sh` (step 4, `gh pr create --draft`) is only ever
  called after the Human Gate returns approval (`0`). Every other exit path
  — a failed gate, a declined human gate, a pending non-interactive gate —
  hard-stops before this step; see `pipeline/README.md`'s "Halt-on-failure
  guarantee" and "Human Gate exit codes".
- Every configured gate (ESLint/Playwright/axe, or the fork's own
  `gate-config.json` list — see §4 below) must pass, or be skipped via its
  own documented no-op condition, **before** the human ever sees the diff.
  A failing gate is a hard stop, not a warning shown alongside the PR.

## 3. Audit Trail — What Gets Logged, and Where

- **`System_Config/log_session.sh`** — called exactly once per coder
  invocation, after the coder step, regardless of outcome (success, watchdog
  timeout, or an Ollama write-workflow refusal). Appends one line —
  provider, role, exit status, reason — under `## Agent Sessions` in the
  current ISO week's weekly note (`brain/weekly_logs/YYYY/YYYY-Www.md`).
  This is the append-only session record: every coder invocation, whether
  it made it to a PR or not, leaves a trace.
- **`pipeline/logs/<run-id>.log`** — the full run, gate output included, is
  teed to a per-run log file (`RUN_ID="$(date +%Y%m%d-%H%M%S)-$$"`). This is
  the gate-run history: what ran, in what order, and whether it passed.
- **`System_Config/healthcheck.sh`**'s "Pipeline Logs" layer reports log
  recency (WARN on a fresh scaffold with zero runs yet, PASS once any exist)
  so a stalled/idle pipeline is visible in the health dashboard, not just in
  a directory listing.

## 4. Gate Policy — This Fork's Current State

Reflects the actual specialization state of **this** clone/fork, not a
generic description — regenerated from `System_Config/agent-roster.json`
and `pipeline/gate-config.json` (or their absence) every run.

<!-- gen:gate-policy-start -->
{gate_policy_block}
<!-- gen:gate-policy-end -->

Run `bash System_Config/specialize.sh --preset <name>` (see
`System_Config/presets.json` for the list) to change this fork's active
roles/gates, then re-run `python3 System_Config/gen_governance.py` to
refresh this section.

## 5. Config Security

`System_Config/healthcheck.sh`'s **Layer G — Config Security Scan** is part
of this governance layer, not a separate concern: it greps the project's own
config surface (`System_Config/*.sh`, `System_Config/*.json`, `.mcp.json`,
any `.env*`, `.agentic-light.conf`) for credential-shaped strings (known
provider key prefixes, bearer tokens, `*_KEY`/`*_TOKEN`/`*_SECRET`
assignments that aren't placeholders), and WARNs on any hit that isn't
already covered by `.gitignore`. It also asserts that files documented as
local-only (`.mcp.json`, `.agentic-light.conf`,
`System_Config/.notify.env`) are in fact gitignored. Run it directly with
`bash System_Config/healthcheck.sh`, or read the "Config Security Scan"
section of the generated `microsite/health.html`.

## See also

- `pipeline/README.md` — the full gate -> human-gate -> PR flow, gate
  configuration schema, concurrency lock, and test coverage.
- `agents/README.md` — full roster table and hand-off graph.
- `System_Config/README.md` — script-by-script reference, including
  `healthcheck.sh` and `log_session.sh`.
- `System_Config/agent-roster.schema.json` / `gate-config.schema.json` —
  the schemas §1/§4 validate against.
"""


def build_markdown():
    agents = get_agents()
    return STATIC_TEMPLATE.format(
        roles_block=build_roles_block(agents),
        gate_policy_block=build_gate_policy_block(),
    )


def main():
    check_mode = '--check' in sys.argv
    dry_run = '--dry-run' in sys.argv

    new_md = build_markdown()

    original = None
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            original = f.read()

    if original == new_md:
        print('gen_governance: GOVERNANCE.md is already up to date.')
        sys.exit(0)

    if check_mode:
        print('gen_governance: GOVERNANCE.md is STALE -- run python3 System_Config/gen_governance.py to update.')
        sys.exit(1)

    if dry_run:
        import difflib
        old_lines = (original or '').splitlines()
        diff = difflib.unified_diff(old_lines, new_md.splitlines(), lineterm='', n=2)
        print('\n'.join(list(diff)[:80]))
        sys.exit(0)

    with open(OUT_PATH, 'w') as f:
        f.write(new_md)
    print('gen_governance: updated ' + OUT_PATH)


if __name__ == '__main__':
    main()
