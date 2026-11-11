"""Election calendar and checks for changes in who represents Boston.

Calendar rules (no hardcoded dates, so it stays correct in future years):
- State election: even years, the Tuesday after the first Monday in November.
  The new General Court convenes the first Wednesday of January.
- Boston municipal election: odd years, same Tuesday. Mayor every four years
  (2025, 2029, ...). The new council term starts the first Monday of January.
Special elections aren't predictable, so the checks look at the data instead:

- Delegation: compares Boston's State House delegation in the Legislature's
  data now with the last published run.
- Council roster: reads recent City Council minutes for councilor names that
  data/council_roster.json doesn't know, and for roster members who stopped
  appearing. Either means the roster needs a hand update.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter

from .api import Client, court_years, current_court, ordinal
from .council import COUNCIL_BODY, Legistar, Roster, attendance
from .delegation import all_members, delegation, district_in_boston


def _nth_weekday(year: int, month: int, weekday: int, n: int = 1) -> dt.date:
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def election_day(year: int) -> dt.date:
    """The Tuesday after the first Monday in November."""
    return _nth_weekday(year, 11, 0) + dt.timedelta(days=1)


def calendar(today: dt.date | None = None, years_ahead: int = 4, days_back: int = 120) -> list[dict]:
    today = today or dt.date.today()
    events = []
    for year in range(today.year - 1, today.year + years_ahead + 1):
        if year % 2 == 0:
            court = 194 + (year + 1 - 2025) // 2
            events.append({"date": election_day(year).isoformat(), "kind": "state_election",
                           "title": "State election",
                           "detail": f"All 160 representatives and 40 senators, for the {ordinal(court)} General Court ({court_years(court)})."})
            events.append({"date": _nth_weekday(year + 1, 1, 2).isoformat(), "kind": "state_term",
                           "title": f"{ordinal(court)} General Court convenes",
                           "detail": "New legislators take office. The tracker switches sessions automatically."})
        else:
            mayor = (year - 2025) % 4 == 0
            events.append({"date": election_day(year).isoformat(), "kind": "city_election",
                           "title": "Boston municipal election",
                           "detail": "All 13 City Council seats" + (" and mayor." if mayor else ".")})
            events.append({"date": _nth_weekday(year + 1, 1, 0).isoformat(), "kind": "city_term",
                           "title": "New City Council term begins",
                           "detail": "Update data/council_roster.json with incoming and outgoing councilors."})
    lo, hi = today - dt.timedelta(days=days_back), today + dt.timedelta(days=365 * years_ahead)
    return sorted((e for e in events if lo.isoformat() <= e["date"] <= hi.isoformat()), key=lambda e: e["date"])


# --------------------------------------------------------------- checks

def check_delegation(client: Client, rules: list[dict], previous: dict | None) -> tuple[dict, list[str]]:
    """Compare the live delegation with the last published one."""
    court = current_court()
    alerts = []
    for c in (court, court + 1):
        try:
            district_in_boston(rules, c, "House", "1st Suffolk")
        except ValueError:
            alerts.append(f"delegation.json has no redistricting map for the {ordinal(c)} General Court "
                          f"({court_years(c)}). Add one before that session starts.")
    now = delegation(rules, court, all_members(client, court))
    before = {}
    for s in (previous or {}).get("sessions", []):
        if s["court"] == court:
            before = {m["code"]: m for m in s["delegation"]}
    added = [m for code, m in now.items() if code not in before] if before else []
    removed = [m for code, m in before.items() if code not in now] if before else []
    for m in added:
        alerts.append(f"New delegation member: {m['name']} ({m['branch']}, {m['district']}).")
    for m in removed:
        alerts.append(f"No longer in the delegation: {m['name']} ({m['branch']}, {m['district']}).")
    result = {"court": court, "members": len(now), "added": added, "removed": removed, "compared": bool(before)}
    return result, alerts


# "Councilor Flynn", "Councilors Breadon, Durkan, and Weber". Skips "former Councilor …".
NAME_RUN = re.compile(r"(?<![Ff]ormer )\bCouncilors? (?=[A-Z])")
# Words that can follow "Councilor" without being a name.
NOT_NAMES = {"President", "Vice", "Chair", "City", "Council", "The", "On", "Rule", "Elect", "At", "District", "Present", "Absent"}


def check_council_roster(lg: Legistar, roster: Roster, days: int = 90, today: dt.date | None = None) -> tuple[dict, list[str]]:
    """Look for councilors in recent minutes that the roster doesn't know, and roster members who disappeared."""
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()
    events = lg.get("/events", {"$filter": f"EventBodyId eq {COUNCIL_BODY} and EventDate ge datetime'{since}'",
                                "$orderby": "EventDate desc", "$top": "60"})
    unknown: Counter = Counter()
    seen: Counter = Counter()
    meetings = []
    attendance_problems = []
    for e in events:
        url = e.get("EventMinutesFile")
        if not url:
            continue
        date = e["EventDate"][:10]
        try:
            text = lg.minutes_text(url)
        except RuntimeError:
            continue
        meetings.append(date)
        flat = re.sub(r"\s+", " ", text)
        serving = set(roster.serving(date))
        for run in NAME_RUN.finditer(flat):
            names, rest = roster.read_names_rest(flat[run.end(): run.end() + 400])
            for n in names:
                seen[n] += 1
            # A capitalized word where the next name should be (first in the list, or after "," / "and")
            # that the roster doesn't know may be a new councilor.
            nxt = re.match(r"^(?:,\s*(?:and\s+)?|\s+and\s+|)([A-Z][\w'’é\-]+(?: [A-Z][\w'’é\-]+)?)", rest if names else rest.lstrip())
            if nxt and (not names or rest[:1] in ",a "):
                words = nxt.group(1).split()
                if words[0] not in NOT_NAMES:
                    unknown[" ".join(words)] += 1
        kind, att = attendance(text, roster)
        if kind == "present":
            missing_from_roster = [n for n in att if n not in serving]
            if missing_from_roster:
                attendance_problems.append(f"{date}: {', '.join(missing_from_roster)} present but not serving per roster")

    alerts = []
    for name, n in unknown.most_common():
        if n >= 2:
            alerts.append(f"Unrecognized councilor name in recent minutes: \"{name}\" ({n} mentions). "
                          "Add them to data/council_roster.json if they're a new councilor.")
    alerts.extend(f"Roster mismatch on {p}" for p in attendance_problems)
    if len(meetings) >= 3:
        for name in roster.serving(today.isoformat()):
            if seen[name] == 0:
                alerts.append(f"{name} is on the roster but not named in the last {len(meetings)} meetings' minutes. "
                              "If they've left the Council, set their end date in data/council_roster.json.")
    serving_now = roster.serving(today.isoformat())
    if len(serving_now) > 13:
        alerts.append(f"The roster lists {len(serving_now)} councilors serving today; the Council has 13 seats.")
    result = {"meetings_checked": meetings, "serving": serving_now, "unknown_names": dict(unknown)}
    return result, alerts


def alerts_markdown(delegation_alerts: list[str], roster_alerts: list[str], cal: list[dict], today: dt.date) -> str:
    lines = ["Automated check of who represents Boston, run " + today.isoformat() + ".", ""]
    if delegation_alerts:
        lines += ["### State House delegation", ""] + [f"- {a}" for a in delegation_alerts] + [""]
    if roster_alerts:
        lines += ["### City Council roster", ""] + [f"- {a}" for a in roster_alerts] + [""]
    upcoming = [e for e in cal if e["date"] >= today.isoformat()][:4]
    if upcoming:
        lines += ["### Upcoming", ""] + [f"- {e['date']}: {e['title']}. {e['detail']}" for e in upcoming]
    return "\n".join(lines) + "\n"
