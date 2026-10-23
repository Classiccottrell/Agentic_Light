#!/usr/bin/env python3
"""Fixtures for manual context collection; all sources are temporary."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parent
SECRET = "PRIVATE_COLLECTION_FIXTURE_ONLY"


def tree_bytes(root):
    if not root.exists():
        return {}
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


class ContextCollectFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace"
        self.system = self.workspace / "System_Config"
        self.system.mkdir(parents=True)
        self.vault = self.workspace / "brain"
        self.vault.mkdir()
        self.sources = self.workspace / "private-sources"
        self.sources.mkdir()
        for name in ("context_collect.py", "context_collect.sh", "context_discover.py", "context_intake.py", "context_weekly.py", "brain_lock.py"):
            shutil.copy2(SCRIPTS / name, self.system / name)

    def source(self, name):
        path = self.sources / name
        path.write_text(SECRET, encoding="utf-8")
        return path

    def entry(self, provider, root, suffix, classification, status="captured"):
        return {"provider": provider, "root": str(root), "suffix": suffix, "age": "current",
                "classification": classification, "status": status}

    def config(self, entries):
        (self.system / "context-sources.local.json").write_text(json.dumps({"sources": entries}), encoding="utf-8")

    def invoke(self, *args, expected=0):
        result = subprocess.run(["bash", str(self.system / "context_collect.sh"), *args],
                                text=True, capture_output=True, timeout=10,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertNotIn(str(self.workspace), result.stdout + result.stderr)
        return result

    def test_manual_collection_publishes_all_classifications_without_raw_data(self):
        work = self.source("work.jsonl")
        personal = self.source("personal.md")
        unsorted = self.source("pending.db")
        self.config([
            self.entry("codex", work, ".jsonl", "work"),
            self.entry("web-clipper", personal, ".md", "personal"),
            self.entry("antigravity", unsorted, ".db", "unsorted", "decoder-required"),
        ])
        note = self.vault / "weekly_logs/2026/2026-W42.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Handwritten note\n", encoding="utf-8")
        self.invoke("2026-10-17")
        records = sorted((self.vault / "context/source-records").glob("*.md"))
        self.assertEqual(len(records), 3)
        queue = self.vault / "context/unsorted-context-2026-10-17.md"
        self.assertIn("antigravity", queue.read_text(encoding="utf-8"))
        archive = self.vault / "context/weekly-sources/2026-W42.md"
        self.assertTrue(archive.is_file())
        self.assertIn("[[context/weekly-sources/2026-W42|", note.read_text(encoding="utf-8"))
        vault_text = "\n".join(path.read_text(encoding="utf-8") for path in records + [queue, archive])
        self.assertNotIn(SECRET, vault_text)
        self.assertNotIn(str(self.workspace), vault_text)

    def test_manual_collection_does_not_create_an_absent_weekly_note(self):
        work = self.source("work.jsonl")
        self.config([self.entry("codex", work, ".jsonl", "work")])
        self.invoke("2026-10-17")
        self.assertTrue((self.vault / "context/weekly-sources/2026-W42.md").is_file())
        self.assertFalse((self.vault / "weekly_logs/2026/2026-W42.md").exists())

    def test_missing_config_discovery_failure_and_invalid_date_leave_vault_unchanged(self):
        before = tree_bytes(self.vault)
        self.invoke("2026-10-17", expected=1)
        self.assertEqual(tree_bytes(self.vault), before)

        self.config([self.entry("codex", self.sources / "missing.jsonl", ".jsonl", "work")])
        self.invoke("2026-10-17", expected=1)
        self.assertEqual(tree_bytes(self.vault), before)

        self.invoke("not-a-date", expected=1)
        self.assertEqual(tree_bytes(self.vault), before)
        self.assertFalse((self.system / "context-manifest.local.json").exists())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()

