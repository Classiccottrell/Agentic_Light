#!/usr/bin/env python3
"""Fixture tests for private, source-linked English weekly context."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("context_weekly_curate.py")


class ContextCurateFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "brain"
        self.records = self.vault / "context/source-records"
        self.records.mkdir(parents=True)
        self.summary = self.root / "summary.md"

    def record(self, provider, day):
        digest = hashlib.sha256((provider + day).encode()).hexdigest()
        path = self.records / f"{provider}-{digest[:12]}-{day}.md"
        path.write_text("\n".join((
            "---", "generated: context-intake-v1", f"provider: {provider}", "age: current",
            "classification: work", "status: captured", f"date: {day}", "---", "",
            "<!-- generated-context-intake-v1 -->", "", f"private-source:sha256:{digest}", "",
        )), encoding="utf-8")
        return path

    def invoke(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--vault", str(self.vault),
                                 "--week", "2026-W42", *args], text=True, capture_output=True,
                                timeout=10, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        return result

    def curated(self):
        return self.vault / "context/weekly-context/2026-W42.md"

    def archive(self):
        return self.vault / "context/weekly-sources/2026-W42.md"

    def test_publishes_english_summary_with_selected_records_and_refreshes_archive(self):
        codex = self.record("codex", "2026-10-12")
        claude = self.record("claude", "2026-10-13")
        self.summary.write_text("Two providers advanced the same project handoff.\n", encoding="utf-8")

        result = self.invoke("--summary", str(self.summary), "--source", codex.stem,
                             "--source", claude.stem)

        self.assertEqual(result.stdout.strip(), '{"sources": 2, "week": "2026-W42"}')
        text = self.curated().read_text(encoding="utf-8")
        self.assertIn("Two providers advanced the same project handoff.", text)
        self.assertIn(f"[[source-records/{codex.stem}|", text)
        self.assertIn(f"[[source-records/{claude.stem}|", text)
        self.assertNotIn(str(self.root), text)
        archive = self.archive().read_text(encoding="utf-8")
        self.assertIn("## Curated summary", archive)
        self.assertIn("[[weekly-context/2026-W42|Read the English weekly context]]", archive)

    def test_rejects_unselected_or_human_owned_summary_without_writing(self):
        current = self.record("codex", "2026-10-12")
        previous = self.record("claude", "2026-10-05")
        self.summary.write_text("A safe summary.\n", encoding="utf-8")

        self.invoke("--summary", str(self.summary), "--source", previous.stem, expected=1)
        self.assertFalse(self.curated().exists())
        self.assertFalse(self.archive().exists())

        self.curated().parent.mkdir(parents=True)
        self.curated().write_text("human note\n", encoding="utf-8")
        self.invoke("--summary", str(self.summary), "--source", current.stem, expected=1)
        self.assertEqual(self.curated().read_text(encoding="utf-8"), "human note\n")
        self.assertFalse(self.archive().exists())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()

