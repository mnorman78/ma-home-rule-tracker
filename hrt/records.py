"""Records that show individual legislators' positions beyond recorded floor votes.

- Committee votes: each committee member's vote on reporting a bill (from the
  bill record in the Legislature's API; published from 2025 on).
- Cosponsors: delegation members who signed on to a petition.
- House and Senate Journals (daily PDFs): the official account of each floor
  action, including whether it happened in an informal session, where a single
  member's objection would have blocked it.
- House roll calls by member (daily roll-call PDFs), which the API doesn't serve.
- Session video: the archived video of the session where the bill was acted on.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from .api import SITE, Client

BRANCH_WORD = {"H": "House", "S": "Senate"}

# History actions that happen on the floor (and so appear in that day's Journal).
FLOOR_ACTION = re.compile(
    r"read|engross|enact|rules suspended|orders of the day|third reading|concurred|amended|substitut|"
    r"laid before|passed|taken out|doubt|objection|recommitted|reconsider|non-concur|conference",
    re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


class Fetcher:
    """Cached downloads of HTML pages and PDF text from malegislature.gov."""

    def __init__(self, cache_dir: Path, live_court: int, offline: bool = False):
        self.cache_dir = cache_dir / "records"
        self.live_court = live_court
        self.offline = offline
        self.requests = 0
        self._lock = threading.Lock()

    def _download(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "ma-home-rule-tracker/0.4"})
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

    def _cached(self, key: str, court: int, fetch, max_age: float):
        file = self.cache_dir / str(court) / f"{key}.json"
        fresh = court < self.live_court or (file.exists() and time.time() - file.stat().st_mtime < max_age)
        if file.exists() and (fresh or self.offline):
            return json.loads(file.read_text())["v"]
        if self.offline:
            raise RuntimeError(f"offline and not cached: {key}")
        value = fetch()
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps({"v": value}))
        return value

    def html(self, court: int, path: str, max_age: float = 12 * 3600) -> str:
        key = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")
        return self._cached(key, court, lambda: self._download(SITE + path).decode("utf-8", "replace"), max_age)

    def pdf_pages(self, court: int, path: str, max_age: float = 7 * 86400) -> list[str]:
        """Text of each page. Recent journals are "uncorrected proofs", so the current session re-reads weekly."""
        from pypdf import PdfReader

        key = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")

        def fetch():
            reader = PdfReader(io.BytesIO(self._download(SITE + path)))
            return [(p.extract_text() or "") for p in reader.pages]

        return self._cached(key, court, fetch, max_age)


# ------------------------------------------------------------- journals

def _session_months(court: int) -> list[tuple[int, int]]:
    start = 2025 + (court - 194) * 2
    return [(start + i // 12, i % 12 + 1) for i in range(25)]  # through January after the session


class Journals:
    """Index of daily Journal and roll-call PDFs, from the monthly listing pages."""

    def __init__(self, fetcher: Fetcher):
        self.f = fetcher
        self._index: dict[tuple[int, str], dict] = {}
        self._lock = threading.Lock()

    def index(self, court: int, branch: str) -> dict:
        with self._lock:
            if (court, branch) in self._index:
                return self._index[(court, branch)]
            journals: dict[str, list[str]] = {}
            rollcalls: dict[str, list[str]] = {}
            today = dt.date.today()
            for year, month in _session_months(court):
                if dt.date(year, month, 1) > today:
                    break
                try:
                    page = self.f.html(court, f"/Journal/{branch}/{court}/{month:02d}-01-{year}")
                except RuntimeError:
                    continue
                for path in set(re.findall(rf'/Journal/{branch}/{court}/[^"]+?\.pdf', page)):
                    m = re.search(r"(\d{2})(\d{2})(\d{4})", path.rsplit("/", 1)[-1])
                    if not m:
                        continue
                    date = f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
                    (rollcalls if "/RollCalls/" in path else journals).setdefault(date, []).append(path)
            self._index[(court, branch)] = {"journals": journals, "rollcalls": rollcalls}
            return self._index[(court, branch)]


def _bill_ref(bill: str) -> re.Pattern:
    """How the Journal cites a bill: "(House, No. 4246)" or "(Senate, No. 27)"."""
    return re.compile(rf"\(\s*{BRANCH_WORD[bill[0]]},\s*No\.\s*{bill[1:]}\s*\)")


def _clean_journal(text: str) -> str:
    text = re.sub(r"UNCORRECTED PROOF\.?", " ", text)
    text = re.sub(r"JOURNAL OF THE (HOUSE|SENATE)\.?", " ", text)
    text = re.sub(r"[—_]{4,}", " ", text)
    return re.sub(r"\s+", " ", text).strip()


FLAGS = [
    ("doubted", re.compile(r"\bdoubted\b", re.I), "Vote doubted (counted or roll call requested)"),
    # "There being no objection" / "without objection" is routine procedure, not an objection.
    ("objection", re.compile(r"(?<!\bno )(?<!\bwithout )\bobject(ed|ion)\b", re.I), "Objection noted"),
    ("roll_call", re.compile(r"yeas? and nays?", re.I), "Roll call"),
    ("statement", re.compile(r"\bstatement of\b|would have voted", re.I), "Member statement"),
]


def journal_entries(journals: Journals, court: int, bill: str, branch: str, dates: list[str]) -> list[dict]:
    """The Journal's account of each day the bill was acted on in `branch`."""
    out = []
    idx = journals.index(court, branch)["journals"]
    ref = _bill_ref(bill)
    for date in sorted(set(dates)):
        for path in idx.get(date, []):
            try:
                pages = journals.f.pdf_pages(court, path)
            except RuntimeError:
                continue
            text = _clean_journal(" ".join(pages))
            hits = list(ref.finditer(text))
            if not hits:
                continue
            excerpts = []
            for m in hits[:3]:
                # The sentence that cites the bill, plus the next one (which usually says what happened).
                # A wider window picks up neighboring bills' actions and mislabels this one.
                lo = text.rfind(". ", 0, m.start())
                lo = 0 if lo < 0 else lo + 2
                hi = m.end()
                for _ in range(2):
                    nxt = text.find(". ", hi)
                    hi = len(text) if nxt < 0 else nxt + 1
                excerpts.append(text[lo:hi].strip())
            excerpt = " … ".join(dict.fromkeys(excerpts))[:1500]
            out.append({
                "branch": branch,
                "date": date,
                "url": SITE + path,
                "informal": bool(re.search(r"in an Informal Session", text[:2500], re.I)),
                "excerpt": excerpt,
                "flags": [label for key, rx, label in FLAGS if rx.search(excerpt)],
            })
    return out


