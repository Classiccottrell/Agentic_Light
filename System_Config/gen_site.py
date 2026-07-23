#!/usr/bin/env python3
"""
gen_site.py -- keep microsite/index.html in sync with the agent/skill roster.

Managed sections:
  <!-- gen:agents-start --> ... <!-- gen:agents-end -->
  <!-- gen:skills-start --> ... <!-- gen:skills-end -->
  inline: <!-- gen:agent-count -->N<!-- /gen:agent-count -->
  inline: <!-- gen:skills-count -->N<!-- /gen:skills-count -->

Sources:
  agents/*.md         -- core agents: name + description from YAML frontmatter
  skills/*/SKILL.md   -- name + description from YAML frontmatter

Usage:
  python3 System_Config/gen_site.py          # update microsite/index.html in place
  python3 System_Config/gen_site.py --check  # exit 1 if site is stale (healthcheck)
  python3 System_Config/gen_site.py --dry-run # print what would change, no write
"""
import os, re, glob, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
AGENTS_DIR = os.path.join(ROOT, 'agents')
SKILLS_DIR = os.path.join(ROOT, 'skills')
HTML_PATH = os.path.join(ROOT, 'microsite', 'index.html')


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

    with open(HTML_PATH) as f:
        original = f.read()

    html = original
    agents = get_agents()
    skills = get_skills()
    roster_total = len(agents)

    html = replace_block(html, 'agents', build_agents_block(agents))
    html = replace_block(html, 'skills', build_skills_block(skills))
    html = replace_inline(html, 'agent-count', str(roster_total))
    html = replace_inline(html, 'skills-count', str(len(skills)))

    if html == original:
        print('gen_site: site is already up to date.')
        sys.exit(0)

    if check_mode:
        print('gen_site: site is STALE -- run python3 System_Config/gen_site.py to update.')
        sys.exit(1)

    if dry_run:
        import difflib
        diff = difflib.unified_diff(original.splitlines(), html.splitlines(), lineterm='', n=2)
        print('\n'.join(list(diff)[:80]))
        sys.exit(0)

    with open(HTML_PATH, 'w') as f:
        f.write(html)
    print('gen_site: updated ' + HTML_PATH)
    print('  agents: ' + str(roster_total) + '  skills: ' + str(len(skills)))


if __name__ == '__main__':
    main()
