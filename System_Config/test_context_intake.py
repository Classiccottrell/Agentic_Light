#!/usr/bin/env python3
"""Fixture tests for private-source context intake; no personal files are read."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("context_intake.py")
SECRET = "PRIVATE_CONTEXT_FIXTURE_ONLY"


def tree_bytes(root):
    result = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISREG(info.st_mode):
            result[str(path.relative_to(root))] = (info.st_mode, path.read_bytes())
        elif path.is_symlink():
            result[str(path.relative_to(root))] = (info.st_mode, os.readlink(path))
        else:
            result[str(path.relative_to(root))] = (info.st_mode, None)
    return result


class ContextIntakeFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "Vault_Brain"
        self.vault.mkdir()
        self.data = self.root / "private-inputs"
        self.data.mkdir()
        self.manifest = self.root / "PRIVATE.json"

    def source(self, name, content=SECRET):
        path = self.data / name
        path.write_text(content, encoding="utf-8")
        return path

    def write_manifest(self, sources):
        self.manifest.write_text(json.dumps({"sources": sources}), encoding="utf-8")

    def row(self, path, provider="codex", age="current", classification="work", status="captured"):
        return {"path": str(path), "provider": provider, "age": age,
                "classification": classification, "status": status}

    def invoke(self, expected=0, date="2026-10-16"):
        result = subprocess.run([sys.executable, str(SCRIPT), "--vault", str(self.vault),
                                 "--manifest", str(self.manifest), "--date", date],
                                text=True, encoding="utf-8", capture_output=True, timeout=10)
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        return result

    def test_three_classifications_are_safe_idempotent_and_queue_unsorted(self):
        work = self.source("work.jsonl")
        personal = self.source("personal.jsonl")
        unsorted = self.source("unknown.md")
        self.write_manifest([self.row(work), self.row(personal, provider="claude", classification="personal"),
                             self.row(unsorted, provider="web-clipper", classification="unsorted", status="review")])
        self.invoke()
        records = self.vault / "context/source-records"
        self.assertEqual(len(list(records.glob("*.md"))), 3)
        contents = "\n".join(path.read_text(encoding="utf-8") for path in records.glob("*.md"))
        self.assertNotIn(SECRET, contents)
        self.assertNotIn(str(self.root), contents)
        for path in (work, personal, unsorted):
            self.assertIn("private-source:sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(), contents)
        queue = self.vault / "context/unsorted-context-2026-10-16.md"
        queue_text = queue.read_text(encoding="utf-8")
        self.assertIn("human classification required", queue_text)
        self.assertIn("web-clipper", queue_text)
        self.assertIn(hashlib.sha256(unsorted.read_bytes()).hexdigest()[:12], queue_text)
        self.assertNotIn("codex", queue_text)
        self.assertNotIn("claude", queue_text)
        self.assertNotIn(SECRET, queue_text)
        self.assertNotIn(str(self.root), queue_text)
        first = tree_bytes(self.vault)
        self.invoke()
        self.assertEqual(tree_bytes(self.vault), first)
        self.write_manifest([self.row(work), self.row(personal, provider="claude", classification="personal")])
        self.invoke()
        cleared = queue.read_text(encoding="utf-8")
        self.assertIn("No unsorted sources", cleared)
        self.assertNotIn("web-clipper", cleared)
        self.assertNotIn(SECRET, cleared)
        self.assertNotIn(str(self.root), cleared)

    def test_changed_source_creates_new_record_without_removing_old(self):
        source = self.source("session.jsonl", "first " + SECRET)
        self.write_manifest([self.row(source)])
        self.invoke()
        first = sorted((self.vault / "context/source-records").glob("*.md"))
        source.write_text("second " + SECRET, encoding="utf-8")
        self.invoke()
        second = sorted((self.vault / "context/source-records").glob("*.md"))
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 2)
        self.assertTrue(first[0].exists())

    def test_unchanged_source_is_recorded_again_on_a_new_day(self):
        source = self.source("session.jsonl")
        self.write_manifest([self.row(source)])
        self.invoke(date="2026-10-16")
        self.invoke(date="2026-10-17")
        records = sorted((self.vault / "context/source-records").glob("*.md"))
        self.assertEqual(len(records), 2)
        self.assertTrue(any(path.name.endswith("-2026-10-16.md") for path in records))
        self.assertTrue(any(path.name.endswith("-2026-10-17.md") for path in records))

    def test_invalid_manifest_and_sources_leave_existing_output_unchanged(self):
        source = self.source("session.jsonl")
        self.write_manifest([self.row(source)])
        self.invoke()
        before = tree_bytes(self.vault)
        cases = [
            b"{broken",
            json.dumps({"sources": [dict(self.row(source), provider="bad provider")]}).encode(),
            json.dumps({"sources": [dict(self.row(source), classification="maybe")]}).encode(),
            json.dumps({"sources": [dict(self.row(self.root / "missing"))]}).encode(),
        ]
        link = self.data / "link.jsonl"
        link.symlink_to(source)
        cases.append(json.dumps({"sources": [self.row(link)]}).encode())
        folder = self.data / "folder"
        folder.mkdir()
        cases.append(json.dumps({"sources": [self.row(folder)]}).encode())
        for payload in cases:
            with self.subTest(payload=payload[:20]):
                self.manifest.write_bytes(payload)
                self.invoke(expected=1)
                self.assertEqual(tree_bytes(self.vault), before)

    def test_non_generated_destinations_conflict_without_writes(self):
        source = self.source("session.jsonl")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        record = self.vault / "context/source-records" / f"codex-{digest[:12]}-2026-10-16.md"
        record.parent.mkdir(parents=True)
        record.write_text("human note\n", encoding="utf-8")
        self.write_manifest([self.row(source)])
        before = tree_bytes(self.vault)
        self.invoke(expected=1)
        self.assertEqual(tree_bytes(self.vault), before)

        record.unlink()
        queue = self.vault / "context/unsorted-context-2026-10-16.md"
        queue.write_text("human queue\n", encoding="utf-8")
        self.write_manifest([self.row(source, classification="unsorted")])
        before = tree_bytes(self.vault)
        self.invoke(expected=1)
        self.assertEqual(tree_bytes(self.vault), before)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()

