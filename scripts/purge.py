#!/usr/bin/env python
"""Remove events older than a given age, with their recordings.

    uv run python scripts/purge.py --older-than 30 --dry-run
    uv run python scripts/purge.py --older-than 30

Nothing here runs on a timer. Recordings are people's voices, and deleting one
somebody still needs on a schedule they did not set is worse than a directory
that grows. This is the operator deciding.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server import purge_older_than


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--older-than", type=int, required=True, metavar="DAYS",
                        help="Remove events created more than this many days ago")
    parser.add_argument("--dry-run", action="store_true",
                        help="List what would go, remove nothing")
    args = parser.parse_args()

    try:
        found = purge_older_than(args.older_than, dry_run=args.dry_run)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not found:
        print(f"Nothing older than {args.older_than} days.")
        return 0

    verb = "Would remove" if args.dry_run else "Removed"
    total_subs = sum(e["submissions"] for e in found)
    print(f"{verb} {len(found)} event(s), {total_subs} recording(s):\n")
    for e in found:
        line = f"  {e['name']}  ({e['submissions']} team(s), created {e['created_at'][:10]})"
        if not args.dry_run:
            line += f"  {e.get('audio_files_removed', 0)} file(s) deleted"
        print(line)

    if args.dry_run:
        print(f"\nNothing was deleted. Re-run without --dry-run to remove them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
