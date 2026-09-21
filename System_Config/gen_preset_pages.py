#!/usr/bin/env python3
"""
gen_preset_pages.py -- generate one microsite page per fork-specialization
preset, plus the index.html preset index table, from presets.json.

Sources:
  System_Config/presets.json              -- roles/gates/skills/description per preset
  System_Config/agent-roster.schema.json  -- fixed 6-role set (canonical order)
  microsite/template.html                 -- page scaffold (CSS + header/footer)

Outputs:
  microsite/presets/<name>.html   -- one page per preset (overwritten each run)
  microsite/index.html            -- <!-- gen:presets-start/end --> table refreshed

Usage:
  python3 System_Config/gen_preset_pages.py          # write pages + index.html
  python3 System_Config/gen_preset_pages.py --check  # exit 1 if anything is stale
  python3 System_Config/gen_preset_pages.py --dry-run # preview, no write
"""
import os, re, json, sys, html as html_mod

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
PRESETS_PATH = os.path.join(SCRIPT_DIR, 'presets.json')
ROSTER_SCHEMA_PATH = os.path.join(SCRIPT_DIR, 'agent-roster.schema.json')
TEMPLATE_PATH = os.path.join(ROOT, 'microsite', 'template.html')
INDEX_PATH = os.path.join(ROOT, 'microsite', 'index.html')
PRESETS_DIR = os.path.join(ROOT, 'microsite', 'presets')


def get_roles():
    with open(ROSTER_SCHEMA_PATH) as f:
        schema = json.load(f)
    return list(schema['properties']['roles']['properties'].keys())


def gate_label(gate):
    if isinstance(gate, str):
        return gate
    if isinstance(gate, dict) and gate.get('name') == 'custom':
        script = gate.get('script', '')
        return 'custom (' + (script if script else 'script unconfigured') + ')'
    return str(gate)


def build_roster_table(active_roles, all_roles):
    rows = []
    for role in all_roles:
        mark = '&#10003; active' if role in active_roles else '&#8212; inactive'
        rows.append('              <tr><td><code>' + html_mod.escape(role) + '</code></td><td>' + mark + '</td></tr>')
    return (
        '        <table>\n'
        '          <thead><tr><th>Role</th><th>Status</th></tr></thead>\n'
        '          <tbody>\n' + '\n'.join(rows) + '\n'
        '          </tbody>\n'
        '        </table>'
    )


def build_gate_table(gates):
    if not gates:
        return '        <p><em>No default gates configured for this preset.</em></p>'
    rows = []
    for g in gates:
        rows.append('              <tr><td><code>' + html_mod.escape(gate_label(g)) + '</code></td></tr>')
    return (
        '        <table>\n'
        '          <thead><tr><th>Gate</th></tr></thead>\n'
        '          <tbody>\n' + '\n'.join(rows) + '\n'
        '          </tbody>\n'
        '        </table>'
    )


def build_skills_note(preset):
    skills = preset.get('skills', [])
    if skills == '*':
        return '<p>Selects <strong>all</strong> shipped skill dirs under <code>skills/</code>.</p>'
    gap_note = preset.get('skills_gap_note', '')
    if not skills:
        if gap_note:
            return '<p>No skill dirs selected &#8212; ' + html_mod.escape(gap_note) + '.</p>'
        return '<p>No skill dirs selected for this preset.</p>'
    items = ''.join('<li><code>' + html_mod.escape(s) + '</code></li>' for s in skills)
    return '<ul>' + items + '</ul>'


def build_flowchart(active_roles, gates):
    steps = ['Task in'] + list(active_roles) + (['Gate: ' + ', '.join(gate_label(g) for g in gates)] if gates else ['No automated gate']) + ['Human gate', 'PR']
    escaped = [html_mod.escape(s) for s in steps]
    return '\n'.join(escaped[i] + '\n  |\n  v' if i < len(escaped) - 1 else escaped[i] for i, _ in enumerate(escaped))


