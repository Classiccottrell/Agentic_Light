#!/usr/bin/env python3
"""Deterministic publication/flush races and legacy open-FD compatibility."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_lock
import log_session


class Spool(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="session-spool.")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.note = self.root / "note.md"
        self.note.write_text("## Agent Sessions\n\n---\n", encoding="utf-8")
        patcher = mock.patch.object(log_session, "PENDING", self.root / "log_session.pending")
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"BRAIN_LOCK_TEST": "1", "BRAIN_LOCK_DIR": str(self.root / "brain.lock.d")})
        env.start()
        self.addCleanup(env.stop)
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.addCleanup(brain_lock.release)

    def entry(self, status="11"):
        return {"provider": "claude", "role": "coder", "status": status, "reason": "exit",
                "note": str(self.note), "metadata": [], "ts": "2026-10-23 12:00:00"}

    def text(self):
        return self.note.read_text(encoding="utf-8")

    def test_publish_before_snapshot_replays_once(self):
        log_session._spool(self.entry())
        queue = log_session.pending_ready()
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].stat().st_mode & 0o777, 0o600)
        log_session.flush_pending()
        log_session.flush_pending()
        self.assertEqual(self.text().count("exit 11"), 1)
        self.assertFalse(log_session.pending_ready())

    def test_flush_before_publication_cannot_consume_open_file(self):
        replace = os.replace
        def before_publish(source, dest):
            if ".entry." in str(dest):
                log_session.flush_pending()
                self.assertNotIn("exit 11", self.text())
            return replace(source, dest)
        with mock.patch.object(os, "replace", side_effect=before_publish):
            log_session._spool(self.entry())
        self.assertEqual(len(log_session.pending_ready()), 1)
        log_session.flush_pending()
        self.assertIn("exit 11", self.text())

    def test_publication_after_snapshot_waits_for_next_flush(self):
        snapshot = log_session.pending_ready
        def publish_after_snapshot():
            captured = snapshot()
            log_session._spool(self.entry())
            return captured
        with mock.patch.object(log_session, "pending_ready", side_effect=publish_after_snapshot):
            log_session.flush_pending()
        self.assertNotIn("exit 11", self.text())
        self.assertEqual(len(snapshot()), 1)
        log_session.flush_pending()
        self.assertIn("exit 11", self.text())

    def test_old_append_fd_survives_legacy_drain(self):
        pending = log_session.PENDING
        pending.write_bytes((json.dumps(self.entry()) + "\n").encode("utf-8"))
        with open(pending, "ab") as old_writer:
            log_session.flush_pending()
            self.assertFalse(log_session.legacy_pending())
            old_writer.write((json.dumps(self.entry("22")) + "\n").encode("utf-8"))
            old_writer.flush()
        self.assertTrue(log_session.legacy_pending())
        log_session.flush_pending()
        self.assertEqual(self.text().count("exit 11"), 1)
        self.assertEqual(self.text().count("exit 22"), 1)
        self.assertTrue(pending.exists())
        self.assertFalse(log_session.legacy_pending())

    def test_historical_flushing_file_is_visible_replayed_and_retained(self):
        historical = log_session.PENDING.with_name(log_session.PENDING.name + ".flushing.12345")
        historical.write_bytes((json.dumps(self.entry()) + "\n").encode("utf-8"))
        ignored = log_session.PENDING.with_name(log_session.PENDING.name + ".flushing.not-a-pid")
        ignored.write_bytes(b'{"wrong": true}\n')
        identity = historical.stat().st_ino
        self.assertTrue(log_session.legacy_pending())
        log_session.flush_pending()
        log_session.flush_pending()
        self.assertEqual(self.text().count("exit 11"), 1)
        self.assertEqual(historical.stat().st_ino, identity)
        self.assertTrue(ignored.exists())
        self.assertFalse(log_session.legacy_pending())
        self.assertFalse(log_session.PENDING.with_name(log_session.PENDING.name + ".failed").exists())

    def test_old_append_fd_to_historical_flushing_file_survives_drain(self):
        historical = log_session.PENDING.with_name(log_session.PENDING.name + ".flushing.12345")
        historical.write_bytes((json.dumps(self.entry()) + "\n").encode("utf-8"))
        with open(historical, "ab") as old_writer:
            log_session.flush_pending()
            self.assertFalse(log_session.legacy_pending())
            old_writer.write((json.dumps(self.entry("22")) + "\n").encode("utf-8"))
            old_writer.flush()
        self.assertTrue(log_session.legacy_pending())
        log_session.flush_pending()
        self.assertEqual(self.text().count("exit 11"), 1)
        self.assertEqual(self.text().count("exit 22"), 1)
        self.assertTrue(historical.exists())
        self.assertFalse(log_session.legacy_pending())

    def test_only_complete_legacy_lf_records_advance_cursor(self):
        pending = log_session.PENDING
        raw = json.dumps(self.entry()).encode("utf-8")
        pending.write_bytes(raw)
        log_session.flush_pending()
        self.assertNotIn("exit 11", self.text())
        self.assertTrue(log_session.legacy_pending())
        with open(pending, "ab") as writer:
            writer.write(b"\n")
        log_session.flush_pending()
        self.assertEqual(self.text().count("exit 11"), 1)
        self.assertFalse(log_session.legacy_pending())

    def test_legacy_replacement_and_truncation_reset_conservatively(self):
        pending = log_session.PENDING
        pending.write_bytes((json.dumps(self.entry()) + "\n").encode("utf-8"))
        log_session.flush_pending()
        pending.write_bytes((json.dumps(self.entry("22")) + "\n").encode("utf-8"))
        log_session.flush_pending()
        replacement = self.root / "replacement"
        replacement.write_bytes((json.dumps(self.entry("33")) + "\n").encode("utf-8"))
        os.replace(str(replacement), str(pending))
        log_session.flush_pending()
        for status in ("11", "22", "33"):
            self.assertEqual(self.text().count("exit " + status), 1)

    def test_malformed_published_entry_is_parked(self):
        log_session._spool({"wrong": True})
        log_session.flush_pending()
        self.assertFalse(log_session.pending_ready())
        self.assertIn('"wrong": true', log_session.PENDING.with_name(log_session.PENDING.name + ".failed").read_text(encoding="utf-8"))

    def test_failed_park_retains_published_entry_for_retry(self):
        log_session._spool({"wrong": True})
        with mock.patch.object(log_session, "_park", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                log_session.flush_pending()
        self.assertEqual(len(log_session.pending_ready()), 1)
        log_session.flush_pending()
        self.assertFalse(log_session.pending_ready())

    def test_failed_park_does_not_advance_legacy_cursor(self):
        log_session.PENDING.write_bytes(b'{"wrong": true}\n')
        with mock.patch.object(log_session, "_park", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                log_session.flush_pending()
        self.assertFalse(log_session.PENDING.with_name(log_session.PENDING.name + ".cursor").exists())
        self.assertTrue(log_session.legacy_pending())
        log_session.flush_pending()
        self.assertFalse(log_session.legacy_pending())

    def test_flusher_requires_ownership(self):
        brain_lock.release()
        with self.assertRaises(RuntimeError):
            log_session.flush_pending()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
