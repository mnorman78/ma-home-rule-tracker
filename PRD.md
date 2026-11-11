# PRD: Boston Home Rule Petition Tracker

## Problem

Boston can't pass certain laws on its own. It petitions the state Legislature for a special act. Once a petition leaves City Hall it's hard to follow: it gets a state bill number, may be replaced by a redraft, and often stalls without any recorded vote. Nobody has a single view of what Boston has asked for, who carried it at the State House, how far it got, and how Boston's own delegation acted on it.

## Goals

For every Boston home rule petition from the last 10 years (2015–present):

1. **Title and summary.** The official title plus a one-to-two sentence plain-English summary of what the petition would do.
2. **Transmitting legislator.** The representative or senator who filed it at the State House.
3. **Status.** How far it got, including whether it became law (with chapter number), was replaced by a redraft (followed to the successor bill), was sent to study, or died when the session ended.
4. **Delegation votes.** How each member of Boston's State House delegation voted, where a recorded vote exists.
5. **City Council votes.** The council docket that approved each petition, when it passed, and how each councilor voted.

## Non-goals (for now)

- Mayoral action on council-passed petitions (signature or veto). Not in Legistar's structured data.
- City Council records before 2021 (see Council votes below).
- Petitions from other cities. The code takes `--city`, but the delegation definition and testing are Boston-only.
- Alerts or notifications on status change.

## Users

Primarily the owner, as a research and civic-tracking tool. Output should be shareable: a static HTML report someone else can open.

## Scope: sessions

A General Court is a two-year session. "Last 10 years" covers:

| General Court | Years | Redistricting map |
|---|---|---|
| 189th | 2015–16 | 2011 |
| 190th | 2017–18 | 2011 |
| 191st | 2019–20 | 2011 |
| 192nd | 2021–22 | 2011 |
| 193rd | 2023–24 | 2021 |
| 194th | 2025–26 | 2021 |

The 195th (2027–28) gets picked up automatically once it convenes.

## Data sources and findings

All data comes from the Legislature's public API, `https://malegislature.gov/api`.

| Need | Source | Notes |
|---|---|---|
| Petition list | `/GeneralCourts/{n}/Cities/Boston/Documents` | Verified against a title search of all ~10,000 bills in the 193rd: catches every original petition. Title-only matches it misses are unrelated bills or new drafts, which we reach by following redrafts instead. |
| Is it a home rule petition? | `Pinslip` on the bill: "with the approval of the mayor and city council" / "[Local Approval Received.]" | About 90% of the city-tagged documents qualify. The rest are ordinary bills that mention Boston. |
| Transmitting legislator | `PrimarySponsor` on the bill | The pinslip also names them ("By Representative Worrell of Boston"). |
| Status | `/Documents/{bill}/DocumentHistoryActions` | Stage inferred from action text. Redrafts ("New draft substituted, see H5585") are followed to the bill that carries the petition forward. |
| Bill text for summaries | `DocumentText` on the bill | Present for nearly every petition. |
| Votes | `RollCalls` on the bill → `/Branches/Senate/RollCalls/{n}` | See below. |
| Delegation | `/GeneralCourts/{n}/LegislativeMembers/{code}` (`District`, `Branch`, `Party`) | See below. |

### Votes

Since 2015 only about 3 of ~170 Boston petitions had a recorded roll call, all in the Senate. Everything else passed or died on a voice vote, which doesn't record how individual members voted. So:

- Each petition records **how it moved in each chamber**: voice vote, roll call (with tally), or no floor action.
- Where a **Senate roll call** exists, each Boston senator's Yea / Nay / Absent is shown.
- **House roll calls** aren't served by the API (the endpoint errors) or linked from bill pages. They appear only in House Journal PDFs. The history line ("Enacted - 156 YEAS to 0 NAYS (See YEA and NAY No. 196)") gives the tally and roll-call number, which we show. Member-level House votes are a possible later phase (parse Journal PDFs).

### Boston delegation

The API gives each member's district name ("5th Suffolk", "Second Suffolk and Middlesex") but not which municipalities it covers. The delegation is defined in `delegation.json`: a list of district names per redistricting map that include part of Boston. It's seeded from the Suffolk County districts minus those that don't touch Boston, then checked against each member's hometown as printed in their bill pinslips. The file is meant to be hand-edited if a district is wrong.

### City Council votes

Source: the Council's Legistar instance (`https://webapi.legistar.com/v1/boston`) plus the City Clerk's official minutes PDFs it links.

Findings:

- **Coverage starts in 2021.** Earlier Legistar records are archived stubs with no minutes or membership.
- **Petitions aren't consistently typed.** They're filed as "Council Home Rule Petition", "Mayor Home Rule Petition", "Committee Reports", "Matters Recently Heard" and more. They're found by title ("petition" plus "special law", "General Court" or "home rule"), excluding resolutions, hearing orders and the like. About 140 dockets since 2021.
- **Legistar records no roll calls**, not even on contested votes. The minutes do, consistently: *"the petition was passed; yeas 11, nays 2. (Baker and Murphy)."* Only the smaller side is named.
- **Legistar's membership records are wrong** (missing members, wrong end dates). `data/council_roster.json` holds a roster built from the councilors named in the minutes. The unnamed side of a roll call is filled in only when the roster, the meeting's attendance line and the tally all agree exactly; otherwise the record is marked partial. Result: 57 of 60 roll calls complete.
- **Many unanimous votes are recorded as roll calls** ("yeas 13"); others pass by voice ("the rules were suspended; the petition was passed"), which records no individual votes.