# ------------------------------------------------------- House roll calls

ROLL_HEADER = re.compile(r"^\s*([HS])\.\s*(\d+)\s+(.+?)Yea and Nay\s+(\d{2}/\d{2}/\d{4})", re.M)
ROLL_NUMBER = re.compile(r"No\.\s*(\d+)\s+(\d+)\s+YEAS\s+(\d+)\s+NAYS\s+(\d+)\s+N/V")
ROLL_ENTRY = re.compile(r"(\S.*?)\s?\*?([YNXP])(?= |$)")
VOTE_WORD = {"Y": "Yea", "N": "Nay", "X": "Not voting", "P": "Present"}


def _parse_roll_page_stacked(page: str) -> dict | None:
    """Older roll-call PDFs (before about 2020): header fields and each name/vote pair on separate lines."""
    bill = re.search(r"^\s*([HS])\.\s*(\d+)\s+(.+?)\s*$", page, re.M)
    num = re.search(r"No\.\s*(\d+)", page)
    yeas, nays, nv = (re.search(rf"(\d+)\s+{w}", page) for w in ("YEAS", "NAYS", r"N/V"))
    if not (bill and num and yeas and nays):
        return None
    votes, name = {}, None
    for line in page[bill.end():].splitlines():
        line = line.strip()
        if not line or line.startswith("*="):
            continue
        token = line.lstrip("*").strip()
        if token in VOTE_WORD and name:
            votes[name] = VOTE_WORD[token]
            name = None
        else:
            name = line.strip(" -").replace("--", "").strip()
    return {
        "bill": f"{bill.group(1)}{bill.group(2)}", "question": bill.group(3).strip(),
        "number": int(num.group(1)), "yeas": int(yeas.group(1)), "nays": int(nays.group(1)),
        "not_voting": int(nv.group(1)) if nv else 0, "votes": votes,
    }


def _parse_roll_page(page: str) -> dict | None:
    head = ROLL_HEADER.search(page)
    num = ROLL_NUMBER.search(page)
    if not head or not num:
        return _parse_roll_page_stacked(page)
    votes = {}
    body = page[num.end():]
    body = body.split("*=AFTER VOTE")[0]
    for line in body.splitlines():
        for m in ROLL_ENTRY.finditer(line.strip()):
            name = m.group(1).strip(" -").replace("--", "").strip()
            if name:
                votes[name] = VOTE_WORD[m.group(2)]
    return {
        "bill": f"{head.group(1)}{head.group(2)}",
        "question": head.group(3).strip(),
        "number": int(num.group(1)),
        "yeas": int(num.group(2)),
        "nays": int(num.group(3)),
        "not_voting": int(num.group(4)),
        "votes": votes,
    }


