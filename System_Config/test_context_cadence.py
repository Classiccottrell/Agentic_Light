#!/usr/bin/env python3
"""Fixture coverage for the daily, Monday, and Friday context cadence."""
import datetime as dt
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).parent


class ContextCadenceFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.system = self.root / "System_Config"
        self.brain = self.root / "brain"
        self.system.mkdir()
        self.brain.mkdir()
        for name in ("daily_ingest.sh", "monday_init.sh", "friday_process.sh", "context_weekly.py",
                     "context_auto_summary.py"):
            shutil.copy2(HERE / name, self.system / name)
        (self.system / "context_collect.sh").write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$WORKSPACE/collector.trace"\n')
        (self.system / "context_collect.sh").chmod(0o755)
        (self.system / "context-sources.local.json").write_text('{"sources": []}\n')
        (self.system / "config.sh").write_text(
            f'WORKSPACE="{self.root}"\nBRAIN="$WORKSPACE/brain"\nRAW="$BRAIN/raw"\n'
            'LOG_DIR="$WORKSPACE/logs"\n'
            'ensure_current_week_raw_folder() { :; }\n'
            'acquire_lock() { return 0; }\n'
            'date_offset() { local shift="$2"; case "$shift" in -*) ;; *) shift="+$shift" ;; esac; if [[ -n "$1" ]]; then date -j -v"$shift"d -f "%Y-%m-%d" "$1" +"$3"; else date -j -v"$shift"d +"$3"; fi; }\n')

    def invoke(self, name, *args, **env):
        return subprocess.run(["/bin/bash", str(self.system / name), *args],
                              text=True, capture_output=True, timeout=10,
                              env=dict(os.environ, WORKSPACE=str(self.root),
                                       PYTHONDONTWRITEBYTECODE="1", **env))

    def week(self):
        value = dt.date.today().isocalendar()
        return f"{value.year}-W{value.week:02d}"

    def test_daily_collection_is_opt_in_and_dry_run_safe(self):
        result = self.invoke("daily_ingest.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex((self.root / "collector.trace").read_text(), r"^\d{4}-\d{2}-\d{2}$")
        (self.root / "collector.trace").unlink()
        result = self.invoke("daily_ingest.sh", DRY_RUN="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "collector.trace").exists())

    def test_monday_and_friday_keep_the_generated_context_link(self):
        year = self.week()[:4]
        weekly = self.brain / "weekly_logs"
        (weekly / "Weekly_Note_Template.md").parent.mkdir()
        shutil.copy2(HERE.parent / "brain/weekly_logs/Weekly_Note_Template.md",
                     weekly / "Weekly_Note_Template.md")
        (weekly / f"{year} Master Note.md").write_text("<!-- WEEKLY-INDEX-INSERT -->\n")
        result = self.invoke("monday_init.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        note = weekly / year / f"{self.week()}.md"
        self.assertIn(f"[[context/weekly-sessions/{self.week()}|", note.read_text())
        self.assertIn(f"[[context/weekly-sources/{self.week()}|", note.read_text())
        result = self.invoke("friday_process.sh", self.week())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.brain / f"context/weekly-overviews/{self.week()}.md").is_file())
        self.assertIn(f"[[context/weekly-sessions/{self.week()}|", note.read_text())
        self.assertIn(f"[[context/weekly-sources/{self.week()}|", note.read_text())


if __name__ == "__main__":
    unittest.main()
