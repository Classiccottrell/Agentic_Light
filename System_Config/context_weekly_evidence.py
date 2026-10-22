#!/usr/bin/env python3
"""Build a private foreground packet from verified, timestamped Claude snapshots."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import context_weekly as weekly

MARKER = b'<!-- context-weekly-evidence: generated v1 -->\n'
MAX_INPUT = 8 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_ROW = 32768
MAX_EXCERPTS = 64
MAX_TEXT = 512


def safe_directories(path):
    for parent in reversed((path, *path.parents)):
        weekly.directory(parent, 'evidence directory')


def excerpts(data, start, end, zone, counts):
    for raw in data.splitlines():
        if len(raw) > MAX_ROW:
            counts['gaps'] += 1
            continue
        try:
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError()
            if row.get('isMeta') or row.get('type') not in ('user', 'assistant'):
                continue
            stamp = row.get('timestamp')
            if not isinstance(stamp, str):
                raise ValueError()
            timestamp = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError()
            day = timestamp.astimezone(zone).date()
            if not start <= day <= end:
                continue
            message = row.get('message')
            if not isinstance(message, dict) or message.get('role') != row['type']:
                raise ValueError()
            content = message.get('content')
            if isinstance(content, list):
                content = '\n'.join(block['text'] for block in content if isinstance(block, dict)
                                    and block.get('type') == 'text' and isinstance(block.get('text'), str))
            if not isinstance(content, str) or not content.strip():
                raise ValueError()
            if counts['excerpts'] >= MAX_EXCERPTS:
                counts['gaps'] += 1
                continue
            text = ' '.join(content.split())
            if len(text) > MAX_TEXT:
                counts['gaps'] += 1
            # Render transcript text as inert Markdown, never as source-supplied links or HTML.
            text = text[:MAX_TEXT].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            for character in ('\\', '`', '*', '_', '[', ']'):
                text = text.replace(character, '\\' + character)
            counts['excerpts'] += 1
            yield f"> {day.isoformat()} {row['type']}: {text}"
        except (ValueError, TypeError, OverflowError, UnicodeError):
            counts['gaps'] += 1


def publish(vault_path, week, classification, timezone):
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        weekly.fail('invalid timezone')
    start, end = weekly.week_bounds(week)
    vault = Path(os.path.abspath(vault_path))
    weekly.directory(vault, 'vault')
    vault = vault.resolve()
    safe_directories(vault)
    records = weekly.selected_records(vault, week)
    selected = {}
    for record in records:
        if record['classification'] == classification:
            selected.setdefault((record['provider'], record['hash']), record)
    output = vault / 'context/weekly-evidence' / f'{week}-{classification}.md'
    if os.path.lexists(output.parent):
        safe_directories(output.parent)
    counts = {'sources': len(selected), 'excerpts': 0, 'gaps': 0, 'unsupported_date_unknown': 0}
    lines = [MARKER.decode().rstrip(), f'# Weekly activity evidence — {week} — {classification}', '',
             f'Timezone: {timezone}. Sources observed during {week}; observation dates do not establish activity dates.', '',
             'Private excerpts; review before sharing. Coverage is limited to the selected observation week.', '']
    total = 0
    for record in selected.values():
        lines.append(f"- [[source-records/{record['stem']}|{record['provider']} source record]]")
        if record['provider'] != 'claude':
            counts['unsupported_date_unknown'] += 1
            continue
        staging = vault / 'context/mempalace-staging'
        if not os.path.lexists(staging):
            counts['gaps'] += 1
            continue
        safe_directories(staging)
        snapshot = staging / f"claude-{record['hash'][:12]}.jsonl"
        if not os.path.lexists(snapshot):
            counts['gaps'] += 1
            continue
        info = weekly.regular(snapshot, 'snapshot')
        if info.st_mode & 0o077:
            weekly.fail('snapshot is not private')
        if info.st_size > MAX_INPUT or total + info.st_size > MAX_TOTAL:
            counts['gaps'] += 1
            continue
        data = weekly.read_bytes(snapshot, 'snapshot', MAX_INPUT)
        total += len(data)
        if hashlib.sha256(data).hexdigest() != record['hash']:
            weekly.fail('snapshot hash mismatch')
        lines.extend(excerpts(data, start, end, zone, counts))
    if not counts['excerpts']:
        lines.extend(('', 'No verified activity evidence for this week.'))
    lines.extend(('', 'Coverage: ' + json.dumps(counts, sort_keys=True),
                  'Gaps count missing/oversized snapshots, invalid or oversized rows, and truncated/omitted excerpts.',
                  'Unsupported/date-unknown sources contribute no content.', ''))
    data = '\n'.join(lines).encode('utf-8')
    if len(data) > 65536:
        weekly.fail('packet exceeds limit')
    prior = weekly.generated_archive(output, MARKER, 'weekly evidence')
    output.parent.mkdir(parents=True, exist_ok=True)
    safe_directories(output.parent)
    weekly.write_generated(output, prior, data, MARKER, 'weekly evidence')
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True)
    parser.add_argument('--week', required=True)
    parser.add_argument('--classification', required=True, choices=weekly.CLASSIFICATIONS)
    parser.add_argument('--timezone', default='UTC', help='IANA timezone (default: UTC)')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(publish(args.vault, args.week, args.classification, args.timezone), sort_keys=True))
    except (ValueError, OSError):
        print('context weekly evidence failed: invalid input or protected destination', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
