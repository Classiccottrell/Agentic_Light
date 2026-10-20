#!/usr/bin/env python3
"""Publish safe vault pointers for a private local source manifest."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import brain_lock


MARKER = "<!-- generated-context-intake-v1 -->"
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CLASSIFICATIONS = {"work", "personal", "unsorted"}
FIELDS = {"path", "provider", "age", "classification", "status"}


def fail(message):
    raise ValueError(message)


def regular_file(path):
    try:
        info = path.lstat()
    except OSError:
        fail("source unavailable")
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        fail("source is not a regular file")


def digest(path):
    regular_file(path)
    value = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(131072):
                value.update(chunk)
    except OSError:
        fail("source unreadable")
    regular_file(path)
    return value.hexdigest()


def token(value, field):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        fail("invalid " + field)
    return value


def record_text(row, source_hash, date):
    return "\n".join((
        "---", "generated: context-intake-v1", "provider: " + row["provider"],
        "age: " + row["age"], "classification: " + row["classification"],
        "status: " + row["status"], "date: " + date, "---", "", MARKER,
        "", "private-source:sha256:" + source_hash, "",
    )).encode()


def queue_text(rows, date):
    lines = ["---", "generated: context-intake-v1", "date: " + date, "---", "", MARKER,
             "", "# Unsorted context", "", "human classification required.", ""]
    if not rows:
        lines.append("No unsorted sources in this intake batch.")
    for row in rows:
        lines.append("- " + row["provider"] + " · " + row["hash"][:12] + " · " + row["status"])
    return ("\n".join(lines) + "\n").encode()


def existing_bytes(path):
    if not os.path.lexists(path):
        return None
    regular_file(path)
    try:
        return path.read_bytes()
    except OSError:
        fail("destination unreadable")


def safe_parent(vault, destination):
    current = vault
    try:
        info = current.lstat()
    except OSError:
        fail("vault unavailable")
    if current.is_symlink() or not stat.S_ISDIR(info.st_mode):
        fail("vault is not a directory")
    for part in destination.relative_to(vault).parts[:-1]:
        current = current / part
        if not os.path.lexists(current):
            return
        try:
            info = current.lstat()
        except OSError:
            fail("destination parent unavailable")
        if current.is_symlink() or not stat.S_ISDIR(info.st_mode):
            fail("destination parent is not a directory")


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fail("destination changed during intake")
    with os.fdopen(fd, "wb") as output:
        output.write(data)


def replace_generated(path, data):
    previous = existing_bytes(path)
    if previous is None:
        write_new(path, data)
        return
    if MARKER.encode() not in previous:
        fail("generated destination conflicts with human file")
    temporary = path.with_name("." + path.name + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fail("temporary destination exists")
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        fail("generated destination write failed")


def parse_manifest(path, date):
    regular_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail("malformed manifest")
    if not isinstance(data, dict) or set(data) != {"sources"} or not isinstance(data["sources"], list):
        fail("malformed manifest")
    rows = []
    seen = set()
    for raw in data["sources"]:
        if not isinstance(raw, dict) or set(raw) != FIELDS or not isinstance(raw["path"], str):
            fail("malformed manifest")
        row = {field: token(raw[field], field) for field in FIELDS if field != "path"}
        if row["classification"] not in CLASSIFICATIONS:
            fail("invalid classification")
        source = Path(raw["path"])
        source_hash = digest(source)
        key = (row["provider"], source_hash)
        if key in seen:
            fail("duplicate source")
        seen.add(key)
        row["hash"] = source_hash
        row["record"] = record_text(row, source_hash, date)
        rows.append(row)
    return rows


def publish(vault, manifest, date):
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        fail("invalid date")
    vault = Path(vault)
    rows = parse_manifest(Path(manifest), date)
    records = []
    for row in rows:
        path = vault / "context" / "source-records" / (
            row["provider"] + "-" + row["hash"][:12] + "-" + date + ".md")
        safe_parent(vault, path)
        existing = existing_bytes(path)
        if existing is not None and existing != row["record"]:
            fail("source record conflicts with existing file")
        records.append((path, row["record"], existing is None))
    unsorted = [row for row in rows if row["classification"] == "unsorted"]
    queue = None
    path = vault / "context" / ("unsorted-context-" + date + ".md")
    safe_parent(vault, path)
    existing = existing_bytes(path)
    if unsorted or existing is not None:
        data = queue_text(unsorted, date)
        if existing is not None and existing != data and MARKER.encode() not in existing:
            fail("generated destination conflicts with human file")
        queue = (path, data, existing != data)
    for path, data, needed in records:
        if needed:
            write_new(path, data)
    if queue and queue[2]:
        replace_generated(queue[0], queue[1])
    return {"records": len(rows), "unsorted": len(unsorted)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args(argv)
    with brain_lock.guard("context_intake", "wait", brain_lock.short_wait_seconds()) as held:
        if not held:
            return 75   # EX_TEMPFAIL: brain lock busy, nothing written
        return _run(args)


def _run(args):
    try:
        print(json.dumps(publish(args.vault, args.manifest, args.date), sort_keys=True))
    except ValueError as error:
        print("context intake failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())

