#!/usr/bin/env python3
"""Fixtures for the automatic, hash-only Friday context overview."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("context_auto_summary.py")


class ContextAutoSummaryFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / "Vault_Brain"
        self.records = self.vault / "context/source-records"
        self.records.mkdir(parents=True)

    def record(self, provider, classification, day, seed):
        digest = hashlib.sha256(seed.encode()).hexdigest()
        path = self.records / f"{provider}-{digest[:12]}-{day}.md"
        path.write_text("\n".join(("---", "generated: context-intake-v1", f"provider: {provider}",
            "age: current", f"classification: {classification}", "status: captured",
            f"date: {day}", "---", "", "<!-- generated-context-intake-v1 -->", "",
            f"private-source:sha256:{digest}", "")), encoding="utf-8")
        return path

    def invoke(self, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--vault", str(self.vault),
                                 "--week", "2026-W42"], text=True, capture_output=True, timeout=10,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn(str(self.vault), result.stdout + result.stderr)
        return result

    def test_publishes_a_clean_overview_and_refreshes_the_archive(self):
        self.record("codex", "work", "2026-10-12", "same")
        self.record("codex", "work", "2026-10-13", "same")
        self.record("web-clipper", "personal", "2026-10-14", "clip")
        self.record("antigravity", "unsorted", "2026-10-15", "pending")
        self.invoke()
        overview = self.vault / "context/weekly-overviews/2026-W42.md"
        text = overview.read_text(encoding="utf-8")
        self.assertIn("1 work source(s), 1 personal source(s), and 1 source(s) awaiting", text)
        archive = (self.vault / "context/weekly-sources/2026-W42.md").read_text(encoding="utf-8")
        self.assertIn("[[weekly-overviews/2026-W42|Read the automatic weekly overview]]", archive)

    def test_refuses_to_replace_a_human_overview(self):
        output = self.vault / "context/weekly-overviews/2026-W42.md"
        output.parent.mkdir(parents=True)
        output.write_text("human overview\n", encoding="utf-8")
        self.invoke(expected=1)
        self.assertEqual(output.read_text(encoding="utf-8"), "human overview\n")

    def test_republishes_a_large_generated_archive(self):
        for number in range(200):
            self.record("codex", "unsorted", "2026-10-12", f"session-{number}")
        self.invoke()
        archive = self.vault / "context/weekly-sources/2026-W42.md"
        self.assertGreater(archive.stat().st_size, 16384)
        self.invoke()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()
