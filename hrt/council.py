"""Boston City Council side: find home rule petitions in Legistar and read council votes from the minutes.

Legistar (webapi.legistar.com/v1/boston) has each council docket and its
action history, but records no roll calls. The City Clerk's official minutes
(PDFs linked from each meeting) do, in a consistent form:

    The report was accepted; the petition was passed; yeas 11, nays 2. (Baker and Murphy).
    ... the petition was passed; yeas 12, absent 1 (Fernandes Anderson)

Only the smaller side is named. The unnamed side is filled in from
data/council_roster.json when the roster, the meeting's attendance line
("All Councilors Present" / "Absent Councilor Mejia") and the tally agree
exactly; otherwise only the named councilors are recorded.

Legistar's minutes start in 2021.
"""

from __future__ import annotations

import concurrent.futures as cf
import io
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LEGISTAR = "https://webapi.legistar.com/v1/boston"
COUNCIL_BODY = 138
WEB = "https://boston.legistar.com/LegislationDetail.aspx"

PETITION_KIND = re.compile(r"special (law|act)|general court|home rule", re.I)
NOT_A_PETITION = re.compile(r"Resolution|Hearing|17F|Report of Public Officer|Notice|Personnel|Minutes|Agenda", re.I)
PASS_ACTION = re.compile(r"\b(passed|adopted)\b", re.I)


class Legistar:
    def __init__(self, cache_dir: Path, max_age: float = 12 * 3600, offline: bool = False):
        self.cache_dir = cache_dir / "legistar"
        self.max_age = max_age
        self.offline = offline
        self.requests = 0
        self._lock = threading.Lock()

    def _download(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "ma-home-rule-tracker/0.3"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    with self._lock:
                        self.requests += 1
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code in (400, 404) or attempt == 2:
                    raise RuntimeError(f"GET {url} -> HTTP {e.code}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == 2:
                    raise RuntimeError(f"GET {url} failed: {e}") from e
            time.sleep(2 * (attempt + 1))

    def _cached(self, key: str, fetch, permanent: bool):
        file = self.cache_dir / f"{key}.json"
        if file.exists() and (permanent or self.offline or time.time() - file.stat().st_mtime < self.max_age):
            return json.loads(file.read_text())
        if self.offline:
            raise RuntimeError(f"offline and not cached: {key}")
        data = fetch()
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data))
        return data

    def get(self, path: str, query: dict | None = None, permanent: bool = False):
        url = LEGISTAR + path + ("?" + urllib.parse.urlencode(query) if query else "")
        key = re.sub(r"[^A-Za-z0-9]+", "_", path + "_" + json.dumps(query or {}, sort_keys=True)).strip("_")[:180]
        return self._cached(key, lambda: json.loads(self._download(url)), permanent)

    def minutes_text(self, url: str) -> str:
        """Text of a minutes PDF. Final minutes don't change, so they're cached permanently."""
        from pypdf import PdfReader

        url = url.replace("http://", "https://")
        key = "minutes/" + re.sub(r"[^A-Za-z0-9]+", "_", url.rsplit("/", 1)[-1])

        def fetch():
            pdf = PdfReader(io.BytesIO(self._download(url)))
            return {"text": "\n".join((p.extract_text() or "") for p in pdf.pages)}

        return self._cached(key, fetch, permanent=True)["text"]


# ------------------------------------------------------------------ roster

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


class Roster:
    def __init__(self, path: Path):
        self.members = json.loads(path.read_text())["members"]
        self._by_surname = {_norm(s): m["name"] for m in self.members for s in m["surnames"]}

    def serving(self, date: str) -> list[str]:
        return [m["name"] for m in self.members if m["start"] <= date and (m["end"] is None or date < m["end"])]

    def resolve(self, surname: str) -> str | None:
        """Match a name as written in the minutes ("Baker", "Ricardo Arroyo", "Pepen") to a roster member."""
        words = surname.split()
        for i in range(len(words)):  # try the whole string, then drop leading first names
            hit = self._by_surname.get(_norm(" ".join(words[i:])))
            if hit:
                return hit
        full = {_norm(m["name"]): m["name"] for m in self.members}
        return full.get(_norm(surname))

    def read_names(self, text: str) -> list[str]:
        """Read councilor names from the start of `text` ("Baker and Flaherty Rabbi Chaim…" → Baker, Flaherty),
        stopping at the first word that isn't a known name. Used where the minutes don't punctuate the list."""
        return self.read_names_rest(text)[0]

    def read_names_rest(self, text: str) -> tuple[list[str], str]:
        """Like read_names, but also returns the unread remainder of `text`."""
        variants = sorted({s for m in self.members for s in m["surnames"]} | {m["name"] for m in self.members},
                          key=len, reverse=True)
        out, rest = [], text
        while True:
            stripped = re.sub(r"^(?:\s|,|and\b|Councilors?\b)+", "", rest)
            hit = next((v for v in variants if _norm(stripped[: len(v)]) == _norm(v)
                        and (len(stripped) == len(v) or not stripped[len(v)].isalpha())), None)
            if not hit:
                return out, rest
            out.append(self.resolve(hit))
            rest = stripped[len(hit):]

    def resolve_all(self, names: list[str]) -> tuple[list[str], list[str]]:
        found, unknown = [], []
        for n in names:
            full = self.resolve(n)
            (found if full else unknown).append(full or n)
        return found, unknown


