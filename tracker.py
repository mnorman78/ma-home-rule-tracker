#!/usr/bin/env python3
"""Track Boston's home rule petitions from City Hall through the Massachusetts Legislature.

    uv run tracker.py                       # last 10 years (six two-year sessions to now)
    uv run tracker.py --since 193           # from a given session
    uv run tracker.py --no-summaries        # skip the Claude API step
    uv run tracker.py --check-elections     # check for delegation and council roster changes
    uv run tracker.py --check-delegation    # list who delegation.json selects

Writes output/<city>.json, output/<city>.html and output/changelog.json. If a
previous output/<city>.json exists (locally, or downloaded from the published
site by the scheduled job), the differences are recorded as "What's new".
API responses are cached in cache/; generated summaries in data/summaries.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from collections import Counter

from hrt.api import Client, court_years, current_court, ordinal
from hrt.categories import LABELS, ROUTINE
from hrt.changes import diff, load_json, update_changelog
from hrt.council import Legistar, Roster, council_petitions
from hrt.delegation import all_members, delegation, load_rules
from hrt.elections import alerts_markdown, calendar, check_council_roster, check_delegation as check_delegation_changes
from hrt.matching import load_overrides
from hrt.notify import build_notifications
from hrt.pipeline import COUNCIL_FROM, attach_council, build
from hrt.report import render
from hrt.summaries import Summarizer

ROOT = Path(__file__).resolve().parent


def list_delegation(client: Client, rules: list[dict], courts: list[int]) -> None:
    for court in courts:
        members = all_members(client, court)
        deleg = delegation(rules, court, members)
        print(f"\n{ordinal(court)} General Court ({court_years(court)}): {len(deleg)} members")
        for m in sorted(deleg.values(), key=lambda m: (m["branch"], m["district"])):
            print(f"  {m['branch']:6}  {m['district']:32}  {m['name']}")


def job_summary(text: str) -> None:
    """Write to the GitHub Actions run summary when running there."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(text + "\n")


