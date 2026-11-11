# MA Home Rule Tracker

Tracks Boston's home rule petitions from City Hall through the Massachusetts Legislature over the last 10 years: how the City Council voted, who carried each one at the State House, how far it got, and how Boston's delegation voted where a vote was recorded. See [PRD.md](PRD.md) for goals and data findings.

**Live site: https://mnorman78.github.io/ma-home-rule-tracker/**. It's updated daily. The data behind it is at [boston.json](https://mnorman78.github.io/ma-home-rule-tracker/boston.json) and [changelog.json](https://mnorman78.github.io/ma-home-rule-tracker/changelog.json).

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

### Claude API sign-in

Summaries need the Claude API. The daily update signs in one of two ways:

1. **Workload Identity Federation (recommended, no key to expire).** GitHub gives each run a short-lived identity token, and the Anthropic SDK exchanges it for a 10-minute access token. One-time setup:
   1. In the Claude Console, open **Settings → Workload identity** (platform.claude.com/settings/workload-identity-federation), click **Connect workload**, and choose **GitHub Actions**. The wizard creates the issuer, a service account and a federation rule. For the rule, use:
      - Subject: `repo:mnorman78@3527366/ma-home-rule-tracker@1453477622:environment:github-pages`. GitHub's tokens name the owner and repository with their permanent numeric IDs, which keeps the rule from matching a renamed or recreated repo. The update job deploys to the `github-pages` environment, which GitHub restricts to the main branch. To see the exact subject your token carries, run the "Test Claude API sign-in" workflow.
      - Audience: `https://api.anthropic.com`
      - Claim `repository_owner`: `mnorman78`
      - Scope: `workspace:developer`
   2. Add four **repository variables** (Settings → Secrets and variables → Actions → Variables). These are IDs, not secrets: `ANTHROPIC_FEDERATION_RULE_ID` (`fdrl_…`), `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID` (`svac_…`), and `ANTHROPIC_WORKSPACE_ID` (`wrkspc_…`).
   3. Delete the `ANTHROPIC_API_KEY` secret once a run shows "keyless sign-in" in its log.
2. **An API key** in the `ANTHROPIC_API_KEY` repository secret, used when the variables above aren't set. Keys can't be renewed automatically (the Admin API can't create them), so a key with an expiration needs replacing by hand.

If sign-in ever fails (an expired key, say), the run opens a `credentials` issue (which emails you) and keeps going with the Legislature's descriptions. It doesn't repeat while that issue is open.

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
| City Council vote (2021+) | Council docket, passage date and each councilor's vote, read from the City Clerk's minutes via Legistar, with a link to the meeting page (video, agenda, minutes) |
| Committee votes (2025+) | Each committee member's vote on reporting the petition (Favorable / Adverse / Reserved right / No vote recorded), with the Boston members highlighted |
| House roll calls by member | Parsed from the House's daily roll-call PDFs, which the API doesn't serve. Covers 2017 on; the 2015–16 "Yea and Nay Supplement" layout isn't parsed, so that session shows the tally and a link to the PDF |
| Journal entries | The House and Senate Journals' account of each floor action, flagged when it happened in an **informal session** (where any single member could have blocked it), when the vote was doubted, an objection was noted, or a member filed a statement |
| Session video | Link to the archived video of each session where the petition was acted on |
| Cosponsors | Boston delegation members who signed on to the petition |
| News coverage | Free sources only (CommonWealth Beacon, Dorchester Reporter): up to five articles per petition that name it, with a flag when the article mentions an objection. Paywalled outlets and sites that block automated access aren't searched. |

## Categories

Each petition is sorted into a category by its title ([hrt/categories.py](hrt/categories.py)). The report can filter by category, or hide the routine ones.

| Category | Summary |
|---|---|
| Age waivers (police and fire hires) | **Routine:** a standard summary filled in from the title, no Claude call |
| Pensions and benefits for individuals | **Routine:** a standard summary filled in from the title, no Claude call |
| Liquor licenses · Elections and city government · Taxes and fees · Housing and tenants · City workforce and public safety · Land, buildings and environment · Education | Written by Claude from the bill text |

To move a single petition to a different category, add it to [data/category_overrides.json](data/category_overrides.json).

## Caveats

- **Most petitions have no recorded votes.** They pass or die on voice votes, which don't record individual members. Only a handful since 2015 had roll calls.
- **Voice votes never record individual votes.** The closest evidence is what's shown: committee votes, cosponsorship, whether a vote happened in an informal session (where no one objected), Journal notes, and news coverage.
- **News matching is conservative.** An article must contain a distinctive phrase from the petition's title, mention Boston, and mention "home rule" or the bill number. Some relevant coverage will be missed rather than showing unrelated stories.
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
hrt/categories.py   categories by title; template summaries for routine petitions
hrt/records.py      committee votes, cosponsors, Journals, House roll-call PDFs, session video
hrt/news.py         free news coverage search
hrt/council.py      City Council dockets (Legistar) and votes (minutes PDFs)
hrt/matching.py     links council dockets to state bills
hrt/changes.py      what changed since the last run
hrt/elections.py    election calendar, delegation and council roster checks
hrt/notify.py       which changes trigger notifications; daily and end-of-session issues
hrt/post.py         posts notifications as GitHub issues
hrt/pipeline.py     builds the dataset across sessions
hrt/report.py       HTML report
```
