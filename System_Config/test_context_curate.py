#!/usr/bin/env python3
"""Regression tests for curation writes."""
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

import context_curate


class CurationWriteTests(unittest.TestCase):
    def test_atomic_write_preserves_existing_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.md"
            path.write_text("original\n", encoding="utf-8")
            with patch("context_curate.os.replace", side_effect=OSError("simulated")):
                with self.assertRaises(OSError):
                    context_curate.atomic_write(path, "replacement\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(list(Path(tmp).glob(".record.md.*")), [])

    def test_agent_session_can_link_to_a_related_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "pipeline/logs/run.log"
            log.parent.mkdir(parents=True)
            log.write_text("run log\n", encoding="utf-8")
            project_source = root / "notes/project.md"
            project_source.parent.mkdir(parents=True)
            project_source.write_text("project notes\n", encoding="utf-8")
            records = root / "brain/records"
            project = records / "projects/fictional-architecture.md"
            project.parent.mkdir(parents=True)
            project.write_text(
                "---\nid: fictional-architecture\ntype: project\ntitle: Fictional Architecture Reconstruction\n"
                "status: active\nscope: project\ncreated: 2026-10-19\nupdated: 2026-10-19\n"
                "author: human\nsource: notes/project.md\n---\n\n## Summary\nFictional Architecture Reconstruction project.\n"
                "## Goals\nReconstruct architecture from evidence.\n## Status\nActive.\n## Links\n\n",
                encoding="utf-8")
            session = records / "sessions/session-fixture.md"
            session.parent.mkdir(parents=True)
            session.write_text(
                "---\nid: session-fixture\ntype: session\ntitle: Fictional Architecture Reconstruction session\n"
                "status: archived\nscope: session\ncreated: 2026-10-19\nupdated: 2026-10-19\n"
                "author: ai\nsource: pipeline/logs/run.log\n---\n\n## Task\nFictional Architecture Reconstruction evidence work.\n"
                "## Outcome\nCompleted reconstruction work.\n## Changed\nArchitecture reconstruction plan.\n"
                "## Unresolved\nNone.\n",
                encoding="utf-8")
            found = context_curate.candidates(root, session)
            accepted = [item for item in found if item["confidence"] == "high"]
            self.assertEqual([item["id"] for item in accepted], ["fictional-architecture"])
            self.assertTrue(context_curate.apply_links(session, accepted))
            self.assertIn("[[fictional-architecture]]", session.read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()
