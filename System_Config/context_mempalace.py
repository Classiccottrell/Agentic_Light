#!/usr/bin/env python3
"""Mine explicitly manifested sources into a private local MemPalace index."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

from context_intake import CLASSIFICATIONS, FIELDS, digest, regular_file, token


def fail(message):
    raise ValueError(message)


def directory(path, label):
    try:
        info = path.lstat()
    except OSError:
        fail(label + " unavailable")
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        fail(label + " is not a directory")


def context_dir(vault):
    context = vault / "context"
    if os.path.lexists(context):
        directory(context, "context")
    else:
        context.mkdir()
        directory(context, "context")
    return context


def sources(manifest):
    regular_file(manifest)
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail("malformed manifest")
    if not isinstance(data, dict) or set(data) != {"sources"} or not isinstance(data["sources"], list):
        fail("malformed manifest")
    rows, seen = [], set()
    for raw in data["sources"]:
        if not isinstance(raw, dict) or set(raw) != FIELDS or not isinstance(raw["path"], str):
            fail("malformed manifest")
        row = {field: token(raw[field], field) for field in FIELDS if field != "path"}
        if row["classification"] not in CLASSIFICATIONS:
            fail("invalid classification")
        if row["age"] not in {"old", "current"}:
            fail("invalid age")
        source = Path(raw["path"])
        source_hash = digest(source)
        key = (row["provider"], source_hash)
        if key in seen:
            fail("duplicate source")
        seen.add(key)
        rows.append((source, source_hash, row))
    return rows


def mode(source, row):
    if row["provider"] in {"claude", "codex", "antigravity"} and source.suffix == ".jsonl":
        return "convos"
    if row["provider"] == "web-clipper" and source.suffix == ".md":
        return "projects"
    return None


def snapshot(vault, source, source_hash, row):
    staging = context_dir(vault) / "mempalace-staging"
    staging.mkdir(parents=True, exist_ok=True)
    directory(staging, "MemPalace staging")
    target = staging / (row["provider"] + "-" + source_hash[:12] + source.suffix)
    if os.path.lexists(target):
        regular_file(target)
        if digest(target) != source_hash:
            fail("MemPalace snapshot conflicts")
        return target
    fd, temporary = tempfile.mkstemp(prefix=".mempalace-", dir=staging)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output, source.open("rb") as input:
            while chunk := input.read(131072):
                output.write(chunk)
        if digest(Path(temporary)) != source_hash or digest(source) != source_hash:
            return None
        try:
            os.link(temporary, target)
        except FileExistsError:
            regular_file(target)
            if digest(target) != source_hash:
                fail("MemPalace snapshot conflicts")
        return target
    finally:
        Path(temporary).unlink(missing_ok=True)


def publish(vault_path, manifest_path, binary):
    vault = Path(vault_path)
    directory(vault, "vault")
    records = sources(Path(manifest_path))
    context = context_dir(vault)
    palace = context / "mempalace"
    if os.path.lexists(palace):
        directory(palace, "MemPalace index")
    else:
        try:
            initialized = subprocess.run([binary, "--palace", str(palace), "init", str(palace.parent),
                                         "--yes", "--no-llm", "--direct"], stdin=subprocess.DEVNULL,
                                        text=True, encoding="utf-8", capture_output=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired):
            fail("MemPalace initialization failed")
        if initialized.returncode:
            fail("MemPalace initialization failed")
    indexed = skipped = deferred = 0
    for source, before, row in records:
        selected = mode(source, row)
        if selected is None:
            skipped += 1
            continue
        staged = snapshot(vault, source, before, row)
        if staged is None:
            deferred += 1
            continue
        try:
            result = subprocess.run([binary, "--palace", str(palace), "mine", str(staged),
                                     "--mode", selected, "--wing", row["classification"], "--direct"],
                                    stdin=subprocess.DEVNULL, text=True, encoding="utf-8", capture_output=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired):
            fail("MemPalace mine failed")
        if result.returncode:
            fail("MemPalace mine failed")
        indexed += 1
    return {"deferred": deferred, "indexed": indexed, "skipped": skipped}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--bin", default="mempalace")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(publish(args.vault, args.manifest, args.bin), sort_keys=True))
    except ValueError as error:
        print("context MemPalace failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())