def run_election_checks(args, client: Client, rules: list[dict], slug: str) -> int:
    today = dt.date.today()
    previous = load_json(args.out / f"{slug}.json")
    deleg_result, deleg_alerts = check_delegation_changes(client, rules, previous)
    legistar = Legistar(ROOT / "cache", offline=args.offline)
    roster_result, roster_alerts = check_council_roster(legistar, Roster(ROOT / "data" / "council_roster.json"))
    cal = calendar(today)
    alerts = deleg_alerts + roster_alerts

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "elections.json").write_text(json.dumps({
        "checked": today.isoformat(), "delegation": deleg_result, "council": roster_result,
        "alerts": alerts, "calendar": cal}, indent=1, ensure_ascii=False))
    md = alerts_markdown(deleg_alerts, roster_alerts, cal, today)
    (args.out / "alerts.md").write_text(md if alerts else "")
    job_summary("## Election and roster check\n\n" + md)

    print(f"Delegation ({ordinal(deleg_result['court'])} General Court): {deleg_result['members']} members"
          f"{'' if deleg_result['compared'] else ' (no published run to compare with)'}")
    print(f"Council minutes checked: {len(roster_result['meetings_checked'])} meetings; {len(roster_result['serving'])} councilors on the roster today")
    print(f"{len(alerts)} alert(s)" + "".join(f"\n  - {a}" for a in alerts))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", default="Boston")
    ap.add_argument("--since", type=int, default=None, help="first General Court to include (default: 10 years back)")
    ap.add_argument("--until", type=int, default=None, help="last General Court to include (default: current)")
    ap.add_argument("--no-summaries", action="store_true", help="don't call the Claude API")
    ap.add_argument("--offline", action="store_true", help="use only cached API responses")
    ap.add_argument("--check-elections", action="store_true", help="check for delegation and council roster changes")
    ap.add_argument("--check-delegation", action="store_true", help="list who delegation.json selects")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    args = ap.parse_args(argv)

    client = Client(ROOT / "cache", offline=args.offline)
    rules = load_rules(ROOT / "delegation.json")
    until = args.until or current_court()
    since = args.since or until - 5  # six two-year sessions, e.g. 2015-16 through 2025-26
    courts = list(range(until, since - 1, -1))
    slug = args.city.lower().replace(" ", "-")

    if args.check_delegation:
        list_delegation(client, rules, courts)
        return 0
    if args.check_elections:
        return run_election_checks(args, client, rules, slug)

    previous = load_json(args.out / f"{slug}.json")
    changelog = load_json(args.out / "changelog.json") or []

    summarizer = Summarizer(ROOT / "data" / "summaries.json", enabled=not args.no_summaries)
    print(f"Building {args.city} home rule petitions, {court_years(since)} to {court_years(until)}…", file=sys.stderr)
    dataset = build(client, args.city, courts, rules, summarizer)

    if args.city == "Boston":
        print(f"Reading City Council dockets and minutes since {COUNCIL_FROM}…", file=sys.stderr)
        legistar = Legistar(ROOT / "cache", offline=args.offline)
        council = council_petitions(legistar, Roster(ROOT / "data" / "council_roster.json"), since=COUNCIL_FROM)
        attach_council(dataset, council, load_overrides(ROOT / "data" / "council_matches.json"))
    else:
        dataset["council_petitions"], dataset["council_from"] = [], None
        for p in dataset["petitions"]:
            p["council"] = None

    counts = Counter(p.get("category") for p in dataset["petitions"])
    dataset["categories"] = [{"key": k, "label": label, "routine": k in ROUTINE, "count": counts[k]}
                             for k, label in LABELS.items() if counts[k]]

    events = diff(previous, dataset)
    changelog = update_changelog(changelog, events)
    dataset["changes"] = changelog[:200]
    dataset["calendar"] = calendar()
    notifications = build_notifications(previous, dataset, events, site=os.environ.get("SITE_URL"),
                                        mention=os.environ.get("NOTIFY_MENTION"), today=dt.date.today().isoformat())

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "notifications.json").write_text(json.dumps(notifications, indent=1, ensure_ascii=False))
    for n in notifications:
        print(f"Notification: {n['title']}")
    (args.out / f"{slug}.json").write_text(json.dumps(dataset, indent=1, ensure_ascii=False))
    (args.out / "changelog.json").write_text(json.dumps(changelog, indent=1, ensure_ascii=False))
    (args.out / f"{slug}.html").write_text(render(dataset))
    (args.out / "index.html").write_text(render(dataset))

    ps = dataset["petitions"]
    by: dict[str, int] = {}
    for p in ps:
        by[p["status"]] = by.get(p["status"], 0) + 1
    with_votes = sum(1 for p in ps if p["roll_calls"] or any(f.get("vote_type") == "roll call" for f in p["floor"].values()))
    summarized = sum(1 for p in ps if p["summary_source"] == "claude")
    print(f"\n{len(ps)} petitions · " + " · ".join(f"{n} {s.lower()}" for s, n in by.items()))
    print(f"{with_votes} with a recorded roll call · {summarized} with Claude summaries · {client.requests} API requests")
    cps = dataset["council_petitions"]
    if cps:
        linked = sum(1 for p in ps if p["council"])
        rc = [c for c in cps if (c["vote"] or {}).get("kind") == "roll call"]
        print(f"City Council: {len(cps)} dockets since {dataset['council_from'][:4]} · {len(rc)} roll calls "
              f"({sum(c['vote']['complete'] for c in rc)} complete) · {linked} state petitions linked to a docket")
    if previous is None:
        print("No previous run to compare with; changes are tracked from the next run.")
    else:
        print(f"{len(events)} change(s) since the previous run" + "".join(f"\n  - {e['title'][:70]}: {e['text']}" for e in events[:25]))
    job_summary(f"## Tracker run\n\n{len(ps)} petitions, {len(cps)} council dockets. "
                + (f"{len(events)} change(s):\n\n" + "\n".join(f"- **{e['title']}**: {e['text']}" for e in events)
                   if previous is not None else "First run; no previous data to compare."))
    print(f"Wrote output/{slug}.json, output/{slug}.html, output/index.html, output/changelog.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
