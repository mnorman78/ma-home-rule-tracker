"""Boston's State House delegation for a given General Court."""

from __future__ import annotations

import concurrent.futures as cf
import json
from pathlib import Path

from .api import Client, ordinal


def load_rules(path: Path) -> list[dict]:
    return json.loads(path.read_text())["maps"]


def district_in_boston(rules: list[dict], court: int, branch: str, district: str | None) -> bool:
    if not district:
        return False
    rule = next((m for m in rules if court in m["courts"]), None)
    if rule is None:
        raise ValueError(f"delegation.json has no redistricting map covering the {ordinal(court)} General Court")
    if district in rule["exclude"].get(branch, []):
        return False
    return any(s.lower() in district.lower() for s in rule["include_if_name_contains"])


def member_summary(m: dict) -> dict:
    return {
        "code": m["MemberCode"],
        "name": m["Name"],
        "branch": m["Branch"],
        "district": m.get("District"),
        "party": m.get("Party"),
    }


def all_members(client: Client, court: int, workers: int = 6) -> dict[str, dict]:
    codes = [m["MemberCode"] for m in client.members(court)]
    with cf.ThreadPoolExecutor(workers) as ex:
        records = list(ex.map(lambda c: client.member(court, c), codes))
    return {r["MemberCode"]: member_summary(r) for r in records}


def delegation(rules: list[dict], court: int, members: dict[str, dict]) -> dict[str, dict]:
    """Members whose district includes part of Boston, keyed by member code."""
    return {
        code: m for code, m in members.items()
        if district_in_boston(rules, court, m["branch"], m["district"])
    }
