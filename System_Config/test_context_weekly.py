#!/usr/bin/env python3
"""Fixture tests for weekly views over generated hash-only source records."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("context_weekly.py")
SECRET = "PRIVATE_WEEKLY_SOURCE_FIXTURE_ONLY"


class ContextWeeklyFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "brain"
        self.records = self.vault / "context/source-records"
        self.records.mkdir(parents=True)
        self.note = self.vault / "weekly_logs/2026/2026-W42.md"
        self.note.parent.mkdir(parents=True)
        self.note.write_text("# Handwritten weekly note\n\nKeep these words exactly.\n")

    def record(self, provider, classification, day, status="captured"):
        digest = hashlib.sha256((provider + classification + day).encode()).hexdigest()
        path = self.records / f"{provider}-{digest[:12]}-{day}.md"
        path.write_text("\n".join((
            "---", "generated: context-intake-v1", f"provider: {provider}", "age: current",
            f"classification: {classification}", f"status: {status}", f"date: {day}", "---", "",
            "<!-- generated-context-intake-v1 -->", "", f"private-source:sha256:{digest}", "",
        )))
        return path

    def invoke(self, *args, expected=0, documented=False):
        vault = "brain" if documented else str(self.vault)
        result = subprocess.run([sys.executable, str(SCRIPT), "--vault", vault,
                                 "--week", "2026-W42", *args], text=True, capture_output=True, timeout=10,
                                cwd=self.root if documented else None,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        return result

    def archive(self):
        return self.vault / "context/weekly-sources/2026-W42.md"

    def test_groups_current_week_links_records_and_preserves_human_note(self):
        work = self.record("codex", "work", "2026-10-12")
        personal = self.record("web-clipper", "personal", "2026-10-14")
        unsorted = self.record("antigravity", "unsorted", "2026-10-16", "decoder-required")
        old = self.record("claude", "work", "2026-10-11")
        self.invoke("--note", "brain/weekly_logs/2026/2026-W42.md", documented=True)
        text = self.archive().read_text()
        self.assertIn("## Work", text)
        self.assertIn("## Personal", text)
        self.assertIn("## Unsorted", text)
        for record in (work, personal, unsorted):
            self.assertIn(f"[[source-records/{record.stem}", text)
        self.assertNotIn(old.stem, text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(str(self.root), text)
        note = self.note.read_text()
        self.assertIn("Keep these words exactly.", note)
        self.assertIn("<!-- context-weekly-link:start -->", note)
        self.assertIn("[[context/weekly-sources/2026-W42|", note)
        archive_before, note_before = self.archive().read_bytes(), self.note.read_bytes()
        self.invoke("--note", "brain/weekly_logs/2026/2026-W42.md", documented=True)
        self.assertEqual(self.archive().read_bytes(), archive_before)
        self.assertEqual(self.note.read_bytes(), note_before)

    def test_malformed_symlink_and_human_conflicts_fail_closed(self):
        self.record("codex", "work", "2026-10-12")
        malformed = self.records / "bad.md"
        malformed.write_text("human record\n")
        self.invoke(expected=1)
        self.assertFalse(self.archive().exists())
        malformed.unlink()
        target = self.record("claude", "personal", "2026-10-13")
        (self.records / "alias.md").symlink_to(target)
        self.invoke(expected=1)
        self.assertFalse(self.archive().exists())
        (self.records / "alias.md").unlink()
        self.archive().parent.mkdir(parents=True, exist_ok=True)
        self.archive().write_text("human archive\n")
        note_before = self.note.read_bytes()
        self.invoke("--note", str(self.note), expected=1)
        self.assertEqual(self.archive().read_bytes(), b"human archive\n")
        self.assertEqual(self.note.read_bytes(), note_before)

    def test_note_conflict_and_missing_note_do_not_create_note_or_archive(self):
        self.record("codex", "work", "2026-10-12")
        self.note.write_text("human\n<!-- context-weekly-link:start -->\n")
        before = self.note.read_bytes()
        self.invoke("--note", str(self.note), expected=1)
        self.assertEqual(self.note.read_bytes(), before)
        self.assertFalse(self.archive().exists())
        missing = self.vault / "weekly_logs/2026/2026-W42-missing.md"
        self.note.write_text("human\n")
        self.invoke("--note", str(missing), expected=1)
        self.assertFalse(missing.exists())
        self.assertFalse(self.archive().exists())


if __name__ == "__main__":
    unittest.main()

