"""Build the dataset: every home rule petition for a city across a range of sessions."""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import re
import sys

from . import categories, records
from .api import Client, bill_url, court_years, ordinal
from .delegation import all_members, delegation
from .history import STAGES, classify, clean, floor_record, pinslip_description
from .summaries import Summarizer

HOME_RULE_RE = re.compile(
    r"approval\s+of\s+the\s+mayor|Local\s+Approval\s+Received|by\s+vote\s+of\s+the\s+(city|town)",
    re.I,
)


def _member_ref(m: dict | None, fallback_name: str | None = None) -> dict | None:
    if not m:
        return {"code": None, "name": fallback_name, "branch": None, "district": None, "party": None} if fallback_name else None
    return {k: m[k] for k in ("code", "name", "branch", "district", "party")}


def _follow(client: Client, court: int, start: str, today: dt.date) -> tuple[str, dict, list, dict] | None:
    """Follow a chain of redrafts to the bill that carries the petition now."""
    seen, nxt = {start}, None
    hist = client.history(court, start)
    nxt = classify(hist, today)["related_bill"]
    while nxt and nxt not in seen and len(seen) < 6:
        seen.add(nxt)
        hist = client.history(court, nxt)
        info = classify(hist, today)
        if info["stage"] != "replaced":
            return nxt, client.document(court, nxt), hist, info
        nxt = info["related_bill"]
    return None


def _senate_votes(client: Client, court: int, doc: dict, deleg: dict[str, dict]) -> list[dict]:
    """Member-level votes for each Senate roll call on the bill, limited to the Boston delegation."""
    out = []
    for rc in doc.get("RollCalls") or []:
        if rc.get("Branch") != "Senate":
            continue
        detail = client.roll_call(court, "Senate", rc["RollCallNumber"])
        how = {}
        for vote, key in (("Yea", "Yeas"), ("Nay", "Nays"), ("Absent", "Absent")):
            for m in detail.get(key) or []:
                how[m["MemberCode"]] = vote
        senators = [m for m in deleg.values() if m["branch"] == "Senate"]
        out.append({
            "branch": "Senate",
            "number": rc["RollCallNumber"],
            "question": detail.get("QuestionMotion"),
            "yeas": len(detail.get("Yeas") or []),
            "nays": len(detail.get("Nays") or []),
            "absent": len(detail.get("Absent") or []),
            "pdf": detail.get("DownloadUrl"),
            # Members not on the roll call at all had left or not yet joined the Senate.
            "delegation": [
                {"code": m["code"], "name": m["name"], "district": m["district"], "vote": how.get(m["code"], "Not serving")}
                for m in senators
            ],
        })
    return out


def _status(stage: str, via_successor: bool, closed: bool) -> str:
    if stage == "law":
        return "Became law"
    if STAGES[stage].get("dead") and not via_successor:
        return "Died"
    return "Died at end of session" if closed else "Pending"


