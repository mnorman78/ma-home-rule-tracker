# MA Home Rule Tracker

Tracks Boston's home rule petitions from City Hall through the Massachusetts Legislature over the last 10 years: how the City Council voted, who carried each one at the State House, how far it got, and how Boston's delegation voted where a vote was recorded. See [PRD.md](PRD.md) for goals and data findings.

## Setup

Requires [uv](https://docs.astral.sh/uv/). It installs Python 3.15 and the Anthropic SDK into `.venv`:

```bash
uv sync
```

For petition summaries, set an Anthropic API key (or run `ant auth login`):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Without one, the tracker still runs and uses the Legislature's one-line filing description as the summary.

## Usage

```bash
uv run tracker.py                       # last 10 years (2015-16 to now)
uv run tracker.py --since 193           # from the 193rd General Court (2023-24)
uv run tracker.py --no-summaries        # skip the Claude API step
uv run tracker.py --offline             # use only cached API responses
uv run tracker.py --check-delegation    # list who delegation.json selects
```

Outputs:

- `output/boston.html`: a filterable report with three tabs:
  - **Petitions:** filter by session, status and transmitting legislator, or search. Each petition shows its City Council vote and its State House record.
  - **City Council:** every council home rule petition since 2021, filterable to split votes or petitions never filed at the State House.
  - **Delegation:** each member's transmitted petitions and recorded votes.
- `output/boston.json`: the full dataset.

## Automation (GitHub Actions)

Two scheduled workflows keep the published report current:

| Workflow | Schedule | What it does |
|---|---|---|
| [Daily update](.github/workflows/update.yml) | Every day, 6–7 AM Boston time | Checks the Legislature and City Council for new petitions and changes, records them in the report's **Updates** tab, and republishes GitHub Pages. New summaries are committed back to `data/summaries.json`. |
| [Election and roster check](.github/workflows/elections.yml) | Weekly on Mondays; daily November–January | Compares Boston's State House delegation with the last published run, and scans recent City Council minutes for councilors the roster doesn't know (or roster members who stopped appearing). Opens or updates a `roster-check` issue when something needs a hand edit. |

### Email notifications

The daily update posts notifications as GitHub issues that mention the repository owner, so GitHub emails them to the address on that account:

- **Daily, only when something happened** (label `update`): one issue grouping
  - petitions **passed by the City Council**,
  - petitions **taken up by the Legislature**: filed at the State House, hearing scheduled, or reported out of committee,
  - petitions **voted on by the Legislature**: passed a chamber, enacted, signed, or vetoed.
- **When a General Court ends** (label `session-report`): the first run after the new session convenes (January of odd years) posts every petition that died in the session that just ended. It lists what was still pending at the end and what died earlier (sent to study, vetoed), each with its furthest step, sponsor and City Council vote.

To get these by email, keep GitHub email notifications on for issues (Settings → Notifications on github.com). Close or unsubscribe from issues as you like; that doesn't affect tracking.

The report's Updates tab also lists upcoming state and city elections and the dates new terms begin, computed from the election rules (not hardcoded).

Optional repository secret: `ANTHROPIC_API_KEY`, to generate summaries in the scheduled run.

**When an issue opens:**
- *New councilor or departure:* edit [data/council_roster.json](data/council_roster.json) (name, surnames as written in the minutes, seat, start and end dates).
- *New delegation member:* nothing to edit unless the district list is wrong. Districts come from the Legislature's data.
- *No redistricting map:* add the next map's districts to [delegation.json](delegation.json). This is needed after the 2030 census, for the 198th General Court (2033–34).

## What it tracks

For each petition (a bill filed "with the approval of the mayor and city council"):

| Field | Source |
|---|---|
| Short title and summary | Written by Claude (`claude-opus-5-5`) from the bill text, cached in `data/summaries.json` |
| Transmitting legislator | The bill's primary sponsor |
| Status | Became law / Pending / Died / Died at end of session, from the bill history. Redrafts are followed to the bill that replaced them. |
| Floor record | Per chamber: voice vote, roll call (tally and number), or no floor vote |
| Delegation votes | Each Boston senator's Yea / Nay / Absent on Senate roll calls |
| City Council vote (2021+) | Council docket, passage date and each councilor's vote, read from the City Clerk's minutes via Legistar |

## Caveats

- **Most petitions have no recorded votes.** They pass or die on voice votes, which don't record individual members. Only a handful since 2015 had roll calls.
- **House roll calls by member aren't available** through the Legislature's API. The report shows the tally and roll-call number; member votes are in the House Journal.
- **The Boston delegation is defined in [delegation.json](delegation.json)** by district name for each redistricting map. Run `--check-delegation` to review it, and edit the file if a district is wrong.
- **City Council data starts in 2021.** Earlier Legistar records have no minutes.
- **Council roll calls name only the smaller side.** The rest is filled in from [data/council_roster.json](data/council_roster.json) only when the roster, attendance and tally agree exactly; otherwise the vote is marked partial.
- **Council dockets are linked to state bills by title and date,** since neither system references the other. Each link shows its match score. Fix wrong or missing links in [data/council_matches.json](data/council_matches.json).
- Stages are inferred from history text, so unusual wording can be misread. The latest action is always shown verbatim.
- Petitions the City Council passed but nobody filed at the State House aren't in the Legislature's data.

## Layout

```
tracker.py          CLI
hrt/api.py          API client with on-disk cache (closed sessions cached permanently)
hrt/history.py      stage, status and floor-vote parsing from bill histories
hrt/delegation.py   which members represent Boston
hrt/summaries.py    Claude-written titles and summaries
hrt/council.py      City Council dockets (Legistar) and votes (minutes PDFs)
hrt/matching.py     links council dockets to state bills
hrt/changes.py      what changed since the last run
hrt/elections.py    election calendar, delegation and council roster checks
hrt/notify.py       which changes trigger notifications; daily and end-of-session issues
hrt/post.py         posts notifications as GitHub issues
hrt/pipeline.py     builds the dataset across sessions
hrt/report.py       HTML report
```
