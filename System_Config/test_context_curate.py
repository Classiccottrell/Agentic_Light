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


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()