**Linking council dockets to state bills.** Neither system references the other. Dockets are matched to state bills by the act's title with rarity-weighted word overlap, so officers' names in age waivers decide those matches. Constraints:

- The council vote must fall within about 3 years before, or 8 months after, the state filing.
- Each state bill gets at most one docket.
- Within a session, a docket goes to at most one House bill and one Senate bill (companion filings).

Hand corrections go in `data/council_matches.json`. Result: 89 of the 121 state petitions since 2021 are linked. Most unlinked ones were filed in early 2021 on council votes from before Legistar's coverage.

## Requirements

### Data

- R1. Fetch all Boston home rule petitions for the 189th–current General Courts.
- R2. Cache API responses on disk. Closed sessions never change, so the 10-year backfill runs once. The current session is refreshed on each run.
- R3. For each petition, record: session, bill number, docket number, title, summary, transmitting legislator (name, branch, district), filed date, committee, stage, chapter (if law), successor bill (if redrafted), last action and date, per-chamber vote record, and delegation votes.
- R4. A petition still pending when its session ended gets the status **Died at end of session**, with the furthest stage it reached kept alongside.

### Summaries

- R5. Generate each summary with the Claude API from the bill's title, pinslip and text: one or two plain sentences saying what the petition would do and who it affects.
- R6. Cache summaries by bill and session so each one is generated once. Re-running costs nothing for unchanged bills.
- R7. If `ANTHROPIC_API_KEY` isn't set, skip summaries with a warning and fall back to the pinslip description. The rest of the tracker still runs.

### Report

- R8. A static HTML report covering all sessions, filterable by session, stage and sponsor, and searchable.
- R9. Each petition shows its title, summary, sponsor, status, link to the bill, and vote record, with a delegation vote grid where one exists.
- R10. A delegation view: each member, the petitions they transmitted, and their recorded votes.
- R11. A JSON export of the full dataset.

### City Council

- R12. For each state petition since 2021, link the council docket that approved it, with passage date, vote (roll call with each councilor's vote, or voice vote) and a link to the minutes.
- R13. A City Council view listing every council home rule petition, its vote, and what happened at the State House, including petitions that passed the council but were never found there.
- R14. Never guess a councilor's vote. Infer the unnamed side only when the roster, attendance and tally agree exactly, and mark partial records as partial.

### Ongoing tracking

- R15. Publish the report publicly on GitHub Pages, updated daily by a scheduled workflow.
- R16. Each run compares with the last published data and records new petitions (council and state), stage and status changes, and new council votes in a changelog shown on the site.
- R17. Track election and term dates (computed from the rules: state elections in even years, Boston municipal elections in odd years, terms starting in January).
- R18. Check weekly, and daily from November through January, for new or departed delegation members and for councilors the roster doesn't know. Open a GitHub issue when a hand edit is needed.

### Evidence of individual positions beyond roll calls

Voice votes don't record individual members. These sources come closest, and are collected for each petition:

| Source | What it shows | Coverage |
|---|---|---|
| Committee votes (API, in the bill record) | Each committee member's vote on reporting the bill | Published from 2025 on |
| House roll-call PDFs (`/Journal/House/{court}/RollCalls/`) | Member-by-member House roll calls; the API doesn't serve these | 2015 on |
| House and Senate Journals (daily PDFs) | Official account of each floor action; whether it was an informal session (one objection blocks); doubted votes, objections, member statements | 2015 on |
| Session video (Sessions API) | Archived video of each session where the bill was acted on | 2015 on |
| City Council meeting page (Legistar) | Meeting video, agenda and minutes | 2021 on |
| Cosponsors (API) | Delegation members who signed on | All years |
| News: CommonWealth Beacon, Dorchester Reporter (WordPress search APIs) | Coverage naming the petition; flag when it mentions an objection | Free sources only; paywalled sites and sites blocking automation are excluded |

- R24. Show these on each petition, and per member in the Delegation tab (cosponsorships, committee votes, floor roll calls).

### Categories

- R22. Sort every petition (and council docket) into a category by title. Routine categories are age waivers (54 of 182) and pensions or benefits for individuals (18). They get a standard summary filled in from the title instead of a Claude summary, which leaves about 100 petitions for Claude.
- R23. The report filters by category, including a "hide age waivers and pensions" option.

### Notifications

Delivered as GitHub issues that mention the owner, so GitHub emails them. This needs no credentials, and the issues double as a searchable log.

- R19. One email per day, only when something happened, covering:
  - petitions passed by the City Council;
  - petitions taken up by the Legislature: filed, hearing scheduled, or reported out of committee;
  - petitions voted on by the Legislature: passed a chamber, enacted, signed, or vetoed.
- R20. When a General Court ends, one email listing every petition that died in it, with its furthest step, sponsor and City Council vote.
- R21. Never email the same change twice. Notifications are posted only after the site deploys, because the next run compares against the published data.

## Open questions

- Council votes before 2021: the City Clerk may have older minutes outside Legistar. Worth backfilling?

- Should petitions that died in committee in one session and were refiled the next be linked as the same effort? (Not in v1. Possible later by matching titles.)
- Member-level House votes from Journal PDFs: worth building given how rare House roll calls on these petitions are?
- Should cosponsorship count as a delegation position? (Not in v1.)
