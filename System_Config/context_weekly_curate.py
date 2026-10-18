#!/usr/bin/env python3
"""Publish a short English weekly context linked to selected source records."""
import argparse
import json
import os
from pathlib import Path
import sys

import context_weekly as weekly


MARKER = weekly.CURATED_MARKER


def summary_text(path):
    try:
        text = weekly.read_bytes(path, "summary", 8192).decode("utf-8").strip()
    except UnicodeDecodeError:
        weekly.fail("summary is not UTF-8")
    if not text:
        weekly.fail("summary is empty")
    return text


def chosen_records(vault, week, stems):
    records = {record["stem"]: record for record in weekly.selected_records(vault, week)}
    if not stems or len(set(stems)) != len(stems):
        weekly.fail("select one or more unique source records")
    if any(stem not in records for stem in stems):
        weekly.fail("selected source record is not in this week")
    return [records[stem] for stem in stems]


def existing(path, week):
    if not os.path.lexists(path):
        return None
    data = weekly.read_bytes(path, "weekly context")
    heading = ("# Weekly context — " + week + "\n").encode()
    if not data.startswith(MARKER + heading):
        weekly.fail("weekly context conflicts with human file")
    return data


def render(week, summary, records):
    lines = [MARKER.decode().rstrip(), "# Weekly context — " + week, "", "## Summary", "", summary,
             "", "## Sources", ""]
    lines.extend("- [[source-records/" + record["stem"] + "|" + record["provider"] +
                 " source record]]" for record in records)
    return ("\n".join(lines) + "\n").encode()


def publish(vault_path, week, summary_path, stems):
    vault = Path(vault_path)
    weekly.week_bounds(week)
    summary = summary_text(Path(summary_path))
    records = chosen_records(vault, week, stems)
    output = vault / "context" / "weekly-context" / (week + ".md")
    prior = existing(output, week)
    archive = vault / "context" / "weekly-sources" / (week + ".md")
    prior_archive = weekly.generated_archive(archive)
    weekly.write_generated(output, prior, render(week, summary, records), MARKER, "weekly context")
    weekly.write_generated(archive, prior_archive, weekly.archive_text(
        week, weekly.selected_records(vault, week), output, weekly.automatic_overview(vault, week)))
    return {"week": week, "sources": len(records)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--week", required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--source", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        print(json.dumps(publish(args.vault, args.week, args.summary, args.source), sort_keys=True))
    except ValueError as error:
        print("context curate failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())

