#!/usr/bin/env python3
"""Fixtures for Python daily, Monday, and Friday private-context hooks."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

import config
import context_cadence


class ContextCadenceFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.system = self.root / "System_Config"
        self.brain = self.root / "brain"
        self.system.mkdir()
        self.brain.mkdir()
        self.trace = self.root / "trace"
        self.old_workspace, self.old_brain = config.WORKSPACE, config.BRAIN
        config.WORKSPACE, config.BRAIN = self.root, self.brain
        self.addCleanup(self.restore_config)
        self.old_trace = os.environ.get("CONTEXT_TRACE")
        os.environ["CONTEXT_TRACE"] = str(self.trace)
        self.addCleanup(self.restore_trace)
        script = (
            "import os, pathlib, sys\n"
            "pathlib.Path(os.environ['CONTEXT_TRACE']).open('a', encoding='utf-8').write("
            "pathlib.Path(sys.argv[0]).name + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        )
        for name in ("context_weekly.py", "context_auto_summary.py", "context_mempalace.py"):
            (self.system / name).write_text(script, encoding="utf-8")
        collector = self.system / "context_collect.sh"
        collector.write_text('#!/usr/bin/env bash\nprintf "context_collect.sh %s\\n" "$*" >> "$CONTEXT_TRACE"\n', encoding="utf-8")
        collector.chmod(0o755)

    def restore_config(self):
        config.WORKSPACE, config.BRAIN = self.old_workspace, self.old_brain

    def restore_trace(self):
        if self.old_trace is None:
            os.environ.pop("CONTEXT_TRACE", None)
        else:
            os.environ["CONTEXT_TRACE"] = self.old_trace

    def lines(self):
        return self.trace.read_text(encoding="utf-8").splitlines() if self.trace.exists() else []

    def test_collection_requires_regular_explicit_config(self):
        logs = []
        self.assertFalse(context_cadence.collect("2026-10-16", logs.append))
        self.assertEqual(self.lines(), [])
        (self.system / "context-sources.local.json").write_text('{"sources": []}\n', encoding="utf-8")
        self.assertTrue(context_cadence.collect("2026-10-16", logs.append))
        self.assertEqual(self.lines(), ["context_collect.sh 2026-10-16"])

    def test_friday_refreshes_collection_overview_and_weekly_links(self):
        (self.system / "context-sources.local.json").write_text('{"sources": []}\n', encoding="utf-8")
        (self.system / "context-manifest.local.json").write_text("context-discover-v1\n", encoding="utf-8")
        old_bin = os.environ.get("CONTEXT_MEMPALACE_BIN")
        os.environ["CONTEXT_MEMPALACE_BIN"] = "/private/mempalace"
        self.addCleanup(lambda: os.environ.pop("CONTEXT_MEMPALACE_BIN", None) if old_bin is None else os.environ.__setitem__("CONTEXT_MEMPALACE_BIN", old_bin))
        logs = []
        note = self.brain / "weekly_logs/2026/2026-W42.md"
        context_cadence.friday("2026-10-16", "2026-W42", note, logs.append)
        trace = "\n".join(self.lines())
        self.assertIn("context_collect.sh 2026-10-16", trace)
        self.assertIn("context_mempalace.py --vault", trace)
        self.assertIn("context_auto_summary.py --vault", trace)
        self.assertIn("context_weekly.py --vault", trace)
        self.assertIn(str(note), trace)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()