def _split_names(s: str | None) -> list[str]:
    if not s:
        return []
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\b(?:Councilors?|and)\b", ",", s)
    return [n.strip(" .") for n in s.split(",") if n.strip(" .")]


def attendance(minutes: str, roster: Roster) -> tuple[str, list[str]]:
    """Who attended, from the opening lines of the minutes.

    Returns ("all", []), ("absent", [members absent]), ("present", [members present,
    including the presiding officer]), or ("unknown", []). The phrasing varies by year:
    "All Councilors Present", "Absent Councilors X and Y", "Absent, Councilor X",
    "Councilor X Absent", and since late 2025 "Present Councilors A, B, … and C"
    (which leaves out the president in the chair).
    """
    head = re.sub(r"\s+", " ", minutes[:1500])
    head = head[: head.find("delivered the invocation")] if "delivered the invocation" in head else head
    if re.search(r"All Councilors present", head, re.I):
        return "all", []
    m = re.search(r"Present,? Councilors? (.*)", head)
    if m:
        chair = re.search(r"President (.+?) in the [Cc]hair", head)
        names = roster.read_names(m.group(1)) + (roster.read_names(chair.group(1)) if chair else [])
        return ("present", names) if names else ("unknown", [])
    m = re.search(r"Absent,? Councilors? (.*)", head)
    if m:
        names = roster.read_names(m.group(1))
        return ("absent", names) if names else ("unknown", [])
    m = re.search(r"\bin the [Cc]hair\.?\s*Councilors? (.+?),? [Aa]bsent\b", head)
    if m:
        names = roster.read_names(m.group(1))
        return ("absent", names) if names else ("unknown", [])
    return "unknown", []


# ------------------------------------------------------------- petitions

def find_petitions(lg: Legistar, since: str) -> list[dict]:
    """Council dockets that are home rule petitions, filed on or after `since` (YYYY-MM-DD)."""
    flt = (f"MatterIntroDate ge datetime'{since}' and "
           "(substringof('petition',MatterTitle) or substringof('Petition',MatterTitle))")
    out, skip = [], 0
    while True:
        page = lg.get("/matters", {"$filter": flt, "$top": "1000", "$skip": str(skip)})
        out.extend(page)
        if len(page) < 1000:
            break
        skip += 1000
    return [m for m in out
            if PETITION_KIND.search(m["MatterTitle"] or "")
            and not NOT_A_PETITION.search(m.get("MatterTypeName") or "")]


def _docket_paragraph(text: str, docket: str) -> str | None:
    """The minutes entry for a docket: from its number to the next docket number at a line start."""
    m = re.search(rf"(?m)^\s*{docket}\b", text)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"(?m)^\s*\d{4}\s+(?=[A-Z])", rest)
    return text[m.start(): m.end() + (nxt.start() if nxt else len(rest))]


# A passage sentence followed by a tally: "...the petition was passed; yeas 11, nays 2. (Baker and Murphy)."
# The tally runs to the end of its sentence: a period (optionally after a closing parenthesis) at a line end.
PASSAGE_RE = re.compile(r"(?:petition|order|ordinance|report|act)[^.;]*?\b(?:passed|adopted)\b[^;.]*?;\s*(yeas\s+\d+.*?(?:\)\.?|\.)\s*)(?=\n|$)", re.I | re.S)
# "nays 2. (Baker and Murphy)", "nays: 5, (Baker, …)", and the reversed "1 absent (Mejia)".
TALLY_PART = re.compile(
    r"\b(?:(yeas|nays|not present|present|absent)\s*:?\s*(\d+)|(\d+)\s+(not present|present|absent))"
    r"\s*[.,]?\s*(?:\(([^)]*)\))?", re.I)
CATEGORY = {"yeas": "Yea", "nays": "Nay", "present": "Present", "absent": "Absent", "not present": "Not present"}