def build_court(client: Client, court: int, city: str, rules: list[dict], summarizer: Summarizer,
                today: dt.date, journals: "records.Journals | None" = None, workers: int = 6) -> tuple[dict, list[dict]]:
    closed = court < client.live_court
    members = all_members(client, court, workers)
    deleg = delegation(rules, court, members)

    listing = client.city_documents(court, city)
    numbered = [d["BillNumber"] for d in listing if d.get("BillNumber")]
    with cf.ThreadPoolExecutor(workers) as ex:
        docs = dict(zip(numbered, ex.map(lambda b: client.document(court, b), numbered)))
    petitions_raw = {b: d for b, d in docs.items() if HOME_RULE_RE.search(clean(d.get("Pinslip")))}

    def process(item):
        bill, doc = item
        hist = client.history(court, bill)
        own = classify(hist, today)
        successor = None
        eff_doc, eff_hist, eff = doc, hist, own
        if own["stage"] == "replaced":
            found = _follow(client, court, bill, today)
            if found:
                s_bill, s_doc, s_hist, s_info = found
                successor = {"bill": s_bill, "url": bill_url(court, s_bill), "stage_label": s_info["stage_label"], "chapter": s_info["chapter"]}
                eff_doc, eff_hist, eff = s_doc, s_hist, s_info
        return bill, doc, own, successor, eff_doc, eff_hist, eff, hist

    with cf.ThreadPoolExecutor(workers) as ex:
        processed = list(ex.map(process, petitions_raw.items()))

    # Records of individual positions beyond floor roll calls: committee votes, cosponsors, Journal
    # entries for each floor action, House roll calls by member, and session video.
    videos = records.session_videos(client, court) if journals else {}

    def gather(item):
        bill, doc, own, successor, eff_doc, eff_hist, eff, hist = item
        out = {
            "committee_votes": records.committee_votes([doc] + ([eff_doc] if successor else []), members, deleg),
            "cosponsors": records.delegation_cosponsors(doc, members, deleg),
            "journal": [], "house_roll_calls": [], "videos": [],
        }
        if not journals:
            return out
        targets = [(bill, hist)] + ([(successor["bill"], eff_hist)] if successor else [])
        for number, h in targets:
            for branch in ("House", "Senate"):
                dates = sorted({a["Date"][:10] for a in h if a.get("Branch") == branch and a.get("Date")
                                and records.FLOOR_ACTION.search(clean(a.get("Action")))})
                out["journal"] += records.journal_entries(journals, court, number, branch, dates)
                out["videos"] += [{"branch": branch, "date": d, "url": videos[(branch, d)]}
                                  for d in dates if (branch, d) in videos]
            roll_dates = [rc["date"] for rc in floor_record(h)["House"]["roll_calls"]]
            if roll_dates:
                out["house_roll_calls"] += records.house_roll_calls(journals, court, number, roll_dates, deleg)
        out["videos"] = list({(v["branch"], v["date"]): v for v in out["videos"]}.values())
        # A petition and its redraft can be cited in the same day's Journal; keep one entry per day.
        merged: dict[tuple, dict] = {}
        for e in out["journal"]:
            k = (e["branch"], e["date"], e["url"])
            if k in merged:
                m = merged[k]
                if e["excerpt"] not in m["excerpt"]:
                    m["excerpt"] = (m["excerpt"] + " … " + e["excerpt"])[:1500]
                m["flags"] = sorted(set(m["flags"]) | set(e["flags"]))
            else:
                merged[k] = dict(e)
        out["journal"] = sorted(merged.values(), key=lambda e: (e["date"], e["branch"]))
        return out

    with cf.ThreadPoolExecutor(workers) as ex:
        extra = dict(zip((item[0] for item in processed), ex.map(gather, processed)))
    names = {code: client.committee_name(court, code)
             for code in {cv["committee_code"] for e in extra.values() for cv in e["committee_votes"]}}
    for e in extra.values():
        for cv in e["committee_votes"]:
            cv["committee"] = names.get(cv["committee_code"], cv["committee_code"])

    # Summaries come from the petition as Boston filed it (falling back to the redraft's text).
    # Routine categories (age waivers, individual pensions) get a template summary instead.
    cat_overrides = categories.load_overrides()
    summarizer.fill([
        {"court": court, "bill": bill, "title": doc.get("Title"), "pinslip": clean(doc.get("Pinslip")),
         "text": doc.get("DocumentText") or eff_doc.get("DocumentText") or ""}
        for bill, doc, _, _, eff_doc, _, _, _ in processed
        if categories.needs_summary(court, bill, doc.get("Title"), cat_overrides)
    ])

    petitions = []
    for bill, doc, own, successor, eff_doc, eff_hist, eff, _ in processed:
        sponsor = doc.get("PrimarySponsor") or {}
        transmitter = _member_ref(members.get(sponsor.get("Id")), sponsor.get("Name"))
        if transmitter:
            transmitter["in_delegation"] = sponsor.get("Id") in deleg
        s = summarizer.get(court, bill)
        stage = eff["stage"]
        petitions.append({
            "court": court,
            "years": court_years(court),
            "bill": bill,
            "docket": doc.get("DocketNumber"),
            "url": bill_url(court, bill),
            "title": doc.get("Title"),
            "short_title": s["short_title"] if s else None,
            "summary": s["summary"] if s else pinslip_description(clean(doc.get("Pinslip")), doc.get("Title")),
            "summary_source": "claude" if s else "pinslip",
            "transmitter": transmitter,
            "filed_date": own["filed_date"],
            "committee": own["committee"],
            "stage": stage,
            "stage_label": eff["stage_label"],
            "status": _status(stage, successor is not None, closed),
            "chapter": eff["chapter"],
            "replaced_by": successor,
            "own_stage_label": own["stage_label"] if successor else None,
            "last_action": eff["last_action"],
            "last_action_date": eff["last_action_date"],
            "last_action_branch": eff["last_action_branch"],
            "floor": floor_record(eff_hist),
            "roll_calls": _senate_votes(client, court, eff_doc, deleg) + extra[bill]["house_roll_calls"],
            "committee_votes": extra[bill]["committee_votes"],
            "cosponsors": extra[bill]["cosponsors"],
            "journal": extra[bill]["journal"],
            "videos": extra[bill]["videos"],
        })

    for d in listing:
        if d.get("BillNumber"):
            continue
        sponsor = d.get("PrimarySponsor") or {}
        transmitter = _member_ref(members.get(sponsor.get("Id")), sponsor.get("Name"))
        if transmitter:
            transmitter["in_delegation"] = sponsor.get("Id") in deleg
        petitions.append({
            "court": court, "years": court_years(court), "bill": None, "docket": d.get("DocketNumber"),
            "url": bill_url(court, d["DocketNumber"]) if d.get("DocketNumber") else None,
            "title": d.get("Title"), "short_title": None, "summary": d.get("Title"), "summary_source": "title",
            "transmitter": transmitter, "filed_date": None, "committee": None,
            "stage": "filed", "stage_label": "Docketed, no bill number yet",
            "status": "Died at end of session" if closed else "Pending",
            "chapter": None, "replaced_by": None, "own_stage_label": None,
            "last_action": None, "last_action_date": None, "last_action_branch": None,
            "floor": {}, "roll_calls": [], "committee_votes": [], "cosponsors": [], "journal": [], "videos": [],
        })

    categories.apply(petitions, cat_overrides)
    petitions.sort(key=lambda p: p["last_action_date"] or "", reverse=True)
    petitions.sort(key=lambda p: -STAGES[p["stage"]]["rank"])
    info = {
        "court": court,
        "years": court_years(court),
        "closed": closed,
        "delegation": sorted(deleg.values(), key=lambda m: (m["branch"] != "Senate", m["district"] or "", m["name"])),
    }
    print(f"  {ordinal(court)} ({court_years(court)}): {len(petitions)} petitions, {len(deleg)} delegation members",
          file=sys.stderr)
    return info, petitions


