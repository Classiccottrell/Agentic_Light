#!/usr/bin/env python3
"""Publish a weekly, source-linked view of generated context records."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


ARCHIVE_MARKER = b"<!-- context-weekly: generated v1 -->\n"
SESSIONS_MARKER = b"<!-- context-weekly-sessions: generated v1 -->\n"
CURATED_MARKER = b"<!-- context-curated-summary: generated v1 -->\n"
AUTO_SUMMARY_MARKER = b"<!-- context-auto-summary: generated v1 -->\n"
LINK_START = b"<!-- context-weekly-link:start -->"
LINK_END = b"<!-- context-weekly-link:end -->"
INTAKE_MARKER = b"<!-- generated-context-intake-v1 -->"
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
CLASSIFICATIONS = ("work", "personal", "unsorted")
AI_PROVIDERS = {"claude", "codex", "antigravity"}


def fail(message):
    raise ValueError(message)


def regular(path, label):
    try:
        info = path.lstat()
    except OSError:
        fail(label + " unavailable")
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        fail(label + " is not a regular file")
    return info


def directory(path, label):
    try:
        info = path.lstat()
    except OSError:
        fail(label + " unavailable")
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        fail(label + " is not a directory")


def week_bounds(week):
    if not re.fullmatch(r"\d{4}-W\d{2}", week):
        fail("week must be YYYY-Www")
    try:
        start = dt.date.fromisocalendar(int(week[:4]), int(week[-2:]), 1)
    except ValueError:
        fail("week must be YYYY-Www")
    return start, start + dt.timedelta(days=6)


def read_bytes(path, label, limit=16384):
    info = regular(path, label)
    if info.st_size > limit:
        fail(label + " exceeds limit")
    try:
        data = path.read_bytes()
    except OSError:
        fail(label + " unreadable")
    regular(path, label)
    return data


def source_record(path):
    data = read_bytes(path, "source record")
    if not data.startswith(b"---\n") or INTAKE_MARKER not in data:
        fail("malformed source record")
    try:
        ending = data.index(b"\n---\n", 4)
        frontmatter = data[4:ending].decode("ascii")
    except (ValueError, UnicodeDecodeError):
        fail("malformed source record")
    fields = {}
    for line in frontmatter.splitlines():
        if ": " not in line:
            fail("malformed source record")
        key, value = line.split(": ", 1)
        if key in fields:
            fail("malformed source record")
        fields[key] = value
    if set(fields) != {"generated", "provider", "age", "classification", "status", "date"}:
        fail("malformed source record")
    if fields["generated"] != "context-intake-v1" or not TOKEN.fullmatch(fields["provider"]):
        fail("malformed source record")
    if fields["age"] not in {"old", "current"} or fields["classification"] not in CLASSIFICATIONS:
        fail("malformed source record")
    if not TOKEN.fullmatch(fields["status"]):
        fail("malformed source record")
    try:
        record_date = dt.date.fromisoformat(fields["date"])
    except ValueError:
        fail("malformed source record")
    try:
        body = data[ending + 5:].decode("ascii")
    except UnicodeDecodeError:
        fail("malformed source record")
    matches = re.findall(r"(?m)^private-source:sha256:([0-9a-f]{64})$", body)
    if len(matches) != 1 or not HASH.fullmatch(matches[0]):
        fail("malformed source record")
    if path.name != fields["provider"] + "-" + matches[0][:12] + "-" + fields["date"] + ".md":
        fail("malformed source record")
    return {"provider": fields["provider"], "classification": fields["classification"],
            "status": fields["status"], "date": record_date, "hash": matches[0], "stem": path.stem}


def selected_records(vault, week):
    start, end = week_bounds(week)
    directory(vault, "vault")
    context = vault / "context"
    if not os.path.lexists(context):
        return []
    directory(context, "context")
    records = context / "source-records"
    if not os.path.lexists(records):
        return []
    directory(records, "source records")
    selected = []
    for path in sorted(records.glob("*.md")):
        record = source_record(path)
        if start <= record["date"] <= end:
            selected.append(record)
    return selected


def curated_summary(vault, week):
    path = vault / "context" / "weekly-context" / (week + ".md")
    if not os.path.lexists(path):
        return None
    data = read_bytes(path, "curated summary")
    heading = ("# Weekly context — " + week + "\n").encode()
    if not data.startswith(CURATED_MARKER + heading):
        fail("curated summary conflicts with human file")
    return path


def automatic_overview(vault, week):
    path = vault / "context" / "weekly-overviews" / (week + ".md")
    if not os.path.lexists(path):
        return None
    data = read_bytes(path, "weekly overview")
    heading = ("# Weekly context overview — " + week + "\n").encode()
    if not data.startswith(AUTO_SUMMARY_MARKER + heading):
        fail("weekly overview conflicts with human file")
    return path


def archive_text(week, records, curated=None, overview=None):
    lines = [ARCHIVE_MARKER.decode().rstrip(), f"# Gathered context sources — {week}", "",
             "Generated links point to hash-only source records; raw sources remain private.", ""]
    for classification in CLASSIFICATIONS:
        lines.extend(("## " + classification.title(), ""))
        grouped = [record for record in records if record["classification"] == classification]
        if grouped:
            displayed = {}
            for record in grouped:
                displayed.setdefault((record["provider"], record["hash"], record["status"]), []).append(record)
            for records_for_source in displayed.values():
                record = records_for_source[0]
                dates = sorted(item["date"].isoformat() for item in records_for_source)
                observed = dates[0] if len(dates) == 1 else dates[0] + " to " + dates[-1]
                lines.append("- [[source-records/" + record["stem"] + "|" + record["provider"] +
                             " source record]] · " + record["hash"][:12] + " · " + record["status"] +
                             " · observed " + observed)
        else:
            lines.append("- No " + classification + " source records.")
        lines.append("")
    if curated is not None:
        lines.extend(("## Curated summary", "",
                      "- [[weekly-context/" + week + "|Read the English weekly context]]", ""))
    if overview is not None:
        lines.extend(("## Automatic overview", "",
                      "- [[weekly-overviews/" + week + "|Read the automatic weekly overview]]", ""))
    return ("\n".join(lines) + "\n").encode()


def sessions_text(week, records):
    lines = [SESSIONS_MARKER.decode().rstrip(), f"# Extracted AI sessions — {week}", "",
             "Generated links point to hash-only session records; raw sessions remain private.", ""]
    for classification in CLASSIFICATIONS:
        lines.extend(("## " + classification.title(), ""))
        grouped = [record for record in records if record["classification"] == classification and
                   record["provider"] in AI_PROVIDERS]
        if grouped:
            displayed = {}
            for record in grouped:
                displayed.setdefault((record["provider"], record["hash"], record["status"]), []).append(record)
            for records_for_source in displayed.values():
                record = records_for_source[0]
                dates = sorted(item["date"].isoformat() for item in records_for_source)
                observed = dates[0] if len(dates) == 1 else dates[0] + " to " + dates[-1]
                lines.append("- [[source-records/" + record["stem"] + "|" + record["provider"] +
                             " session record]] · " + record["hash"][:12] + " · " + record["status"] +
                             " · observed " + observed)
        else:
            lines.append("- No " + classification + " AI session records.")
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


def generated_archive(path, marker=ARCHIVE_MARKER, label="weekly archive"):
    if not os.path.lexists(path):
        return None
    data = read_bytes(path, label)
    if not data.startswith(marker):
        fail(label + " conflicts with human file")
    return data


def write_generated(path, expected, data, marker=ARCHIVE_MARKER, label="weekly archive"):
    path.parent.mkdir(parents=True, exist_ok=True)
    if expected is None:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            fail(label + " changed during publish")
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        return
    if read_bytes(path, label) != expected or not expected.startswith(marker):
        fail(label + " changed during publish")
    fd, temporary = tempfile.mkstemp(prefix=".context-weekly-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def note_update(vault, week, note):
    expected = vault / "weekly_logs" / week[:4] / (week + ".md")
    if not note.is_absolute():
        if note == expected:
            pass
        elif note == Path("weekly_logs") / week[:4] / (week + ".md"):
            note = expected
        else:
            fail("weekly note does not exist")
    if note != expected or not os.path.lexists(note):
        fail("weekly note does not exist")
    original = read_bytes(note, "weekly note", 131072)
    starts = [match.start() for match in re.finditer(re.escape(LINK_START), original)]
    ends = [match.start() for match in re.finditer(re.escape(LINK_END), original)]
    if len(starts) != len(ends) or len(starts) > 1 or (starts and starts[0] > ends[0]):
        fail("weekly note link block conflicts with human text")
    block = LINK_START + b"\n" + ("[[context/weekly-sessions/" + week +
                                    "|Extracted AI sessions for " + week + "]]" ).encode() + b"\n" + (
                                    "[[context/weekly-sources/" + week +
                                    "|Gathered context sources for " + week + "]]" ).encode() + b"\n" + LINK_END + b"\n"
    if starts:
        end = ends[0] + len(LINK_END)
        if original[end:end + 1] == b"\n":
            end += 1
        updated = original[:starts[0]] + block + original[end:]
    else:
        separator = b"" if original.endswith(b"\n") else b"\n"
        updated = original + separator + b"\n" + block
    return note, original, updated


def write_note(path, original, updated):
    if updated == original:
        return
    info = regular(path, "weekly note")
    if read_bytes(path, "weekly note", 131072) != original:
        fail("weekly note changed during publish")
    fd, temporary = tempfile.mkstemp(prefix=".context-weekly-note-", dir=path.parent)
    try:
        os.fchmod(fd, stat.S_IMODE(info.st_mode))
        with os.fdopen(fd, "wb") as output:
            output.write(updated)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def publish(vault_path, week, note=None):
    vault = Path(vault_path)
    records = selected_records(vault, week)
    archive = vault / "context" / "weekly-sources" / (week + ".md")
    expected_archive = generated_archive(archive)
    sessions = vault / "context" / "weekly-sessions" / (week + ".md")
    expected_sessions = generated_archive(sessions, SESSIONS_MARKER, "weekly sessions archive")
    curated = curated_summary(vault, week)
    overview = automatic_overview(vault, week)
    note_plan = note_update(vault, week, Path(note)) if note is not None else None
    write_generated(archive, expected_archive, archive_text(week, records, curated, overview))
    write_generated(sessions, expected_sessions, sessions_text(week, records), SESSIONS_MARKER, "weekly sessions archive")
    if note_plan is not None:
        write_note(*note_plan)
    return {"week": week, "records": len(records), "linked": note_plan is not None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--week", required=True)
    parser.add_argument("--note", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(publish(args.vault, args.week, args.note), sort_keys=True))
    except ValueError as error:
        print("context weekly failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())

