"""Link City Council dockets to the state bills they became.

Neither record points at the other, so a council docket is matched to a
state petition by the act's title, constrained by dates: the council votes
before (or shortly after) the bill is filed at the State House.

Words are weighted by rarity across all titles, so what distinguishes a
petition (an officer's name, a street, "ranked choice") counts for far more
than the boilerplate shared by dozens of age waivers.

Within a session each council docket matches at most one state bill. The
same docket may match bills in different sessions, because a petition that
dies at the State House is often refiled under the original council vote.

Matches can be pinned or blocked by hand in data/council_matches.json:

    {"194/H2995": "2024-0582",   # pin this state bill to this council docket
     "193/H4805": null}          # this state bill has no council docket
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections import Counter
from pathlib import Path

STOP = set("""a an the of to for in on and or by at as with from into its it be is relative act acts
city boston general court special law petition home rule re regarding authorizing authorize directing
certain approval message order your docket referred entitled""".split())

# Strip everything up to the last boilerplate phrase ("…, Docket #1277, for a Special Law re: An Act …").
LEADING = re.compile(
    r"^.*(?:entitled|petition for a special law|for a special law|special law|home rule petition|special act)"
    r"\s*(?:re|regarding|for)?\s*[:.,-]?\s*", re.I)
TRAILING = re.compile(
    r"(?:[\"”]?,\s*(?:the|from the) committee\b|[\"”]?\.\s*(?:On motion|Councilor|President|The rules|The report|Referred)\b"
    r"|[\"”]?,?\s*submits? a report|;\s*the rules).*$", re.I | re.S)


def act_title(council_title: str) -> str:
    """The act's own title from a council docket title."""
    t = re.sub(r"\s+", " ", council_title)
    quoted = re.findall(r"[\"“]([^\"“”]{12,}?)[\"”]", t)
    if quoted:
        return max(quoted, key=len).strip()
    t = TRAILING.sub("", t)
    return (LEADING.sub("", t) or t).strip(" .")


def _stem(w: str) -> str:
    """Crude plural folding so "Inspectors" matches "Inspector"."""
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _tokens(s: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", s.lower().replace("’", "'"))
    return {_stem(w.strip("'")) for w in words if len(w.strip("'")) > 1 and w.strip("'") not in STOP}


class Scorer:
    def __init__(self, titles: list[str]):
        self.df = Counter(t for title in titles for t in _tokens(title))
        self.n = len(titles)

    def idf(self, token: str) -> float:
        return math.log((self.n + 1) / (self.df.get(token, 0) + 1)) + 1

    def score(self, a: str, b: str) -> float:
        ta, tb = _tokens(a), _tokens(b)
        union = ta | tb
        if not union:
            return 0.0
        return sum(self.idf(t) for t in ta & tb) / sum(self.idf(t) for t in union)


def _date(s: str | None) -> dt.date | None:
    return dt.date.fromisoformat(s) if s else None


def match(state_petitions: list[dict], council: list[dict], overrides: dict, threshold: float = 0.5) -> dict[str, dict]:
    """Map 'court/bill' → council record (plus match info) for each state petition with a match."""
    passed = [c for c in council if c.get("passed")]
    for c in council:
        c["act_title"] = act_title(c["title"])
    by_docket = {c["docket"]: c for c in council}
    scorer = Scorer([p["title"] or "" for p in state_petitions] + [c["act_title"] for c in passed])

    out: dict[str, dict] = {}
    candidates = []
    for p in state_petitions:
        if not (p.get("bill") or p.get("docket")):
            continue
        key = petition_key(p)
        if key in overrides:
            pinned = overrides[key]
            if pinned and pinned in by_docket:
                out[key] = {**by_docket[pinned], "match": {"score": None, "method": "manual"}}
            continue
        filed = _date(p.get("filed_date"))
        if not filed:  # without a filing date there's no date check, so don't guess
            continue
        chamber = (p.get("bill") or p.get("docket") or "?")[0]
        for c in passed:
            cdate = _date(c["passed"])
            # Council approval normally comes first. Some bills are filed early and wait for it, and
            # a petition that dies is often refiled a session or two later under the same vote.
            if filed and not (filed - dt.timedelta(days=1100) <= cdate <= filed + dt.timedelta(days=240)):
                continue
            s = scorer.score(p["title"] or "", c["act_title"])
            if filed and cdate > filed:
                s -= 0.1
            if s >= threshold:
                gap = abs((filed - cdate).days) if filed else 999
                candidates.append((s, -gap, key, (p["court"], chamber), c["docket"]))

    # Best pairs first. Each state bill gets one docket; within a session a docket goes to at most one
    # House bill and one Senate bill (companion filings of the same petition).
    taken = {((int(k.split("/")[0]), k.split("/")[1][0]), v["docket"]) for k, v in out.items()}
    for s, _, key, slot, docket in sorted(candidates, reverse=True):
        if key in out or (slot, docket) in taken:
            continue
        out[key] = {**by_docket[docket], "match": {"score": round(s, 3), "method": "title"}}
        taken.add((slot, docket))
    return out


def petition_key(p: dict) -> str:
    return f"{p['court']}/{p.get('bill') or p.get('docket')}"


def load_overrides(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}
