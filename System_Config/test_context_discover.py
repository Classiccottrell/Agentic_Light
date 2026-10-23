#!/usr/bin/env python3
"""Fixture tests for opt-in context discovery; never inspect provider defaults."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("context_discover.py")
SECRET = "PRIVATE_DISCOVERY_FIXTURE_ONLY"
sys.path.insert(0, str(SCRIPT.parent))
import context_discover


class ContextDiscoverFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "default.jsonl").write_text(SECRET, encoding="utf-8")
        self.data = self.root / "opted-in"
        self.data.mkdir()
        self.config = self.root / "PRIVATE-config.json"
        self.out = self.root / "PRIVATE-manifest.json"

    def source(self, relative, text=SECRET):
        path = self.data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def entry(self, provider, root, suffix, age="current", classification="work", status="captured"):
        return {"provider": provider, "root": str(root), "suffix": suffix, "age": age,
                "classification": classification, "status": status}

    def write_config(self, entries):
        self.config.write_text(json.dumps({"sources": entries}), encoding="utf-8")

    def invoke(self, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--config", str(self.config),
                                 "--out", str(self.out), "--date", "2026-10-17"],
                                text=True, capture_output=True, timeout=10,
                                env=dict(os.environ, HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1"), encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        return result

    def marker(self):
        return self.out.with_name(self.out.name + ".context-discover")

    def test_exact_filename_suffix_skips_sibling_logs(self):
        wanted = self.source("agy/brain/a/.system_generated/logs/transcript.jsonl")
        self.source("agy/brain/a/.system_generated/logs/transcript_full.jsonl")
        self.write_config([self.entry("antigravity", self.data / "agy", "transcript.jsonl")])
        self.invoke()
        self.assertEqual([row["path"] for row in json.loads(self.out.read_text(encoding="utf-8"))["sources"]], [str(wanted)])

    def test_explicit_recursive_sources_emit_all_providers_without_duplicates(self):
        claude = self.source("claude/nested/session.jsonl")
        codex = self.source("codex/rollout.jsonl")
        antigravity = self.source("antigravity/history.db")
        clipper = self.source("clips/nested/article.md")
        self.source("claude/nested/ignore.txt")
        self.write_config([
            self.entry("claude", claude.parent.parent, ".jsonl"),
            self.entry("claude", claude.parent.parent, ".jsonl"),
            self.entry("codex", codex, ".jsonl", age="old"),
            self.entry("antigravity", antigravity.parent, ".db", classification="unsorted", status="decoder-required"),
            self.entry("web-clipper", clipper.parent.parent, ".md", classification="personal"),
        ])
        self.invoke()
        rows = json.loads(self.out.read_text(encoding="utf-8"))["sources"]
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["provider"] for row in rows}, {"claude", "codex", "antigravity", "web-clipper"})
        self.assertNotIn(str(self.home / "default.jsonl"), {row["path"] for row in rows})
        self.assertEqual({row["path"] for row in rows}, {str(claude), str(codex), str(antigravity), str(clipper)})
        self.assertTrue(all(Path(row["path"]).is_absolute() for row in rows))
        self.assertTrue(all(set(row) == {"path", "provider", "age", "classification", "status"} for row in rows))
        antigravity_row = next(row for row in rows if row["provider"] == "antigravity")
        self.assertEqual((antigravity_row["classification"], antigravity_row["status"]),
                         ("unsorted", "decoder-required"))
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o600)
        first = self.out.read_bytes()
        self.invoke()
        self.assertEqual(self.out.read_bytes(), first)

    def test_owned_output_can_be_replaced_but_human_output_cannot(self):
        first = self.source("first.jsonl")
        second = self.source("second.jsonl")
        self.write_config([self.entry("codex", first, ".jsonl")])
        self.invoke()
        self.write_config([self.entry("codex", second, ".jsonl")])
        self.invoke()
        self.assertEqual({row["path"] for row in json.loads(self.out.read_text(encoding="utf-8"))["sources"]}, {str(second)})
        self.out.unlink()
        self.marker().unlink()
        self.out.write_text("human manifest\n", encoding="utf-8")
        before = self.out.read_bytes()
        self.invoke(expected=1)
        self.assertEqual(self.out.read_bytes(), before)

    def test_first_publish_collision_preserves_human_manifest(self):
        human = b"human manifest\n"
        original_link = os.link

        def collide(source, destination, *args, **kwargs):
            self.out.write_bytes(human)
            return original_link(source, destination, *args, **kwargs)

        with patch.object(context_discover.os, "link", side_effect=collide):
            with self.assertRaises(ValueError):
                context_discover.atomic_write(self.out, b"generated\n", replace_state=None)
        self.assertEqual(self.out.read_bytes(), human)
        self.assertFalse(self.marker().exists())

    def test_owned_output_change_before_replace_preserves_human_manifest(self):
        source = self.source("session.jsonl")
        self.write_config([self.entry("codex", source, ".jsonl")])
        self.invoke()
        _, replace_state = context_discover.output_state(self.out)
        human = b"human replacement\n"
        self.out.write_bytes(human)
        with self.assertRaises(ValueError):
            context_discover.atomic_write(self.out, b"generated\n", replace_state)
        self.assertEqual(self.out.read_bytes(), human)
        self.assertEqual(self.marker().read_bytes(), context_discover.MARKER)

    def test_malformed_relative_and_unsafe_sources_fail_without_output(self):
        regular = self.source("safe.jsonl")
        linked = self.data / "linked.jsonl"
        linked.symlink_to(regular)
        fifo = self.data / "events.jsonl"
        os.mkfifo(fifo)
        cases = [
            b"{broken",
            json.dumps({"sources": [dict(self.entry("codex", regular, ".jsonl"), root="relative.jsonl")]}).encode(),
            json.dumps({"sources": [self.entry("codex", linked, ".jsonl")]}).encode(),
            json.dumps({"sources": [self.entry("claude", self.data, ".jsonl")]}).encode(),
            json.dumps({"sources": [self.entry("codex", self.root / "missing", ".jsonl")]}).encode(),
        ]
        for payload in cases:
            with self.subTest(payload=payload[:20]):
                self.config.write_bytes(payload)
                self.invoke(expected=1)
                self.assertFalse(self.out.exists())
                self.assertFalse(self.marker().exists())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()

