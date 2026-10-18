#!/usr/bin/env python3
"""
gen_site.py -- keep the microsite dashboard in sync with the agent/skill/preset
roster. microsite/index.html is a static compatibility redirect to it.

Managed sections:
  dashboard.html: <!-- gen:dashboard-presets-start/end -->
                  <!-- gen:dashboard-roster-head-start/end -->
                  <!-- gen:dashboard-roster-body-start/end -->

Sources:
  agents/*.md         -- core agents: name + description from YAML frontmatter
  skills/*/SKILL.md   -- name + description from YAML frontmatter

Usage:
  python3 System_Config/gen_site.py          # update microsite/dashboard.html in place
  python3 System_Config/gen_site.py --check  # exit 1 if site is stale (healthcheck)
  python3 System_Config/gen_site.py --dry-run # print what would change, no write
"""
import html
import json
import os, re, glob, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
AGENTS_DIR = os.path.join(ROOT, 'agents')
SKILLS_DIR = os.path.join(ROOT, 'skills')
DASHBOARD_PATH = os.path.join(ROOT, 'microsite', 'dashboard.html')
PRESETS_PATH = os.path.join(SCRIPT_DIR, 'presets.json')
ROSTER_SCHEMA_PATH = os.path.join(SCRIPT_DIR, 'agent-roster.schema.json')


def read_frontmatter(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if not content.startswith('---'):
        return None
    end = content.find('---', 3)
    if end == -1:
        return None
    fm = content[3:end]
    name_m = re.search(r'^name:\s*(.+)$', fm, re.MULTILINE)
    desc_m = re.search(r'^description:\s*(.+)$', fm, re.MULTILINE)
    if not name_m:
        return None
    desc = desc_m.group(1).strip() if desc_m else ''
    short = re.split(r'[.;]', desc)[0].strip()
    if len(short) > 80:
        short = short[:77] + '...'
    return {'name': name_m.group(1).strip(), 'short_desc': short}


def get_agents():
    agents = []
    for path in sorted(glob.glob(os.path.join(AGENTS_DIR, '*.md'))):
        info = read_frontmatter(path)
        if info:
            info['rel'] = 'agents/' + os.path.basename(path)
            agents.append(info)
    return agents


def get_skills():
    skills = []
    for path in sorted(glob.glob(os.path.join(SKILLS_DIR, '*', 'SKILL.md'))):
        info = read_frontmatter(path)
        if info:
            info['rel'] = 'skills/' + os.path.basename(os.path.dirname(path)) + '/SKILL.md'
            skills.append(info)
    return skills


def get_presets():
    with open(PRESETS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_roles():
    with open(ROSTER_SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    return list(schema['properties']['roles']['properties'].keys())


def build_roster_rows(rows):
    out = []
    for a in rows:
        out.append(
            '              <tr><td><code>' + a['name'] + '</code></td><td>' +
            a['short_desc'] + '</td><td><code>' + a['rel'] + '</code></td></tr>'
        )
    return '\n'.join(out)


def build_agents_block(agents):
    return (
        '        <h3>Core Agents</h3>\n'
        '        <table>\n'
        '          <thead><tr><th>Agent</th><th>Scope</th><th>File</th></tr></thead>\n'
        '          <tbody>\n' + build_roster_rows(agents) + '\n'
        '          </tbody>\n'
        '        </table>'
    )


def build_skills_block(skills):
    if not skills:
        return '        <p><em>No skills registered yet.</em></p>'
    return (
        '        <table>\n'
        '          <thead><tr><th>Skill</th><th>Purpose</th><th>File</th></tr></thead>\n'
        '          <tbody>\n' + build_roster_rows(skills) + '\n'
        '          </tbody>\n'
        '        </table>'
    )


def build_dashboard_presets(presets):
    cards = []
    for name in sorted(presets):
        safe_name = html.escape(name)
        description = html.escape(presets[name].get('description', ''))
        cards.append(
            '            <a class="preset-card" href="presets/' + safe_name + '.html">\n'
            '                <span class="pname">' + safe_name + '</span>\n'
            '                <p class="pdesc">' + description + '</p>\n'
            '            </a>'
        )
    return '\n'.join(cards)


def build_dashboard_roster_head(presets):
    return '              <th>Role</th>' + ''.join(
        '<th>' + html.escape(name) + '</th>' for name in sorted(presets)
    )


def build_dashboard_roster_body(presets, roles):
    rows = []
    for role in roles:
        cells = []
        for name in sorted(presets):
            active = role in presets[name].get('roles', [])
            cells.append('<td class="' + ('on' if active else 'off') + '">' +
                         ('&#10003;' if active else '&#8212;') + '</td>')
        rows.append('              <tr><td>' + html.escape(role) + '</td>' +
                    ''.join(cells) + '</tr>')
    return '\n'.join(rows)


def replace_block(html, marker, new_content):
    start = '<!-- gen:' + marker + '-start -->'
    end = '<!-- gen:' + marker + '-end -->'
    pat = re.compile(re.escape(start) + r'.*?' + re.escape(end), re.DOTALL)
    return pat.sub(start + '\n' + new_content + '\n' + end, html)


def replace_inline(html, marker, new_val):
    pat = re.compile(r'<!-- gen:' + re.escape(marker) + r' -->.*?<!-- /gen:' + re.escape(marker) + r' -->', re.DOTALL)
    return pat.sub('<!-- gen:' + marker + ' -->' + new_val + '<!-- /gen:' + marker + ' -->', html)


def main():
    check_mode = '--check' in sys.argv
    dry_run = '--dry-run' in sys.argv

    with open(DASHBOARD_PATH, encoding="utf-8") as f:
        dashboard_original = f.read()

    presets = get_presets()
    roles = get_roles()
    dashboard = replace_block(dashboard_original, 'dashboard-presets', build_dashboard_presets(presets))
    dashboard = replace_block(dashboard, 'dashboard-roster-head', build_dashboard_roster_head(presets))
    dashboard = replace_block(dashboard, 'dashboard-roster-body', build_dashboard_roster_body(presets, roles))

    if dashboard == dashboard_original:
        print('gen_site: site is already up to date.')
        sys.exit(0)

    if check_mode:
        print('gen_site: site is STALE -- run python3 System_Config/gen_site.py to update.')
        sys.exit(1)

    if dry_run:
        import difflib
        diffs = list(difflib.unified_diff(dashboard_original.splitlines(), dashboard.splitlines(), fromfile=DASHBOARD_PATH, tofile=DASHBOARD_PATH, lineterm='', n=2))
        print('\n'.join(diffs[:120]))
        sys.exit(0)

    if dashboard != dashboard_original:
        with open(DASHBOARD_PATH, 'w', encoding="utf-8", newline="\n") as f:
            f.write(dashboard)
    print('gen_site: updated generated microsite pages')
    print('  dashboard: ' + DASHBOARD_PATH)
    print('  presets: ' + str(len(presets)) + '  roles: ' + str(len(roles)))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
