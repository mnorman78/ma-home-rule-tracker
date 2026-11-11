"""Client for the Massachusetts Legislature API with an on-disk cache.

Closed sessions never change, so their responses are cached indefinitely.
Responses for the current session are refreshed once they're older than
`max_age` seconds.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://malegislature.gov/api"
SITE = "https://malegislature.gov"
USER_AGENT = "ma-home-rule-tracker/0.2"


def current_court(today: dt.date | None = None) -> int:
    """A new General Court convenes the first Wednesday of each odd-numbered year (194th: 2025-26)."""
    today = today or dt.date.today()
    year = today.year if today.year % 2 else today.year - 1
    jan1 = dt.date(year, 1, 1)
    first_wed = jan1 + dt.timedelta(days=(2 - jan1.weekday()) % 7)
    if today < first_wed:
        year -= 2
    return 194 + (year - 2025) // 2


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def court_years(court: int) -> str:
    start = 2025 + (court - 194) * 2
    return f"{start}–{str(start + 1)[2:]}"


def bill_url(court: int, number: str) -> str:
    return f"{SITE}/Bills/{court}/{number}"


class Client:
    def __init__(self, cache_dir: Path, max_age: float = 12 * 3600, offline: bool = False):
        self.cache_dir = cache_dir
        self.max_age = max_age
        self.offline = offline
        self.live_court = current_court()
        self.requests = 0
        self._lock = threading.Lock()

    # -- low level -----------------------------------------------------------

    def _fetch(self, path: str, retries: int = 3):
        url = f"{API}{urllib.parse.quote(path)}"  # some member codes contain spaces
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    with self._lock:
                        self.requests += 1
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code in (400, 404) or attempt == retries - 1:
                    raise RuntimeError(f"GET {url} -> HTTP {e.code}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == retries - 1:
                    raise RuntimeError(f"GET {url} failed: {e}") from e
            time.sleep(2 * (attempt + 1))

    def get(self, court: int, path: str, transform=None):
        """GET `path`, cached under the session it belongs to."""
        key = path.strip("/").replace("/", "__")
        file = self.cache_dir / str(court) / f"{key}.json"
        fresh_enough = court < self.live_court or (
            file.exists() and time.time() - file.stat().st_mtime < self.max_age
        )
        if file.exists() and (fresh_enough or self.offline):
            return json.loads(file.read_text())
        if self.offline:
            raise RuntimeError(f"offline and not cached: {path}")
        data = self._fetch(path)
        if transform:
            data = transform(data)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data))
        return data

    # -- endpoints -----------------------------------------------------------

    def city_documents(self, court: int, city: str) -> list[dict]:
        return self.get(court, f"/GeneralCourts/{court}/Cities/{city}/Documents")

    def document(self, court: int, number: str) -> dict:
        return self.get(court, f"/GeneralCourts/{court}/Documents/{number}")

    def history(self, court: int, number: str) -> list[dict]:
        return self.get(court, f"/GeneralCourts/{court}/Documents/{number}/DocumentHistoryActions")

    def members(self, court: int) -> list[dict]:
        return self.get(court, f"/GeneralCourts/{court}/LegislativeMembers")

    def member(self, court: int, code: str) -> dict:
        # Member records embed every bill they sponsored; drop those to keep the cache small.
        drop = {"SponsoredBills", "CoSponsoredBills", "Committees"}
        return self.get(court, f"/GeneralCourts/{court}/LegislativeMembers/{code}",
                        transform=lambda d: {k: v for k, v in d.items() if k not in drop})

    def roll_call(self, court: int, branch: str, number: int) -> dict:
        return self.get(court, f"/GeneralCourts/{court}/Branches/{branch}/RollCalls/{number}")
