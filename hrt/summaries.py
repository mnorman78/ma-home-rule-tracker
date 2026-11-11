"""Plain-English short titles and summaries for petitions, written by Claude.

Each summary is generated once and stored in data/summaries.json, which is
checked in, so re-running the tracker doesn't pay for unchanged bills.
Without the Anthropic SDK or credentials, summaries are skipped and the
tracker falls back to the Legislature's own one-line description.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import sys
import threading
from pathlib import Path

MODEL = "claude-opus-5-5"

SYSTEM = """You write entries for a public tracker of home rule petitions: requests from the City of Boston asking the Massachusetts Legislature to pass a special law that applies only to Boston.

For each petition you get the official title, the Legislature's filing description, and the bill text. Return:

- short_title: at most 8 words, plain language, no "An Act". Name the specific person or place when the bill is about one (e.g. "Police age waiver for Elijah Osborne", "Real estate transfer fee and senior tax relief").
- summary: one or two sentences (under 60 words) saying what the law would do and who it affects, written for a resident who has never read a bill. Mention concrete numbers, dates, or locations if the text has them. Don't speculate beyond the text, and don't comment on whether it's a good idea.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "short_title": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["short_title", "summary"],
    "additionalProperties": False,
}


class Summarizer:
    def __init__(self, store: Path, enabled: bool = True):
        self.store = store
        self.cache: dict[str, dict] = json.loads(store.read_text()) if store.exists() else {}
        self._lock = threading.Lock()
        self.client = None
        self.generated = 0
        self.failed: list[str] = []
        if enabled:
            self.client = self._make_client()

    @staticmethod
    def _make_client():
        try:
            import anthropic
        except ImportError:
            print("Summaries skipped: the anthropic package isn't installed (run with `uv run`).", file=sys.stderr)
            return None
        try:
            return anthropic.Anthropic(max_retries=4)
        except anthropic.AnthropicError as e:
            print(f"Summaries skipped: no Anthropic credentials ({e}). Set ANTHROPIC_API_KEY to enable.", file=sys.stderr)
            return None

    @staticmethod
    def key(court: int, bill: str) -> str:
        return f"{court}/{bill}"

    def get(self, court: int, bill: str) -> dict | None:
        return self.cache.get(self.key(court, bill))

    def _save(self):
        tmp = self.store.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(sorted(self.cache.items())), indent=1, ensure_ascii=False))
        tmp.replace(self.store)

    def _summarize(self, title: str, pinslip: str, text: str) -> dict | None:
        import anthropic

        prompt = (
            f"Official title: {title}\n\n"
            f"Filing description: {pinslip or '(none)'}\n\n"
            f"Bill text:\n{text.strip() or '(no text available)'}"
        )
        response = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            return None
        raw = next((b.text for b in response.content if b.type == "text"), None)
        if not raw:
            return None
        data = json.loads(raw)
        return {
            "short_title": data["short_title"].strip(),
            "summary": data["summary"].strip(),
            "model": response.model,
            "generated": dt.date.today().isoformat(),
        }

    def fill(self, items: list[dict], workers: int = 4) -> None:
        """Generate summaries for items missing one. Each item: court, bill, title, pinslip, text."""
        if not self.client:
            return
        todo = [i for i in items if self.key(i["court"], i["bill"]) not in self.cache]
        if not todo:
            return
        import anthropic

        print(f"Writing {len(todo)} summaries with {MODEL}…", file=sys.stderr)

        stop = threading.Event()

        def one(item):
            k = self.key(item["court"], item["bill"])
            if stop.is_set():
                return
            try:
                result = self._summarize(item["title"], item["pinslip"], item["text"])
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.CredentialsError, TypeError) as e:
                # With no credentials at all, the SDK raises TypeError while building the request.
                if not stop.is_set():
                    print(f"Summaries stopped: {type(e).__name__}. Set ANTHROPIC_API_KEY (or run `ant auth login`).", file=sys.stderr)
                stop.set()
                return
            except (anthropic.APIError, json.JSONDecodeError, KeyError) as e:
                print(f"  {k}: {type(e).__name__}: {e}", file=sys.stderr)
                result = None
            with self._lock:
                if result:
                    self.cache[k] = result
                    self.generated += 1
                    if self.generated % 10 == 0:
                        self._save()
                else:
                    self.failed.append(k)

        with cf.ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, todo))
        with self._lock:
            self._save()
        if stop.is_set():
            self.client = None  # no credentials: don't try again for later sessions
            return
        print(f"  {self.generated} written, {len(self.failed)} failed", file=sys.stderr)