def parse_vote(paragraph: str, date: str, minutes: str, roster: Roster) -> dict:
    """Read the final passage vote for one docket."""
    text = re.sub(r"[ \t]+", " ", paragraph)
    passages = list(PASSAGE_RE.finditer(text))
    att_kind, att_names = attendance(minutes, roster)
    serving = roster.serving(date)
    absent_meeting = [n for n in serving if n not in att_names] if att_kind == "present" else att_names

    if not passages:
        voted = re.search(r"\b(passed|adopted)\b", text, re.I)
        return {
            "kind": "voice vote" if voted else "unknown",
            "text": None,
            "attendance": att_kind,
            "absent_from_meeting": absent_meeting,
        }

    tally_text = re.sub(r"\s+", " ", passages[-1].group(1))  # amendments come first; final passage is last
    counts: dict[str, int] = {}
    named: dict[str, list[str]] = {}
    unknown: list[str] = []
    for part in TALLY_PART.finditer(tally_text):
        label, number = (part.group(1), part.group(2)) if part.group(1) else (part.group(4), part.group(3))
        cat = CATEGORY[label.lower()]
        counts[cat] = counts.get(cat, 0) + int(number)
        for name in _split_names(part.group(5)):
            # "yeas 12 (Absent Mejia)": the parenthesis names an absentee, not a yea.
            target = cat
            if re.match(r"(?i)(absent|not present)\b", name):
                target = "Absent"
                name = re.sub(r"(?i)^(absent|not present)\s*", "", name)
            full = roster.resolve(name)
            if full:
                named.setdefault(target, []).append(full)
            else:
                unknown.append(name)

    votes = {n: cat for cat, ns in named.items() for n in ns}
    # Meeting absentees didn't vote; the minutes don't always repeat them in the tally.
    for n in absent_meeting:
        votes.setdefault(n, "Absent")

    # Fill in the one category whose members weren't named, if everything adds up.
    inferred = False
    short = {cat: counts[cat] - len(named.get(cat, [])) for cat in counts if counts[cat] > len(named.get(cat, []))}
    # Without an attendance line, only infer when the tally itself accounts for every serving member.
    accounted = att_kind != "unknown" or sum(counts.values()) == len(serving)
    if not unknown and accounted and len(short) == 1:
        (cat, missing), = short.items()
        rest = [n for n in serving if n not in votes]
        if len(rest) == missing:
            for n in rest:
                votes[n] = cat
            inferred = True

    return {
        "kind": "roll call",
        "text": tally_text,
        "yeas": counts.get("Yea", 0),
        "nays": counts.get("Nay", 0),
        "present": counts.get("Present", 0),
        "absent": counts.get("Absent", 0) + counts.get("Not present", 0),
        "votes": votes,
        "complete": inferred or len(votes) == len(serving),
        "attendance": att_kind,
        "absent_from_meeting": absent_meeting,
        "unmatched_names": unknown,
    }


def council_record(lg: Legistar, matter: dict, roster: Roster) -> dict:
    """Passage date, how the vote went, and a link, for one council docket."""
    hist = lg.get(f"/matters/{matter['MatterId']}/histories")
    council_acts = sorted((h for h in hist if h.get("MatterHistoryActionBodyId") == COUNCIL_BODY),
                          key=lambda h: h["MatterHistoryActionDate"])
    passed = next((h for h in reversed(council_acts)
                   if PASS_ACTION.search(h.get("MatterHistoryActionName") or "")
                   and "not pass" not in (h.get("MatterHistoryActionName") or "")), None)
    rec = {
        "docket": matter["MatterFile"],
        "matter_id": matter["MatterId"],
        "title": re.sub(r"\s+", " ", matter["MatterTitle"]).strip(),
        "type": matter.get("MatterTypeName"),
        "filed": (matter.get("MatterIntroDate") or "")[:10] or None,
        "council_status": matter.get("MatterStatusName"),
        "url": f"{WEB}?ID={matter['MatterId']}&GUID={matter['MatterGuid']}",
        "passed": None,
        "action": None,
        "vote": None,
        "minutes": None,
    }
    if not passed:
        return rec
    date = passed["MatterHistoryActionDate"][:10]
    rec["passed"] = date
    rec["action"] = passed.get("MatterHistoryActionName")
    text = None
    if passed.get("MatterHistoryEventId"):
        try:
            event = lg.get(f"/events/{passed['MatterHistoryEventId']}", permanent=True)
            url = event.get("EventMinutesFile")
            rec["minutes"] = url.replace("http://", "https://") if url else None
            text = lg.minutes_text(url) if url else None
        except RuntimeError:  # meeting record or minutes file missing from Legistar
            text = None
    para = _docket_paragraph(text, matter["MatterFile"].split("-")[-1]) if text else None
    rec["vote"] = parse_vote(para, date, text, roster) if para else {"kind": "unknown", "text": None}
    return rec


def council_petitions(lg: Legistar, roster: Roster, since: str = "2021-01-01", workers: int = 6) -> list[dict]:
    matters = find_petitions(lg, since)
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda m: council_record(lg, m, roster), matters))
