#!/usr/bin/env python3
"""Build selected weekly activity evidence from verified private Claude, Codex, and Antigravity snapshots."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import context_weekly as weekly

MARKER = b'<!-- context-weekly-evidence: generated v1 -->\n'
MAX_INPUT = 32 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_ROW = 32768
# Sixteen excerpts leave room below 64 KiB even when each character expands to five bytes.
MAX_EXCERPTS = 16
MAX_SOURCES = 12
MAX_TEXT = 512
# Codex injects these into user-role messages; they are system context, not human activity.
REQUEST = re.compile(r'<USER_REQUEST>(.*?)</USER_REQUEST>', re.DOTALL)
AGY_INJECTED = re.compile(r'<(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE)>')
INJECTED = ('<environment_context', '<hook_prompt', '<image', '# AGENTS.md instructions')


def safe_directories(path):
    for parent in reversed((path, *path.parents)):
        weekly.directory(parent, 'evidence directory')


def stamped_day(row, zone, field='timestamp'):
    stamp = row.get(field)
    if not isinstance(stamp, str):
        raise ValueError()
    timestamp = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError()
    return timestamp.astimezone(zone).date()


def claude_messages(data, start, end, zone, counts):
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
            day = stamped_day(row, zone)
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
            yield day, row['type'], content
        except (ValueError, TypeError, OverflowError, UnicodeError):
            counts['gaps'] += 1


def codex_messages(data, start, end, zone, counts):
    """Yield dated Codex rollout messages.

    Every rollout row carries its own UTC timestamp. A forked rollout replays its parent's
    history with fresh timestamps, so rows before the first session_meta's
    subagent_history_start_ordinal are undated and never counted. Only response_item
    messages from user/assistant count; injected context and assistant commentary do not.
    """
    lines = data.splitlines()
    first = None
    try:
        if lines and len(lines[0]) <= MAX_ROW:
            first = json.loads(lines[0])
        meta = first['payload'] if first['type'] == 'session_meta' else None
        if not isinstance(meta, dict):
            raise ValueError()
        history_start = None
        if 'forked_from_id' in meta:
            history_start = meta.get('subagent_history_start_ordinal')
            if not isinstance(history_start, int) or isinstance(history_start, bool) or history_start < 0:
                raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError):
        # No readable fork authority: nothing in this file can be dated.
        counts['gaps'] += 1
        counts['undated'] += 1
        return
    label_user = 'delegated-prompt' if meta.get('parent_thread_id') else 'user'
    for raw in lines[1:]:
        if len(raw) > MAX_ROW:
            try:
                item = json.loads(raw)
                payload = item.get('payload') if isinstance(item, dict) else None
                if (not isinstance(payload, dict) or item.get('type') != 'response_item'
                        or payload.get('type') != 'message' or payload.get('role') not in ('user', 'assistant')):
                    continue
            except (ValueError, TypeError, UnicodeError):
                pass
            counts['gaps'] += 1
            continue
        try:
            row = json.loads(raw)
            payload = row.get('payload') if isinstance(row, dict) else None
            if (not isinstance(payload, dict) or row.get('type') != 'response_item' or payload.get('type') != 'message'
                    or payload.get('role') not in ('user', 'assistant')):
                continue
            role = payload['role']
            if history_start is not None:
                ordinal = row.get('ordinal')
                if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < history_start:
                    counts['undated'] += 1
                    continue
            day = stamped_day(row, zone)
            if not start <= day <= end:
                continue
            if role == 'assistant' and payload.get('phase') == 'commentary':
                continue
            blocks = payload.get('content')
            if not isinstance(blocks, list):
                raise ValueError()
            kind = 'input_text' if role == 'user' else 'output_text'
            texts = [block['text'] for block in blocks if isinstance(block, dict)
                     and block.get('type') == kind and isinstance(block.get('text'), str)]
            kept = [text for text in texts if not text.lstrip().startswith(INJECTED)]
            counts['injected_excluded'] += len(texts) - len(kept)
            if not texts:
                raise ValueError()
            if kept:
                yield day, label_user if role == 'user' else role, '\n'.join(kept)
        except (ValueError, TypeError, OverflowError, UnicodeError):
            counts['gaps'] += 1


def antigravity_messages(data, start, end, zone, counts):
    """Yield dated Antigravity CLI transcript.jsonl messages.

    The log (brain/<id>/.system_generated/logs/transcript.jsonl) is an undocumented internal
    format that may change between versions. Each row has its own created_at. Only
    USER_EXPLICIT/USER_INPUT requests and MODEL/PLANNER_RESPONSE text count; thinking, tool
    calls, SYSTEM rows, and injected metadata/settings blocks never do. Most prompts are
    automated (headless agy runs), so they are labeled 'prompt', not 'user'.
    """
    for raw in data.splitlines():
        if len(raw) > MAX_ROW:
            counts['gaps'] += 1
            continue
        try:
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError()
            kind = (row.get('source'), row.get('type'))
            if kind not in (('USER_EXPLICIT', 'USER_INPUT'), ('MODEL', 'PLANNER_RESPONSE')):
                continue
            day = stamped_day(row, zone, 'created_at')
            if not start <= day <= end:
                continue
            content = row.get('content')
            if not isinstance(content, str):
                if kind[1] == 'USER_INPUT':
                    raise ValueError()
                continue  # tool-only planner steps carry no text
            truncated = row.get('truncated_fields')
            if truncated and (not isinstance(truncated, list) or 'content' in truncated):
                raise ValueError()
            if kind[1] == 'USER_INPUT':
                bodies = REQUEST.findall(content)
                if len(bodies) != 1:
                    raise ValueError()
                counts['injected_excluded'] += len(AGY_INJECTED.findall(content))
                yield day, 'prompt', bodies[0]
            else:
                yield day, 'assistant', content
        except (ValueError, TypeError, OverflowError, UnicodeError):
            counts['gaps'] += 1


PROVIDERS = {'claude': claude_messages, 'codex': codex_messages, 'antigravity': antigravity_messages}


def excerpts(messages, counts, quota):
    emitted = 0
    for day, label, content in messages:
        if not content.strip():
            counts['gaps'] += 1
            continue
        if emitted >= quota:
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
        emitted += 1
        yield f"> {day.isoformat()} {label}: {text}"


def publish(vault_path, week, classification, timezone, sources):
    if not sources or len(sources) > MAX_SOURCES:
        weekly.fail('select between one and twelve source records')
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
    available = {record['stem']: record for record in records if record['classification'] == classification}
    selected = {}
    for stem in sources:
        if stem not in available:
            weekly.fail('source not observed in selected week and classification')
        record = available[stem]
        selected.setdefault((record['provider'], record['hash']), record)
    output = vault / 'context/weekly-evidence' / f'{week}-{classification}.md'
    if os.path.lexists(output.parent):
        safe_directories(output.parent)
    counts = {'selected_source_records': len(set(sources)), 'sources': len(selected), 'excerpts': 0, 'gaps': 0, 'unsupported_date_unknown': 0, 'undated': 0, 'injected_excluded': 0}
    lines = [MARKER.decode().rstrip(), f'# Selected weekly activity evidence — {week} — {classification}', '',
             f'Timezone: {timezone}. Sources observed during {week}; observation dates do not establish activity dates.', '',
             'Private excerpts; review before sharing. Coverage includes only explicitly selected sources; automatic full-week coverage remains open.', '']
    total = 0
    for record in selected.values():
        lines.append(f"- [[source-records/{record['stem']}|{record['provider']} source record]]")
        if record['provider'] not in PROVIDERS:
            counts['unsupported_date_unknown'] += 1
            continue
        staging = vault / 'context/mempalace-staging'
        if not os.path.lexists(staging):
            counts['gaps'] += 1
            continue
        safe_directories(staging)
        snapshot = staging / f"{record['provider']}-{record['hash'][:12]}.jsonl"
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
        messages = PROVIDERS[record['provider']](data, start, end, zone, counts)
        lines.extend(excerpts(messages, counts, max(1, MAX_EXCERPTS // len(selected))))
    if not counts['excerpts']:
        lines.extend(('', 'No verified activity evidence for this week.'))
    lines.extend(('', 'Coverage: ' + json.dumps(counts, sort_keys=True),
                  'Gaps count missing/oversized snapshots, invalid rows, oversized message rows, and truncated/omitted excerpts.',
                  'Undated counts Codex rows or files whose timestamps cannot be tied to their own activity (forked-history replays, unreadable fork header).',
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
    parser.add_argument('--source', required=True, action='append', help='source-record stem; repeat up to twelve times')
    parser.add_argument('--timezone', default='UTC', help='IANA timezone (default: UTC)')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(publish(args.vault, args.week, args.classification, args.timezone, args.source), sort_keys=True))
    except (ValueError, OSError):
        print('context weekly evidence failed: invalid input or protected destination', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
