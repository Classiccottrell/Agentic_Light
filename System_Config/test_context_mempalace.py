#!/usr/bin/env python3
"""Fixtures for the private explicit-source MemPalace bridge."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("context_mempalace.py")
SECRET = "PRIVATE_MEMPALACE_FIXTURE_ONLY"


class ContextMemPalaceFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "brain"
        self.vault.mkdir()
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.trace = self.root / "trace"
        self.binary = self.root / "mempalace"
        self.binary.write_text('#!/usr/bin/env bash\nmkdir -p "$2"\nprintf "%s\\n" "$*" >> "$TRACE"\n', encoding="utf-8")
        self.binary.chmod(0o755)

    def source(self, name):
        path = self.sources / name
        path.write_text(SECRET + "\n" + name, encoding="utf-8")
        return path

    def manifest(self, rows):
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"sources": rows}), encoding="utf-8")
        return path

    def row(self, provider, path, classification="work", status="selected"):
        return {"path": str(path), "provider": provider, "age": "current",
                "classification": classification, "status": status}

    def invoke(self, manifest, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--vault", str(self.vault),
                                 "--manifest", str(manifest), "--bin", str(self.binary)],
                                text=True, capture_output=True, timeout=10,
                                env=dict(os.environ, TRACE=str(self.trace), PYTHONDONTWRITEBYTECODE="1"), encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        return result

    def test_mines_supported_sources_and_skips_opaque_rows(self):
        claude = self.source("claude.jsonl")
        codex = self.source("codex.jsonl")
        antigravity = self.source("antigravity.jsonl")
        clip = self.source("clip.md")
        opaque = self.source("antigravity.db")
        result = self.invoke(self.manifest([
            self.row("claude", claude), self.row("codex", codex),
            self.row("antigravity", antigravity),
            self.row("web-clipper", clip, "personal"),
            self.row("antigravity", opaque, "unsorted", "decoder-required"),
        ]))
        self.assertEqual(json.loads(result.stdout), {"deferred": 0, "indexed": 4, "skipped": 1})
        calls = self.trace.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 3)
        self.assertEqual(sum(" init " in call for call in calls), 1)
        self.assertIn(" init " + str(self.vault / "context"), calls[0])
        self.assertEqual(sum("--mode convos" in call for call in calls), 1)
        self.assertEqual(sum("--mode projects" in call for call in calls), 1)
        self.assertTrue((self.vault / "context/mempalace").is_dir())
        staged = sorted((self.vault / "context/mempalace-staging").rglob("*"))
        staged = [path for path in staged if path.is_file()]
        self.assertEqual(len(staged), 4)
        self.assertTrue(all(SECRET in path.read_text(encoding="utf-8") for path in staged))

    def test_invalid_source_fails_before_mining(self):
        source = self.source("claude.jsonl")
        alias = self.sources / "alias.jsonl"
        alias.symlink_to(source)
        self.invoke(self.manifest([self.row("claude", alias)]), expected=1)
        self.assertFalse(self.trace.exists())

    def test_symlinked_context_directory_fails_before_mining(self):
        source = self.source("claude.jsonl")
        outside = self.root / "outside"
        outside.mkdir()
        (self.vault / "context").symlink_to(outside)
        self.invoke(self.manifest([self.row("claude", source)]), expected=1)
        self.assertFalse(self.trace.exists())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()

