#!/usr/bin/env python3
"""Publish the deterministic weekly context overview used by Friday closeout."""
import argparse
import json
import os
from pathlib import Path
import sys

import context_weekly as weekly


MARKER = weekly.AUTO_SUMMARY_MARKER


def existing(path, week):
    if not os.path.lexists(path):
        return None
    data = weekly.read_bytes(path, "weekly overview")
    if not data.startswith(MARKER + ("# Weekly context overview — " + week + "\n").encode()):
        weekly.fail("weekly overview conflicts with human file")
    return data


def render(week, records):
    counts = {classification: len({(record["provider"], record["hash"], record["status"])
                                  for record in records if record["classification"] == classification})
              for classification in weekly.CLASSIFICATIONS}
    lines = [MARKER.decode().rstrip(), "# Weekly context overview — " + week, "", "## Summary", "",
             "This week gathered {work} work source(s), {personal} personal source(s), and "
             "{unsorted} source(s) awaiting classification.".format(**counts),
             "Use the linked AI-session and gathered-context archives to review the sources.", ""]
    return ("\n".join(lines)).encode()


def publish(vault_path, week):
    vault = Path(vault_path)
    records = weekly.selected_records(vault, week)
    output = vault / "context" / "weekly-overviews" / (week + ".md")
    prior = existing(output, week)
    archive = vault / "context" / "weekly-sources" / (week + ".md")
    prior_archive = weekly.generated_archive(archive)
    weekly.write_generated(output, prior, render(week, records), MARKER, "weekly overview")
    weekly.write_generated(archive, prior_archive, weekly.archive_text(
        week, records, weekly.curated_summary(vault, week), output))
    return {"week": week, "sources": len(records)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--week", required=True)
    args = parser.parse_args(argv)
    try:
        weekly.week_bounds(args.week)
        print(json.dumps(publish(args.vault, args.week), sort_keys=True))
    except ValueError as error:
        print("context auto summary failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
