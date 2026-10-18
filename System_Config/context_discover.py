#!/usr/bin/env python3
"""Build a private intake manifest from explicitly configured local roots."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


MARKER = b"context-discover-v1\n"
PROVIDERS = {"claude", "codex", "antigravity", "web-clipper"}
AGES = {"old", "current"}
CLASSIFICATIONS = {"work", "personal", "unsorted"}
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SUFFIX = re.compile(r"^\.[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
FIELDS = {"provider", "root", "suffix", "age", "classification", "status"}


def fail(message):
    raise ValueError(message)


def regular(path, label):
    try:
        info = path.lstat()
    except OSError:
        fail(label + " unavailable")
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        fail(label + " is not a regular file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def directory(path, label):
    try:
        info = path.lstat()
    except OSError:
        fail(label + " unavailable")
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        fail(label + " is not a directory")


def token(value, field, allowed=None):
    if not isinstance(value, str) or not TOKEN.fullmatch(value) or (allowed and value not in allowed):
        fail("invalid " + field)
    return value


def load_config(path):
    regular(path, "config")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail("malformed config")
    if not isinstance(value, dict) or set(value) != {"sources"} or not isinstance(value["sources"], list):
        fail("malformed config")
    return value["sources"]


def entry(raw):
    if not isinstance(raw, dict) or set(raw) != FIELDS or not isinstance(raw["root"], str):
        fail("malformed config")
    result = {
        "provider": token(raw["provider"], "provider", PROVIDERS),
        "age": token(raw["age"], "age", AGES),
        "classification": token(raw["classification"], "classification", CLASSIFICATIONS),
        "status": token(raw["status"], "status"),
        "suffix": raw["suffix"],
    }
    if not isinstance(result["suffix"], str) or not SUFFIX.fullmatch(result["suffix"]):
        fail("invalid suffix")
    result["root"] = Path(raw["root"])
    if not result["root"].is_absolute():
        fail("source root must be absolute")
    return result


def candidates(config):
    root = config["root"]
    suffix = config["suffix"]
    try:
        info = root.lstat()
    except OSError:
        fail("source root unavailable")
    if root.is_symlink():
        fail("source root is a symlink")
    if stat.S_ISREG(info.st_mode):
        if not root.name.endswith(suffix):
            fail("source file does not match suffix")
        return [root]
    if not stat.S_ISDIR(info.st_mode):
        fail("source root is not regular")
    found = []

    def unreadable(_):
        fail("source root unreadable")

    for base, directories, files in os.walk(root, followlinks=False, onerror=unreadable):
        for name in sorted(directories):
            path = Path(base) / name
            if name.endswith(suffix):
                regular(path, "source candidate")
        for name in sorted(files):
            if name.endswith(suffix):
                path = Path(base) / name
                regular(path, "source candidate")
                found.append(path)
    return found


def output_state(path):
    marker = path.with_name(path.name + ".context-discover")
    exists = os.path.lexists(path)
    marker_exists = os.path.lexists(marker)
    if exists:
        output_identity = regular(path, "output")
        if not marker_exists:
            fail("output is not owned by context discovery")
        marker_identity = regular(marker, "output marker")
        try:
            if marker.read_bytes() != MARKER:
                fail("output marker is invalid")
        except OSError:
            fail("output marker unreadable")
    elif marker_exists:
        fail("output marker has no output")
    return marker, (output_identity, marker_identity) if exists else None


def safe_parent(path):
    for parent in (path.parent, *path.parent.parents):
        if not os.path.lexists(parent):
            continue
        directory(parent, "output parent")
        return


def atomic_write(path, data, replace_state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".context-discover-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if replace_state:
            _, current_state = output_state(path)
            if current_state != replace_state:
                fail("output changed during discovery")
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            Path(temporary).unlink()
    except FileExistsError:
        fail("output changed during discovery")
    except OSError:
        fail("output write failed")
    finally:
        Path(temporary).unlink(missing_ok=True)


def publish(config_path, output_path, date):
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        fail("invalid date")
    rows = []
    for raw in load_config(Path(config_path)):
        configured = entry(raw)
        for source in candidates(configured):
            rows.append({"path": str(source), "provider": configured["provider"],
                         "age": configured["age"], "classification": configured["classification"],
                         "status": configured["status"]})
    unique = {}
    for row in rows:
        prior = unique.get(row["path"])
        if prior is not None and prior != row:
            fail("duplicate source has conflicting metadata")
        unique[row["path"]] = row
    output = Path(output_path)
    safe_parent(output)
    marker, replace_state = output_state(output)
    data = (json.dumps({"sources": sorted(unique.values(), key=lambda row: row["path"])},
                       sort_keys=True, separators=(",", ":")) + "\n").encode()
    atomic_write(output, data, replace_state)
    if not marker.exists():
        try:
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output_marker:
                output_marker.write(MARKER)
        except OSError:
            fail("output marker write failed")
    return {"sources": len(unique)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(publish(args.config, args.out, args.date), sort_keys=True))
    except ValueError as error:
        print("context discovery failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())

