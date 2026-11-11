"""Read a bill's history: how far it got, and how it moved through each chamber."""

from __future__ import annotations

import datetime as dt
import html
import re

# Stages in order of progress. `dead` marks ends that can't become law this session.
STAGES = {
    "law":       {"rank": 90, "label": "Signed into law"},
    "governor":  {"rank": 80, "label": "On the Governor's desk"},
    "vetoed":    {"rank": 75, "label": "Vetoed",                   "dead": True},
    "enacted":   {"rank": 70, "label": "Enacted"},
    "both":      {"rank": 60, "label": "Passed both chambers"},
    "one":       {"rank": 50, "label": "Passed one chamber"},
    "reported":  {"rank": 40, "label": "Reported out of committee"},
    "hearing":   {"rank": 30, "label": "Committee hearing held"},
    "scheduled": {"rank": 25, "label": "Hearing scheduled"},
    "committee": {"rank": 20, "label": "In committee"},
    "filed":     {"rank": 10, "label": "Filed"},
    "replaced":  {"rank": 5,  "label": "Replaced by another bill", "dead": True},
    "study":     {"rank": 3,  "label": "Sent to study",            "dead": True},
}

COMMITTEE_SKIP = re.compile(r"Steering|Ways and Means|Third Reading|Rules|Bills in the")
TALLY = [
    re.compile(r"(\d+)\s+YEAS?\s+to\s+(\d+)\s+NAYS?", re.I),
    re.compile(r"Yeas\s+(\d+)\s+to\s+Nays\s+(\d+)", re.I),
]
ROLL_NO = [
    re.compile(r"YEA and NAY No\.\s*(\d+)", re.I),
    re.compile(r"Roll Call\s*#\s*(\d+)", re.I),
]


def clean(text: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _ordered(history: list[dict]) -> list[dict]:
    """Drop stricken actions and sort by date. Undated actions inherit the previous date so they stay put."""
    out, prev = [], ""
    for h in history:
        if h.get("IsStricken"):
            continue
        prev = h.get("Date") or prev
        out.append({**h, "Date": prev, "Action": clean(h.get("Action"))})
    out.sort(key=lambda h: h["Date"])
    return out


def classify(history: list[dict], today: dt.date) -> dict:
    actions = _ordered(history)
    stage = "filed"
    committee = chapter = related = None
    engrossed: set[str] = set()
    hearings: list[dt.date] = []

    def bump(new: str):
        nonlocal stage
        if not STAGES[stage].get("dead") and STAGES[new]["rank"] > STAGES[stage]["rank"]:
            stage = new

    for h in actions:
        a, branch = h["Action"], h.get("Branch") or ""

        m = re.search(r"Referred to the committee on (.+?)(?: with |$)", a)
        if m and not COMMITTEE_SKIP.search(m.group(1)):
            committee = m.group(1).strip().rstrip(".")
            bump("committee")

        m = re.search(r"Hearing (?:re)?scheduled (?:for|to) (\d{2}/\d{2}/\d{4})", a)
        if m:
            hearings.append(dt.datetime.strptime(m.group(1), "%m/%d/%Y").date())

        if re.search(r"reported favorably|ought to pass|Discharged from committee", a, re.I) and "recommitted" not in a:
            bump("reported")
        if re.search(r"passed to be engrossed", a, re.I):
            engrossed.add(branch)
        if re.search(r"\bEnacted\b", a):
            bump("enacted")
        if re.search(r"laid before the Governor", a, re.I):
            bump("governor")
        if re.search(r"\bVetoed\b", a, re.I):
            stage = "vetoed"

        m = re.search(r"Signed by the Governor,?\s*(Chapter \d+ of the Acts of \d{4})", a, re.I)
        if m:
            chapter, stage = m.group(1), "law"

        m = (re.search(r"(?:New draft substituted|Amended by substitution.*?|Accompanied a new draft),? see\s+([HS]\d+)", a, re.I)
             or re.search(r"Consolidated with ([HS]\d+)", a, re.I))
        if m and stage != "law":
            related, stage = m.group(1), "replaced"
        if re.search(r"study order", a, re.I) and stage not in ("law", "replaced"):
            r = re.search(r"see\s+([HS]\d+)", a)
            related = r.group(1) if r else related
            stage = "study"

    if stage in ("filed", "committee") and hearings:
        stage = "hearing" if min(hearings) <= today else "scheduled"
    if len(engrossed) >= 2:
        bump("both")
    elif engrossed:
        bump("one")

    last = actions[-1] if actions else None
    return {
        "stage": stage,
        "stage_label": STAGES[stage]["label"],
        "dead": bool(STAGES[stage].get("dead")),
        "committee": committee,
        "chapter": chapter,
        "related_bill": related,
        "filed_date": actions[0]["Date"][:10] if actions else None,
        "last_action": last["Action"] if last else None,
        "last_action_date": last["Date"][:10] if last else None,
        "last_action_branch": last.get("Branch") if last else None,
    }


def floor_record(history: list[dict]) -> dict[str, dict]:
    """How the bill moved on the floor of each chamber.

    For each of House and Senate: whether it was engrossed and enacted, and
    whether any of those votes was a roll call (with tally and number) or a
    voice vote, which records no individual votes.
    """
    record = {}
    for branch in ("House", "Senate"):
        acts = [h for h in _ordered(history) if h.get("Branch") == branch]
        engrossed = next((h for h in acts if re.search(r"passed to be engrossed", h["Action"], re.I)), None)
        enacted = next((h for h in acts if re.search(r"\bEnacted\b", h["Action"])), None)
        roll_calls = []
        for h in acts:
            tally = next((m for p in TALLY if (m := p.search(h["Action"]))), None)
            if not tally:
                continue
            num = next((m for p in ROLL_NO if (m := p.search(h["Action"]))), None)
            roll_calls.append({
                "date": h["Date"][:10],
                "action": h["Action"],
                "yeas": int(tally.group(1)),
                "nays": int(tally.group(2)),
                "number": int(num.group(1)) if num else None,
            })
        if roll_calls:
            vote_type = "roll call"
        elif engrossed or enacted:
            vote_type = "voice vote"
        else:
            vote_type = "no floor vote"
        record[branch] = {
            "vote_type": vote_type,
            "engrossed": engrossed["Date"][:10] if engrossed else None,
            "enacted": enacted["Date"][:10] if enacted else None,
            "roll_calls": roll_calls,
        }
    return record


def pinslip_description(pinslip: str, title: str) -> str:
    """The pinslip's 'relative to …' clause, used when there's no generated summary."""
    # "... of Nick Collins (with the approval of the mayor and city council) for legislation to direct ... Public Service.  [Local Approval Received.]"
    m = (re.search(r"city council\)\s*(?:for legislation\s+|for\s+|that\s+)?(.+?)\.\s+[A-Z][A-Za-z ,&'’]+\.\s+\[", pinslip or "")
         or re.search(r"\)\s*(?:for legislation\s+|for\s+)?(.+?)\.\s+[A-Z][A-Za-z ,&'’]+\.\s+\[", pinslip or ""))
    if not m:
        return title
    text = m.group(1).strip()
    return text[0].upper() + text[1:]
