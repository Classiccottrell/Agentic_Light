#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('context_weekly_evidence.py')

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / 'brain'
        (self.vault / 'context/source-records').mkdir(parents=True)
        self.output = self.vault / 'context/weekly-evidence/2026-W43-work.md'

    def source(self, rows, provider='claude', classification='work', day='2026-10-20'):
        data = b'\n'.join(json.dumps(row).encode() for row in rows) + b'\n'
        digest = hashlib.sha256(data).hexdigest()
        name = f'{provider}-{digest[:12]}-{day}'
        (self.vault / f'context/source-records/{name}.md').write_text(
            f'---\ngenerated: context-intake-v1\nprovider: {provider}\nage: current\nclassification: {classification}\nstatus: captured\ndate: {day}\n---\n<!-- generated-context-intake-v1 -->\nprivate-source:sha256:{digest}\n', encoding='utf-8')
        staging = self.vault / 'context/mempalace-staging'
        staging.mkdir(exist_ok=True)
        path = staging / f'{provider}-{digest[:12]}.jsonl'
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    def row(self, stamp, text='included', role='user'):
        return {'type': role, 'timestamp': stamp, 'message': {'role': role, 'content': text}, 'private': 'METADATA_SECRET'}

    def invoke(self, expected=0, zone='UTC', sources=None):
        if sources is None:
            sources = [path.stem for path in (self.vault / 'context/source-records').glob('*.md') if 'classification: work' in path.read_text(encoding='utf-8')]
        source_args = [value for source in sources for value in ('--source', source)]
        result = subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.vault), '--week', '2026-W43', '--classification', 'work', '--timezone', zone, *source_args], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn(str(self.vault), result.stdout + result.stderr)
        self.assertNotIn('included', result.stdout + result.stderr)
        self.assertNotIn('METADATA_SECRET', result.stdout + result.stderr)
        return json.loads(result.stdout) if not expected else None

    def test_historical_observation_is_not_activity(self):
        self.source([self.row('2026-09-20T10:00:00Z')])
        self.assertEqual(self.invoke()['excerpts'], 0)
        self.assertIn('No verified activity evidence for this week.', self.output.read_text(encoding='utf-8'))

    def test_timezone_dedup_class_and_roles(self):
        rows = [self.row('2026-10-19T00:30:00Z', 'previous'), self.row('2026-10-26T00:30:00Z', 'included'), self.row('2026-10-20T10:00:00Z', 'TOOL_SECRET', 'tool')]
        self.source(rows)
        self.source(rows, day='2026-10-21')
        self.source([self.row('2026-10-20T10:00:00Z', 'PERSONAL_SECRET')], classification='personal')
        counts = self.invoke(zone='America/Vancouver')
        self.assertEqual(counts['sources'], 1)
        self.assertEqual(counts['excerpts'], 1)
        text = self.output.read_text(encoding='utf-8')
        for secret in ('previous', 'PERSONAL_SECRET', 'METADATA_SECRET', 'TOOL_SECRET'):
            self.assertNotIn(secret, text)
        self.assertIn('included', text)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_hash_and_destination_fail_closed(self):
        path = self.source([self.row('2026-10-20T10:00:00Z')])
        path.write_text('changed', encoding='utf-8')
        self.invoke(expected=1)
        self.assertFalse(self.output.exists())

    def test_gaps_and_bounds(self):
        self.source([self.row(None), self.row('no timestamp'), self.row('2026-10-20T10:00:00'), self.row('2026-10-20T10:00:00Z', 'x' * 40000)])
        for provider in ('antigravity', 'web-clipper'):
            self.source([], provider=provider)
        counts = self.invoke()
        self.assertEqual(counts['unsupported_date_unknown'], 2)
        self.assertEqual(counts['gaps'], 4)
        self.assertLess(self.output.stat().st_size, 65536)

    def test_missing_oversized_and_malformed_snapshots(self):
        path = self.source([self.row('2026-10-20T10:00:00Z')])
        path.unlink()
        self.assertEqual(self.invoke()['gaps'], 1)
        self.source([self.row('2026-10-20T10:00:00Z')])
        path.write_bytes(b'x' * (32 * 1024 * 1024 + 1))
        self.assertEqual(self.invoke()['gaps'], 1)
        path.unlink()
        for record in (self.vault / 'context/source-records').glob('*.md'):
            record.unlink()
        malformed = self.source([self.row('2026-10-20T10:00:00Z', 'valid')])
        raw = b'{bad json}\n'
        digest = hashlib.sha256(raw).hexdigest()
        original = next((self.vault / 'context/source-records').glob('*.md'))
        original.write_text(original.read_text(encoding='utf-8').replace(hashlib.sha256(malformed.read_bytes()).hexdigest(), digest), encoding='utf-8')
        original.rename(original.with_name(f'claude-{digest[:12]}-2026-10-20.md'))
        malformed.unlink()
        target = malformed.with_name(f'claude-{digest[:12]}.jsonl')
        target.write_bytes(raw)
        target.chmod(0o600)
        self.assertEqual(self.invoke()['gaps'], 1)

    def test_text_blocks_metadata_and_excerpt_cap(self):
        row = self.row('2026-10-20T10:00:00Z')
        row['message']['content'] = [{'type': 'text', 'text': 'visible'}, {'type': 'image', 'text': 'ATTACHMENT_SECRET'}, {'type': 'tool_result', 'content': 'TOOL_SECRET'}]
        meta = self.row('2026-10-20T10:00:00Z', 'META_SECRET')
        meta['isMeta'] = True
        self.source([meta, row] + [self.row('2026-10-20T10:00:00Z', 'a' * 600) for _ in range(70)])
        counts = self.invoke()
        self.assertEqual(counts['excerpts'], 16)
        self.assertGreater(counts['gaps'], 0)
        text = self.output.read_text(encoding='utf-8')
        self.assertIn('visible', text)
        for secret in ('ATTACHMENT_SECRET', 'TOOL_SECRET', 'META_SECRET'):
            self.assertNotIn(secret, text)
        self.assertLess(len(self.output.read_bytes()), 65536)
        self.invoke()

    def test_selection_required_and_wrong_identity_rejected(self):
        path = self.source([self.row('2026-10-20T10:00:00Z')])
        self.invoke(expected=2, sources=[])
        self.invoke(expected=1, sources=['unknown'])
        self.source([self.row('2026-10-20T10:00:00Z', 'personal')], classification='personal')
        personal = next(record.stem for record in (self.vault / 'context/source-records').glob('*.md') if 'classification: personal' in record.read_text(encoding='utf-8'))
        self.invoke(expected=1, sources=[personal])
        self.source([self.row('2026-10-20T10:00:00Z', 'old observation')], day='2026-10-12')
        old = next(record.stem for record in (self.vault / 'context/source-records').glob('*2026-10-12.md'))
        self.invoke(expected=1, sources=[old])
        selected = next(record.stem for record in (self.vault / 'context/source-records').glob('*.md') if path.stem in record.stem)
        self.invoke(expected=1, sources=[selected] * 13)

    def test_large_current_source_after_historical_selection(self):
        self.source([self.row('2026-09-20T10:00:00Z', 'historical')])
        historical = next((self.vault / 'context/source-records').glob('*.md')).stem
        self.source([{'type': 'system', 'content': 'x' * 30000}] * 300 + [self.row('2026-10-20T10:00:00Z', 'current evidence')])
        current = next(record.stem for record in (self.vault / 'context/source-records').glob('*.md') if record.stem != historical)
        counts = self.invoke(sources=[historical, current])
        self.assertEqual(counts['excerpts'], 1)
        self.assertIn('current evidence', self.output.read_text(encoding='utf-8'))

    def test_dense_escaping_and_later_hash_failure_preserve_packet(self):
        path = self.source([self.row('2026-10-20T10:00:00Z', '&' * 512)] * 80)
        counts = self.invoke()
        self.assertGreater(counts['gaps'], 0)
        self.assertLessEqual(self.output.stat().st_size, 65536)
        prior = self.output.read_bytes()
        path.write_bytes(b'changed')
        self.invoke(expected=1)
        self.assertEqual(self.output.read_bytes(), prior)

    def test_two_eligible_sources_receive_fair_excerpt_quota(self):
        self.source([self.row('2026-10-20T10:00:00Z', 'FIRSTSOURCE')] * 20)
        first = next((self.vault / 'context/source-records').glob('*.md')).stem
        self.source([self.row('2026-10-20T10:00:00Z', 'SECONDSOURCE')] * 20)
        second = next(record.stem for record in (self.vault / 'context/source-records').glob('*.md') if record.stem != first)
        counts = self.invoke(sources=[first, second])
        text = self.output.read_text(encoding='utf-8')
        self.assertEqual(text.count('FIRSTSOURCE'), 8)
        self.assertEqual(text.count('SECONDSOURCE'), 8)
        self.assertEqual(counts['excerpts'], 16)
        self.assertEqual(counts['gaps'], 24)
        self.assertLessEqual(len(self.output.read_bytes()), 65536)

    def meta(self, **extra):
        return {'type': 'session_meta', 'ordinal': 0, 'timestamp': '2026-10-20T09:00:00.000Z', 'payload': {'id': 'S', 'base_instructions': 'META_SECRET', **extra}}

    def message(self, ordinal, stamp, text='codex included', role='user', phase=None, kind=None, rtype='response_item'):
        payload = {'type': 'message', 'role': role, 'id': f'm{ordinal}',
                   'content': [{'type': kind or ('input_text' if role == 'user' else 'output_text'), 'text': text}]}
        if phase:
            payload['phase'] = phase
        return {'type': rtype, 'ordinal': ordinal, 'timestamp': stamp, 'payload': payload}

    def codex(self, rows, **kwargs):
        return self.source(rows, provider='codex', **kwargs)

    def test_codex_current_week_messages_only(self):
        self.codex([self.meta(),
                    self.message(1, '2026-10-20T10:00:00.000Z', 'DEVELOPER_SECRET', 'developer'),
                    self.message(2, '2026-10-20T10:00:00.000Z', '<environment_context>INJECTED_SECRET</environment_context>'),
                    self.message(3, '2026-10-20T10:00:01.000Z', 'codex user prompt'),
                    self.message(4, '2026-10-20T10:00:02.000Z', 'COMMENTARY_SECRET', 'assistant', 'commentary'),
                    self.message(5, '2026-10-20T10:00:03.000Z', 'codex final answer', 'assistant', 'final_answer'),
                    self.message(6, '2026-10-12T10:00:00.000Z', 'LASTWEEK_SECRET'),
                    self.message(7, '2026-10-20T10:00:04.000Z', 'EVENT_SECRET', rtype='event_msg'),
                    {'type': 'response_item', 'ordinal': 8, 'timestamp': '2026-10-20T10:00:05.000Z', 'payload': {'type': 'function_call', 'arguments': 'TOOL_SECRET'}}])
        counts = self.invoke()
        text = self.output.read_text(encoding='utf-8')
        self.assertEqual((counts['excerpts'], counts['injected_excluded'], counts['gaps'], counts['undated']), (2, 1, 0, 0))
        self.assertIn('2026-10-20 user: codex user prompt', text)
        self.assertIn('2026-10-20 assistant: codex final answer', text)
        for secret in ('DEVELOPER_SECRET', 'INJECTED_SECRET', 'COMMENTARY_SECRET', 'LASTWEEK_SECRET', 'EVENT_SECRET', 'TOOL_SECRET', 'META_SECRET'):
            self.assertNotIn(secret, text)

    def test_codex_historical_messages_collected_this_week(self):
        self.codex([self.meta(), self.message(1, '2026-09-20T10:00:00.000Z')], day='2026-10-21')
        self.assertEqual(self.invoke()['excerpts'], 0)
        self.assertIn('No verified activity evidence for this week.', self.output.read_text(encoding='utf-8'))

    def test_codex_bad_timestamps_and_oversized_rows_are_gaps(self):
        rows = [self.meta(), self.message(1, None), self.message(2, 'no timestamp'), self.message(3, '2026-10-20T10:00:00'),
                self.message(4, '2026-10-20T10:00:00.000Z', 'x' * 40000), self.message(5, '2026-10-20T10:00:00.000Z', '')]
        rows[1].pop('timestamp')
        self.codex(rows)
        counts = self.invoke()
        self.assertEqual((counts['excerpts'], counts['gaps']), (0, 5))

    def test_codex_oversized_nonmessage_is_not_an_activity_gap(self):
        self.codex([self.meta(),
                    {'type': 'response_item', 'ordinal': 1, 'timestamp': '2026-10-20T10:00:00Z',
                     'payload': {'type': 'function_call', 'arguments': 'TOOL_SECRET' * 5000}},
                    self.message(2, '2026-10-20T10:00:01Z', 'MESSAGE_SECRET' * 5000)])
        counts = self.invoke()
        self.assertEqual((counts['excerpts'], counts['gaps']), (0, 1))
        self.assertNotIn('TOOL_SECRET', self.output.read_text(encoding='utf-8'))
        self.assertNotIn('MESSAGE_SECRET', self.output.read_text(encoding='utf-8'))

    def test_codex_fork_replay_is_undated(self):
        self.codex([self.meta(forked_from_id='P', subagent_history_start_ordinal=3),
                    self.message(1, '2026-10-20T10:00:00.000Z', 'REPLAY_SECRET'),
                    self.message(2, '2026-10-20T10:00:00.000Z', 'REPLAY_SECRET', 'assistant', 'final_answer'),
                    self.message(3, '2026-10-20T10:00:01.000Z', 'native prompt')])
        counts = self.invoke()
        self.assertEqual((counts['excerpts'], counts['undated']), (1, 2))
        text = self.output.read_text(encoding='utf-8')
        self.assertIn('native prompt', text)
        self.assertNotIn('REPLAY_SECRET', text)

    def test_codex_unreadable_fork_header_makes_file_undated(self):
        message = self.message(1, '2026-10-20T10:00:00.000Z', 'HEADER_SECRET')
        for rows in ([self.meta(forked_from_id='P'), message],
                     [self.meta(forked_from_id='P', subagent_history_start_ordinal='3'), message],
                     [self.meta(forked_from_id='P', subagent_history_start_ordinal=-1), message],
                     [message], [{'type': 'session_meta', 'payload': 'bad'}, message]):
            for record in (self.vault / 'context/source-records').glob('*.md'):
                record.unlink()
            self.codex(rows)
            counts = self.invoke()
            self.assertEqual((counts['excerpts'], counts['undated']), (0, 1))
            self.assertNotIn('HEADER_SECRET', self.output.read_text(encoding='utf-8'))

    def test_codex_delegated_prompt_label(self):
        self.codex([self.meta(parent_thread_id='P'), self.message(1, '2026-10-20T10:00:00.000Z')])
        self.invoke()
        self.assertIn('delegated-prompt: codex included', self.output.read_text(encoding='utf-8'))

    def test_codex_hash_mismatch_preserves_prior_packet(self):
        path = self.codex([self.meta(), self.message(1, '2026-10-20T10:00:00.000Z')])
        self.invoke()
        prior = self.output.read_bytes()
        self.assertIn(b'codex included', prior)
        path.write_bytes(path.read_bytes() + b'\n')
        self.invoke(expected=1)
        self.assertEqual(self.output.read_bytes(), prior)

    def test_human_and_symlink_protection(self):
        self.source([self.row('2026-10-20T10:00:00Z')])
        self.output.parent.mkdir()
        self.output.write_text('human', encoding='utf-8')
        self.invoke(expected=1)
        self.assertEqual(self.output.read_text(encoding='utf-8'), 'human')
        self.output.unlink()
        self.output.symlink_to(self.vault / 'absent')
        self.invoke(expected=1)
        self.output.unlink()
        self.output.parent.rmdir()
        self.output.parent.symlink_to(self.vault)
        self.invoke(expected=1)

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    unittest.main()