COUNCIL_FROM = "2021-01-01"  # Legistar's minutes and records start here


def attach_council(dataset: dict, council: list[dict], overrides: dict) -> None:
    """Link each state petition to the City Council docket that approved it, and keep the full council list."""
    from .matching import match, petition_key

    eligible = [p for p in dataset["petitions"] if p["court"] >= 192]  # the 2021-22 session onward
    links = match(eligible, council, overrides)
    linked_from: dict[str, list[str]] = {}
    for p in dataset["petitions"]:
        key = petition_key(p)
        c = links.get(key)
        p["council"] = None if not c else {
            "docket": c["docket"],
            "url": c["url"],
            "title": c["act_title"],
            "filed": c["filed"],
            "passed": c["passed"],
            "action": c.get("action"),
            "minutes": c["minutes"],
            "meeting_url": c.get("meeting_url"),
            "has_video": c.get("has_video", False),
            "vote": c["vote"],
            "match": c["match"],
        }
        if c:
            linked_from.setdefault(c["docket"], []).append(key)

    dataset["council_from"] = COUNCIL_FROM
    dataset["council_petitions"] = sorted(({
        "docket": c["docket"],
        "url": c["url"],
        "title": c.get("act_title") or c["title"],
        "category": categories.categorize(c.get("act_title") or c["title"]),
        "type": c["type"],
        "filed": c["filed"],
        "council_status": c["council_status"],
        "passed": c["passed"],
        "action": c.get("action"),
        "minutes": c["minutes"],
        "meeting_url": c.get("meeting_url"),
        "has_video": c.get("has_video", False),
        "vote": c["vote"],
        "state_bills": linked_from.get(c["docket"], []),
    } for c in council), key=lambda c: c["filed"] or "", reverse=True)


def build(client: Client, city: str, courts: list[int], rules: list[dict], summarizer: Summarizer,
          journals: "records.Journals | None" = None) -> dict:
    today = dt.date.today()
    sessions, petitions = [], []
    for court in courts:
        info, ps = build_court(client, court, city, rules, summarizer, today, journals)
        sessions.append(info)
        petitions.extend(ps)
    return {
        "city": city,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "live_court": client.live_court,
        "sessions": sessions,
        "petitions": petitions,
    }