def render_page(name, preset, all_roles, template):
    active_roles = preset.get('roles', [])
    gates = preset.get('gates', [])
    description = html_mod.escape(preset.get('description', ''))
    name_esc = html_mod.escape(name)

    html = template.replace('href="index.html"', 'href="../index.html"')
    html = html.replace('href="health.html"', 'href="../health.html"')
    html = html.replace(
        '<!-- HEADER: wordmark always points at microsite/index.html — every page in this microsite is a sibling. -->',
        '<!-- HEADER: wordmark points at ../index.html — preset pages live one level down in microsite/presets/. -->'
    )
    html = html.replace('<title>Page Title — Agentic Light</title>',
                         '<title>' + name_esc + ' — Agentic Light</title>')

    body = (
        '        <p class="eyebrow">// specialization preset</p>\n'
        '        <h1>' + name_esc + '</h1>\n'
        '        <p class="lede">' + description + '</p>\n'
        '\n'
        '        <h2>Roster</h2>\n' + build_roster_table(active_roles, all_roles) + '\n'
        '\n'
        '        <h2>Gates</h2>\n' + build_gate_table(gates) + '\n'
        '\n'
        '        <h2>Skills</h2>\n        ' + build_skills_note(preset) + '\n'
        '\n'
        '        <h2>Task Flow</h2>\n'
        '        <pre><code>' + build_flowchart(active_roles, gates) + '</code></pre>\n'
        '\n'
        '        <p>Run <code>System_Config/specialize.sh --preset ' + name_esc + '</code> to apply this preset.</p>'
    )

    old_content = (
        '        <p class="eyebrow">// category name</p>\n'
        '        <h1>Page Title</h1>\n'
        '        <p class="lede">A 1-2 sentence introduction that explains what this page covers.</p>\n'
        '\n'
        '        <h2>First section</h2>\n'
        '        <p>Paragraph text goes here. Use <code>code</code> for inline code, <strong>strong</strong> for emphasis.</p>'
    )
    html = html.replace(old_content, body)
    html = html.replace('agentic-light · Page Name · <a href="../index.html">home</a> · <a href="../health.html">health</a>',
                         'agentic-light · ' + name_esc + ' · <a href="../index.html">home</a> · <a href="../health.html">health</a>')
    return html


def build_index_table(presets):
    rows = []
    for name in sorted(presets):
        p = presets[name]
        name_esc = html_mod.escape(name)
        rows.append(
            '              <tr><td><code>' + name_esc + '</code></td><td>' + html_mod.escape(p.get('description', '')) +
            '</td><td><a href="presets/' + name_esc + '.html">presets/' + name_esc + '.html</a></td></tr>'
        )
    return (
        '        <table>\n'
        '          <thead><tr><th>Preset</th><th>Description</th><th>Page</th></tr></thead>\n'
        '          <tbody>\n' + '\n'.join(rows) + '\n'
        '          </tbody>\n'
        '        </table>'
    )


def replace_block(html, marker, new_content):
    start = '<!-- gen:' + marker + '-start -->'
    end = '<!-- gen:' + marker + '-end -->'
    pat = re.compile(re.escape(start) + r'.*?' + re.escape(end), re.DOTALL)
    return pat.sub(start + '\n' + new_content + '\n' + end, html)


def main():
    check_mode = '--check' in sys.argv
    dry_run = '--dry-run' in sys.argv

    with open(PRESETS_PATH) as f:
        presets = json.load(f)
    all_roles = get_roles()
    with open(TEMPLATE_PATH) as f:
        template = f.read()

    stale = False
    written = []
    removed = []

    if os.path.isdir(PRESETS_DIR):
        expected = set(name + '.html' for name in presets)
        for fname in sorted(os.listdir(PRESETS_DIR)):
            if fname.endswith('.html') and fname not in expected:
                removed.append(os.path.join(PRESETS_DIR, fname))

    if not check_mode and not dry_run and (presets or removed):
        os.makedirs(PRESETS_DIR, exist_ok=True)

    for name, preset in presets.items():
        out_path = os.path.join(PRESETS_DIR, name + '.html')
        new_html = render_page(name, preset, all_roles, template)
        existing = None
        if os.path.exists(out_path):
            with open(out_path) as f:
                existing = f.read()
        if existing != new_html:
            stale = True
            written.append(out_path)
            if not check_mode and not dry_run:
                with open(out_path, 'w') as f:
                    f.write(new_html)

    if removed:
        stale = True
        if not check_mode and not dry_run:
            for p in removed:
                os.remove(p)

    with open(INDEX_PATH) as f:
        index_html = f.read()
    new_index_html = replace_block(index_html, 'presets', build_index_table(presets))
    if new_index_html != index_html:
        stale = True
        written.append(INDEX_PATH)
        if not check_mode and not dry_run:
            with open(INDEX_PATH, 'w') as f:
                f.write(new_index_html)

    if not stale:
        print('gen_preset_pages: all preset pages already up to date.')
        sys.exit(0)

    if check_mode:
        print('gen_preset_pages: STALE -- run python3 System_Config/gen_preset_pages.py to update.')
        for p in written:
            print('  ' + p)
        for p in removed:
            print('  ' + p + ' (orphaned)')
        sys.exit(1)

    if dry_run:
        print('gen_preset_pages: would update:')
        for p in written:
            print('  ' + p)
        for p in removed:
            print('  ' + p + ' (would remove -- orphaned)')
        sys.exit(0)

    print('gen_preset_pages: updated ' + str(len(written)) + ' file(s), removed ' + str(len(removed)) + ' orphan(s).')
    for p in written:
        print('  ' + p)
    for p in removed:
        print('  removed ' + p)


if __name__ == '__main__':
    main()
