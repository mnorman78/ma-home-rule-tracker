"""Free news coverage of petitions, from outlets with an open search API.

Sources: CommonWealth Beacon and the Dorchester Reporter (both WordPress, both
free to read). Paywalled outlets are deliberately left out, and so are sites
that block automated requests.

For each non-routine petition the search uses the two most distinctive
two-word phrases from its title ("ranked choice", "rent stabilization"),
limited to the dates the petition was active. An article counts only if its
text contains one of those exact phrases, mentions Boston, and mentions
"home rule" or the bill number, which ties it to the petition rather than the
topic. Only the headline, date and link are kept; whether the text mentions an
objection is noted as a flag.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

SOURCES = [
    ("CommonWealth Beacon", "https://commonwealthbeacon.org/wp-json/wp/v2/posts"),
    ("Dorchester Reporter", "https://www.dotnews.com/wp-json/wp/v2/posts"),
]

GENERIC = set("""act relative city boston authorizing authorize certain section regarding directing establish
provide providing concerning further amend amending the of to for in and a an on by with from into its
petition special law home rule new""".split())
HOME_RULE = re.compile(r"home[- ]rule", re.I)
OBJECTION = re.compile(r"\bobject(?:ed|ion|s)\b", re.I)


def phrases(title: str, df: dict[str, int], n: int = 2) -> list[str]:
    """The `n` most distinctive two-word phrases in a title ("ranked choice", "rent stabilization").

    Single words match too much unrelated coverage; a phrase from the title is a much stronger signal.
    Rarity is measured across all petition titles.
    """
    words = re.findall(r"[a-z0-9][a-z0-9'\-]*", (title or "").lower())
    pairs = {}
    for a, b in zip(words, words[1:]):
        if a in GENERIC or b in GENERIC or len(a) < 3 or len(b) < 3:
            continue
        pairs[f"{a} {b}"] = df.get(a, 0) + df.get(b, 0)
    return sorted(pairs, key=pairs.get)[:n]


class News:
    def __init__(self, cache_dir: Path, offline: bool = False, max_age: float = 7 * 86400):
        self.cache_dir = cache_dir / "news"
        self.offline = offline
        self.max_age = max_age
        self.requests = 0
        self._lock = threading.Lock()

    def _get(self, url: str):
        key = re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:]
        file = self.cache_dir / f"{key}.json"
        if file.exists() and (self.offline or time.time() - file.stat().st_mtime < self.max_age):
            return json.loads(file.read_text())
        if self.offline:
            return []
        req = urllib.request.Request(url, headers={"User-Agent": "ma-home-rule-tracker/0.4 (civic research)"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            with self._lock:
                self.requests += 1
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            return []  # a news site being down shouldn't stop the tracker
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data))
        return data

    def search(self, phrase_list: list[str], bill: str | None, after: str, before: str) -> list[dict]:
        out, seen = [], set()
        for name, base in SOURCES:
            for phrase in phrase_list:
                q = urllib.parse.urlencode({
                    "search": phrase, "after": f"{after}T00:00:00", "before": f"{before}T23:59:59",
                    "per_page": 20, "_fields": "date,link,title,content",
                })
                for post in self._get(f"{base}?{q}") or []:
                    if post.get("link") in seen:
                        continue
                    text = html.unescape(re.sub(r"<[^>]+>", " ", (post.get("content") or {}).get("rendered", "")))
                    flat = re.sub(r"\s+", " ", text).lower()
                    if not any(ph in flat for ph in phrase_list) or "boston" not in flat:
                        continue
                    # Tie it to the petition itself, not just the topic.
                    if not (HOME_RULE.search(text) or (bill and re.search(rf"\b{bill[0]}\.?\s?{bill[1:]}\b", text))):
                        continue
                    seen.add(post["link"])
                    out.append({
                        "source": name,
                        "date": post["date"][:10],
                        "title": html.unescape(re.sub(r"<[^>]+>", "", (post.get("title") or {}).get("rendered", ""))),
                        "url": post["link"],
                        "mentions_objection": bool(OBJECTION.search(text)),
                    })
        out.sort(key=lambda a: a["date"], reverse=True)
        return out[:5]


def attach_news(dataset: dict, news: News, routine: set[str]) -> int:
    """Add `news` to each non-routine petition. Returns how many petitions got at least one article."""
    titles = [p.get("title") or "" for p in dataset["petitions"]]
    df = Counter(w for t in titles for w in set(re.findall(r"[a-z0-9][a-z0-9'\-]*", t.lower())))
    found = 0
    today = dt.date.today()
    for p in dataset["petitions"]:
        p["news"] = []
        if p.get("category") in routine or not p.get("title"):
            continue
        ph = phrases(p["title"], df)
        if not ph:
            continue
        start = (p.get("council") or {}).get("filed") or p.get("filed_date") or f"{2025 + (p['court'] - 194) * 2}-01-01"
        start_d = dt.date.fromisoformat(start) - dt.timedelta(days=60)
        end_d = min(dt.date.fromisoformat(p.get("last_action_date") or today.isoformat()) + dt.timedelta(days=90), today)
        p["news"] = news.search(ph, p.get("bill"), start_d.isoformat(), end_d.isoformat())
        p["news_query"] = ph
        found += bool(p["news"])
    return found