def _match_member(votes: dict[str, str], member_name: str) -> str | None:
    """Find a member's entry on a roll call ("Moran, M." for Michael J. Moran; "Fluker-Reid" for Brandy Fluker-Reid)."""
    words = member_name.replace(",", " ").split()
    first = _norm(words[0])[:1] if words else ""
    full = _norm(member_name)
    candidates = []
    for listed in votes:
        base, _, initial = listed.partition(",")
        if not initial:  # older PDFs write "Moran F." with no comma
            m = re.match(r"^(.*\S)\s+([A-Z])\.?$", listed)
            if m:
                base, initial = m.group(1), m.group(2)
        b = _norm(base)
        if b and full.endswith(b):
            if initial.strip() and _norm(initial)[:1] != first:
                continue
            candidates.append(listed)
    return max(candidates, key=len) if candidates else None


def house_roll_calls(journals: Journals, court: int, bill: str, dates: list[str], delegation: dict[str, dict]) -> list[dict]:
    idx = journals.index(court, "House")["rollcalls"]
    reps = [m for m in delegation.values() if m["branch"] == "House"]
    out = []
    for date in sorted(set(dates)):
        for path in idx.get(date, []):
            try:
                pages = journals.f.pdf_pages(court, path)
            except RuntimeError:
                continue
            for page in pages:
                rc = _parse_roll_page(page)
                if not rc or rc["bill"] != bill:
                    continue
                deleg_votes = []
                for m in reps:
                    listed = _match_member(rc["votes"], m["name"])
                    deleg_votes.append({"code": m["code"], "name": m["name"], "district": m["district"],
                                        "vote": rc["votes"][listed] if listed else "Not on roll call"})
                out.append({"branch": "House", "date": date, "number": rc["number"], "question": rc["question"],
                            "yeas": rc["yeas"], "nays": rc["nays"], "not_voting": rc["not_voting"],
                            "pdf": SITE + path, "delegation": deleg_votes})
    return out


# ------------------------------------------------------------ session video

def session_videos(client: Client, court: int) -> dict[tuple[str, str], str]:
    """(branch, date) → session page with archived video."""
    out = {}
    try:
        sessions = client.get(court, f"/GeneralCourts/{court}/Sessions")
    except RuntimeError:
        return out
    for s in sessions:
        branch = "House" if "House" in (s.get("LocationName") or s.get("Name") or "") else \
                 "Senate" if "Senate" in (s.get("LocationName") or s.get("Name") or "") else None
        if branch and s.get("EventDate"):
            out.setdefault((branch, s["EventDate"][:10]), f"{SITE}/Events/Sessions/Detail/{s['EventId']}")
    return out


# --------------------------------------------- committee votes, cosponsors

def committee_votes(docs: list[dict], members: dict[str, dict], delegation: dict[str, dict]) -> list[dict]:
    out, seen = [], set()
    for doc in docs:
        for rec in doc.get("CommitteeRecommendations") or []:
            for v in rec.get("Votes") or []:
                key = (rec["Committee"]["CommitteeCode"], v.get("Date"), v.get("Question"))
                if key in seen:
                    continue
                seen.add(key)
                tally: dict[str, list[str]] = {}
                for group in v.get("Vote") or []:
                    for category, ms in group.items():
                        tally.setdefault(category, []).extend(m["MemberCode"] for m in ms)
                label = {"Favorable": "Favorable", "Adverse": "Adverse", "ReserveRight": "Reserved right",
                         "NoVoteRecorded": "No vote recorded"}
                out.append({
                    "committee_code": rec["Committee"]["CommitteeCode"],
                    "question": v.get("Question"),
                    "date": (v.get("Date") or "")[:10],
                    "bill": (v.get("Bill") or {}).get("BillNumber"),
                    "counts": {label.get(k, k): len(ms) for k, ms in tally.items()},
                    "delegation": [
                        {"code": code, "name": members.get(code, {}).get("name", code),
                         "district": members.get(code, {}).get("district"), "vote": label.get(cat, cat)}
                        for cat, codes in tally.items() for code in codes if code in delegation
                    ],
                })
    return out


def delegation_cosponsors(doc: dict, members: dict[str, dict], delegation: dict[str, dict]) -> list[dict]:
    primary = (doc.get("PrimarySponsor") or {}).get("Id")
    out = []
    for c in doc.get("Cosponsors") or []:
        code = c.get("Id")
        if code and code != primary and code in delegation:
            m = members[code]
            out.append({"code": code, "name": m["name"], "branch": m["branch"], "district": m["district"]})
    return out
