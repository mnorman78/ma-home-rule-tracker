"""Write a test notification (made-up example petitions) to output/notifications.json.

Used by the "Test notification" workflow to confirm that notification emails reach the owner.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hrt.notify import daily_issue  # noqa: E402

site = os.environ.get("SITE_URL")
events = [
    {"kind": "council_passed", "title": "Example: age waiver for a police officer", "bill": None, "url": site,
     "text": "Passed by the City Council 13–0 (example)"},
    {"kind": "new_petition", "title": "Example: real estate transfer fee and senior tax relief", "bill": "H0000", "url": site,
     "text": "Filed at the State House (example)", "from_stage": None, "to_stage": "committee"},
    {"kind": "stage", "title": "Example: office of district councilor", "bill": "S0000", "url": site,
     "text": "Reported out of committee → Passed one chamber (example)", "from_stage": "reported", "to_stage": "one"},
]
note = daily_issue(events, site, os.environ.get("NOTIFY_MENTION"), "test")
note["title"] = "Test notification: Boston home rule petition tracker"
note["body"] = ("**This is a test** to confirm notification emails reach you. The petitions below are made-up "
                "examples. You can close this issue.\n\n" + note["body"])
note["labels"] = ["test"]
out = Path("output")
out.mkdir(exist_ok=True)
(out / "notifications.json").write_text(json.dumps([note], indent=1, ensure_ascii=False))
print(note["title"])
