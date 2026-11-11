"""Notifications: turn a run's changes into GitHub issues, which GitHub emails to the repository owner.

Three kinds of daily alert:
- Passed by the City Council.
- Taken up by the Legislature: filed at the State House, hearing scheduled,
  or reported out of committee.
- Voted on in the Legislature: passed a chamber, enacted, signed, or vetoed.

And when a General Court ends (the tracker switches to the next session in
January of odd years), one issue listing every petition that died in it.

The tracker writes output/notifications.json; the workflow posts each entry
as an issue.
"""

from __future__ import annotations

from .api import court_years, ordinal
from .history import STAGES

TAKEN_UP = {"scheduled", "hearing", "reported"}
VOTED = {"one", "both", "enacted", "governor", "law", "vetoed"}


def _rank(stage: str | None) -> int:
    return STAGES[stage]["rank"] if stage in STAGES else 0


def classify(events: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"council": [], "taken_up": [], "voted": []}
    for e in events:
        kind, to, frm = e["kind"], e.get("to_stage"), e.get("from_stage")
        if kind == "council_passed":
            out["council"].append(e)
        elif kind == "new_petition":
            # A bill that shows up already past committee is reported by its furthest step.
            (out["voted"] if to in VOTED else out["taken_up"]).append(e)
        elif kind in ("status", "stage") and to != frm:
            if to in VOTED and _rank(to) > _rank(frm):
                out["voted"].append(e)
            elif to in TAKEN_UP and _rank(to) > _rank(frm):
                # "Hearing held" after "Hearing scheduled" was already notified isn't news.
                if not (to == "hearing" and frm == "scheduled"):
                    out["taken_up"].append(e)
    return out


SECTIONS = [
    ("council", "Passed by the Boston City Council"),
    ("taken_up", "Taken up by the Legislature"),
    ("voted", "Voted on in the Legislature"),
]
SHORT = {"council": "passed by the City Council", "taken_up": "taken up by the Legislature", "voted": "voted on by the Legislature"}


def _line(e: dict) -> str:
    title = f"[{e['title']}]({e['url']})" if e.get("url") else e["title"]
    bill = f"{e['bill']}: " if e.get("bill") else ""
    return f"- {bill}{title}  \n  {e['text']}"


def daily_issue(events: list[dict], site: str | None, mention: str | None, today: str) -> dict | None:
    groups = classify(events)
    n = sum(len(v) for v in groups.values())
    if not n:
        return None
    parts = [f"{mention} " if mention else ""]
    parts[0] += f"{n} update{'s' if n != 1 else ''} on Boston home rule petitions."
    counts = [f"{len(groups[k])} {SHORT[k]}" for k, _ in SECTIONS if groups[k]]
    for key, label in SECTIONS:
        if groups[key]:
            parts.append(f"### {label}\n\n" + "\n".join(_line(e) for e in groups[key]))
    if site:
        parts.append(f"Full report: {site}")
    return {
        "title": f"Home rule petitions, {today}: " + ", ".join(counts),
        "body": "\n\n".join(parts) + "\n",
        "labels": ["update"],
    }


def closed_sessions(old: dict | None, new: dict) -> list[int]:
    """Sessions that were current in the previous run and aren't any more."""
    if not old or "live_court" not in old:
        return []
    return list(range(old["live_court"], new["live_court"]))


def session_issue(dataset: dict, court: int, site: str | None, mention: str | None) -> dict:
    ps = [p for p in dataset["petitions"] if p["court"] == court]
    died = [p for p in ps if p["status"] in ("Died", "Died at end of session")]
    laws = [p for p in ps if p["status"] == "Became law"]
    name = f"{ordinal(court)} General Court ({court_years(court)})"

    def row(p):
        who = (p.get("transmitter") or {}).get("name") or "—"
        council = p.get("council") or {}
        cv = council.get("vote") or {}
        council_txt = ""
        if council.get("passed"):
            tally = f" {cv['yeas']}–{cv['nays']}" if cv.get("kind") == "roll call" else ""
            council_txt = f" · City Council passed {council['passed']}{tally}"
        num = p.get("bill") or p.get("docket") or ""
        title = p.get("short_title") or p.get("title")
        link = f"[{title}]({p['url']})" if p.get("url") else title
        return f"- {num}: {link}  \n  Furthest step: {p['stage_label']} · {who}{council_txt}"

    at_end = [p for p in died if p["status"] == "Died at end of session"]
    earlier = [p for p in died if p["status"] == "Died"]
    parts = [(f"{mention} " if mention else "") +
             f"The {name} has ended. Of {len(ps)} Boston home rule petitions, {len(laws)} became law and "
             f"{len(died)} died. Petitions that died need to be refiled (and usually re-approved by the "
             "City Council) to be taken up again."]
    if at_end:
        parts.append(f"### Still pending when the session ended ({len(at_end)})\n\n" + "\n".join(row(p) for p in at_end))
    if earlier:
        parts.append(f"### Ended earlier: sent to study, vetoed, or replaced ({len(earlier)})\n\n" + "\n".join(row(p) for p in earlier))
    if site:
        parts.append(f"Full report: {site}")
    return {
        "title": f"Session ended: {len(died)} Boston home rule petitions died in the {name}",
        "body": "\n\n".join(parts) + "\n",
        "labels": ["session-report"],
    }


def credentials_issue(error: str, mention: str | None) -> dict:
    """Raised when the Claude API rejects the tracker's credentials (an expired or revoked key, or a changed federation rule)."""
    return {
        "title": "Claude API sign-in failed: new petitions aren't getting summaries",
        "body": (f"{mention + ' ' if mention else ''}The daily update couldn't sign in to the Claude API, so new petitions "
                 "fall back to the Legislature's one-line descriptions. Everything else kept working.\n\n"
                 f"Error: `{error}`\n\n"
                 "To fix:\n"
                 "- **Using an API key:** create a new key at platform.claude.com/settings/keys and update the "
                 "`ANTHROPIC_API_KEY` repository secret.\n"
                 "- **Better, no key to expire:** set up Workload Identity Federation (see the README's Automation section).\n\n"
                 "Summaries that were missed are written on the next successful run. Close this issue once it's fixed; "
                 "it won't be reopened while it stays open.\n"),
        "labels": ["credentials"],
        "dedupe": True,
    }


def build_notifications(old: dict | None, new: dict, events: list[dict], site: str | None,
                        mention: str | None, today: str, auth_error: str | None = None) -> list[dict]:
    out = []
    if auth_error:
        out.append(credentials_issue(auth_error, mention))
    daily = daily_issue(events, site, mention, today)
    if daily:
        out.append(daily)
    for court in closed_sessions(old, new):
        out.append(session_issue(new, court, site, mention))
    return out
