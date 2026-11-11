"""Sort petitions into categories by title, and write template summaries for routine ones.

Routine categories (one person, one standard request) get a summary filled in
from the title, with no Claude call. Everything else is summarized by Claude
when an API key is available. Rules are checked in order; the first match wins.
Edit RULES (or data/category_overrides.json for single petitions) to adjust.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# (key, label, routine, pattern)
RULES: list[tuple[str, str, bool, str]] = [
    ("age_waiver", "Age waivers (police and fire hires)", True,
     r"maximum age requirement|age waiver"),
    ("individual_benefits", "Pensions and benefits for individuals", True,
     r"disability pension|death benefits for the widow|retirement benefits of the surviving|creditable service to|"
     r"pension benefits for firefighter|disability pension"),
    ("liquor", "Liquor licenses", False,
     r"licenses? for the sale of (all )?alcoholic|liquor licenses?"),
    ("elections", "Elections and city government", False,
     r"vot(e|ing)|election|ranked choice|councilor|councillor|office of mayor|terms of office|municipal years|"
     r"wards and precincts|nomination|finance commission|inspector general|boards and commissions|arts commission|"
     r"trustees of the public library|landmarks commission|zoning board|procurement|planning and community development|"
     r"segregated reserve|retirement system"),
    ("taxes", "Taxes and fees", False,
     r"\btax|transfer fee|exemption|fines which may be imposed|snow removal penalt|long-term homeowners"),
    ("housing", "Housing and tenants", False,
     r"rent stabilization|eviction|governmentally-involved housing|stabilization act|affordable housing"),
    ("workforce", "City workforce and public safety", False,
     r"residency preference|cadet|police academy|school police|special police|emergency telecommunicators|"
     r"superannuation|surviving spouses|police officer in the city|veterans|retired .*police"),
    ("land_environment", "Land, buildings and environment", False,
     r"easement|parcel|conservation land|courthouse|concurrent jurisdiction|fossil fuel|environmental justice|"
     r"sunlight|charging station|energy service|limit buildings|street closure|speed limit|historic .*district"),
    ("education", "Education", False, r"early education|school"),
]
OTHER = ("other", "Other", False)

LABELS = {k: label for k, label, _, _ in RULES} | {OTHER[0]: OTHER[1]}
ROUTINE = {k for k, _, routine, _ in RULES if routine}


def categorize(title: str, overrides: dict | None = None, key: str | None = None) -> str:
    if overrides and key and key in overrides:
        return overrides[key]
    t = re.sub(r"\s+", " ", title or "")
    for k, _, _, pattern in RULES:
        if re.search(pattern, t, re.I):
            return k
    return OTHER[0]


def _name(title: str, after: str) -> str | None:
    """The name following the *last* occurrence of `after` ("…for police officers for Adam Watt" → "Adam Watt")."""
    t = re.sub(r"\s+", " ", title or "").strip(" .")
    t = re.sub(r"\s+administered by .*$", "", t, flags=re.I)
    m = re.search(r".*(?:" + after + r")\s+(.+?)\s*$", t, re.I)
    if m:
        return m.group(1).strip(" .")
    m = re.search(r"^(?:An Act\s+)?(.+?)\s+disability pension$", t, re.I)  # "Lieutenant Deputy Sheriff Brian McPherson disability pension"
    return m.group(1).strip(" .") if m else None


def template_summary(category: str, title: str) -> str | None:
    """A plain-language summary for routine petitions, filled in from the title."""
    t = re.sub(r"\s+", " ", title or "").strip()
    if category == "age_waiver":
        dept = "Fire Department" if re.search(r"fire", t, re.I) else "Police Department"
        who = _name(t, r"\b(?:for|officer)") or "a named candidate"
        role = "firefighter" if dept == "Fire Department" else "police officer"
        return (f"Lets the Boston {dept} hire {who} as a {role} even though they're over the maximum entry age "
                f"set by state civil service law.")
    if category == "individual_benefits":
        if re.search(r"widow", t, re.I):
            return "Provides death benefits to the widow of a former Boston firefighter."
        if re.search(r"surviving beneficiary", t, re.I):
            who = _name(t, r"beneficiary of")
            return f"Changes the retirement benefits paid to the surviving beneficiary of {who or 'a former employee'}."
        if re.search(r"creditable service", t, re.I):
            who = _name(t, r"service to")
            return f"Grants {who or 'a named employee'} additional creditable service toward retirement."
        if re.search(r"disability pension", t, re.I):
            who = _name(t, r"pension (?:for|of)")
            return f"Authorizes a disability pension for {who or 'a named employee'}, outside the standard retirement rules."
        who = _name(t, r"firefighter|for")
        return f"Authorizes pension benefits for {who or 'a named employee'}, outside the standard retirement rules."
    return None


SHORT_TITLE = {"age_waiver": "Age waiver", "individual_benefits": "Pension or benefits"}


def template_short_title(category: str, title: str) -> str | None:
    t = re.sub(r"\s+", " ", title or "")
    if category == "age_waiver":
        who = _name(t, r"\b(?:for|officer)")
        return f"Age waiver: {who}" if who else "Age waiver"
    if category == "individual_benefits":
        if re.search(r"widow", t, re.I):
            return "Death benefits for a firefighter's widow"
        who = _name(t, r"pension (?:for|of)|beneficiary of|service to|firefighter|for")
        kind = "Disability pension" if "disability" in t.lower() else "Retirement benefits"
        return f"{kind}: {who}" if who else kind
    return None


OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "data" / "category_overrides.json"


def load_overrides(path: Path = OVERRIDES_PATH) -> dict:
    try:
        return {k: v for k, v in json.loads(path.read_text()).items() if not k.startswith("_")}
    except FileNotFoundError:
        return {}


def apply(petitions: list[dict], overrides: dict | None = None) -> None:
    """Set each petition's category, and fill in template summaries for routine ones without a Claude summary."""
    overrides = load_overrides() if overrides is None else overrides
    for p in petitions:
        key = f"{p['court']}/{p.get('bill') or p.get('docket')}"
        cat = categorize(p.get("title"), overrides, key)
        p["category"] = cat
        p["category_label"] = LABELS.get(cat, cat)
        if cat in ROUTINE and p.get("summary_source") != "claude":
            summary = template_summary(cat, p.get("title"))
            if summary:
                p["summary"], p["summary_source"] = summary, "template"
                p["short_title"] = template_short_title(cat, p.get("title"))


def needs_summary(court: int, bill: str, title: str, overrides: dict | None = None) -> bool:
    overrides = load_overrides() if overrides is None else overrides
    return categorize(title, overrides, f"{court}/{bill}") not in ROUTINE
