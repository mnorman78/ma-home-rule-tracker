"""What changed between two runs: new petitions, status and stage changes, new council votes.

The previous run's dataset is whatever was last published (the scheduled job
downloads it from GitHub Pages before running) or the local output/ copy.
Events accumulate in a changelog that the report shows as "What's new".
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .matching import petition_key

MAX_CHANGELOG = 1000


def _petitions(ds: dict) -> dict[str, dict]:
    return {petition_key(p): p for p in ds.get("petitions", []) if p.get("bill") or p.get("docket")}


def _council(ds: dict) -> dict[str, dict]:
    return {c["docket"]: c for c in ds.get("council_petitions", [])}


def _label(p: dict) -> str:
    return p.get("short_title") or p.get("title") or ""


def diff(old: dict | None, new: dict) -> list[dict]:
    if not old:
        return []
    today = dt.date.today().isoformat()
    events: list[dict] = []

    def add(kind: str, item: dict, text: str, **extra):
        events.append({"date": today, "kind": kind, "text": text, **extra, **item})

    op, np_ = _petitions(old), _petitions(new)
    # A docketed petition that gets its bill number changes key (194/HD4422 → 194/H5100); treat it as the same one.
    old_by_docket = {(p["court"], p.get("docket")): k for k, p in op.items() if p.get("docket")}
    renumbered: set[str] = set()
    for key, p in np_.items():
        ref = {"key": key, "title": _label(p), "url": p.get("url"), "court": p.get("court"),
               "bill": p.get("bill") or p.get("docket")}
        before = op.get(key)
        if not before and (p.get("court"), p.get("docket")) in old_by_docket:
            old_key = old_by_docket[(p["court"], p["docket"])]
            if old_key not in np_:
                before = op[old_key]
                renumbered.add(old_key)
        if not before:
            who = (p.get("transmitter") or {}).get("name")
            add("new_petition", ref, f"Filed at the State House{f' by {who}' if who else ''}",
                from_stage=None, to_stage=p.get("stage"))
            continue
        stages = {"from_stage": before.get("stage"), "to_stage": p.get("stage")}
        if p.get("status") != before.get("status"):
            text = f"{before.get('status')} → {p['status']}"
            if p.get("chapter"):
                text += f" ({p['chapter']})"
            add("status", ref, text, **stages)
        elif p.get("stage_label") != before.get("stage_label"):
            add("stage", ref, f"{before.get('stage_label')} → {p['stage_label']}", **stages)
        if p.get("council") and not before.get("council"):
            add("council_link", ref, f"Linked to City Council docket {p['council']['docket']}")
    for key in op.keys() - np_.keys() - renumbered:
        add("removed", {"key": key, "title": _label(op[key]), "url": op[key].get("url")},
            "No longer listed for Boston (renumbered or withdrawn)")

    oc, nc = _council(old), _council(new)
    for docket, c in nc.items():
        ref = {"key": f"council/{docket}", "title": c.get("title"), "url": c.get("url")}
        before = oc.get(docket)
        if not before:
            add("new_council", ref, "Filed with the City Council")
        if c.get("passed") and not (before or {}).get("passed"):
            v = c.get("vote") or {}
            tally = f" {v['yeas']}–{v['nays']}" if v.get("kind") == "roll call" else " by voice vote" if v.get("kind") == "voice vote" else ""
            add("council_passed", ref, f"Passed by the City Council{tally} on {c['passed']}")

    old_courts = {s["court"] for s in old.get("sessions", [])}
    for s in new.get("sessions", []):
        if s["court"] not in old_courts:
            add("session", {"key": f"session/{s['court']}", "title": f"{s['years']} session", "url": None},
                f"A new General Court convened ({s['years']})")
    return events


def update_changelog(previous: list[dict], events: list[dict]) -> list[dict]:
    return (events + previous)[:MAX_CHANGELOG]


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
