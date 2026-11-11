"""Post output/notifications.json as GitHub issues (GitHub emails them to the repository owner).

    uv run python -m hrt.post output/notifications.json            # needs gh and GH_TOKEN
    uv run python -m hrt.post output/notifications.json --dry-run  # print what would be posted
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

LABELS = {
    "update": ("0E8A16", "Daily petition updates"),
    "session-report": ("B60205", "Petitions that died when a session ended"),
}


def gh(*args: str, dry_run: bool) -> None:
    if dry_run:
        print("gh", " ".join(repr(a) if " " in a else a for a in args))
        return
    subprocess.run(["gh", *args], check=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    notes = json.loads(args.file.read_text()) if args.file.exists() else []
    if not notes:
        print("No notifications.")
        return 0
    for label in sorted({l for n in notes for l in n["labels"]}):
        color, desc = LABELS.get(label, ("BFD4F2", ""))
        gh("label", "create", label, "--color", color, "--description", desc, "--force", dry_run=args.dry_run)
    for n in notes:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(n["body"])
        gh("issue", "create", "--title", n["title"], "--label", ",".join(n["labels"]), "--body-file", f.name,
           dry_run=args.dry_run)
        if args.dry_run:
            print(f"  body: {len(n['body'])} chars, starts: {n['body'][:80]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
