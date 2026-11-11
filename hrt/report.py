"""Render the dataset as a single self-contained HTML page."""

from __future__ import annotations

import html
import json


def render(dataset: dict) -> str:
    data = json.dumps(dataset, ensure_ascii=False).replace("</", "<\\/")
    city = html.escape(dataset["city"])
    return TEMPLATE.replace("__CITY__", city).replace("__DATA__", data)


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CITY__ Home Rule Petitions</title>
<style>
:root { --bg:#fbfaf7; --fg:#1d1d1b; --muted:#6b6a65; --line:#e4e1d8; --card:#fff; --soft:#f3f1ec; --accent:#1f4e79;
  --law:#2e7d4f; --pending:#b07a12; --dead:#8a8880; --yea:#2e7d4f; --nay:#b3362c; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#16171a; --fg:#ecebe6; --muted:#a09e97; --line:#2c2d31; --card:#1d1e22; --soft:#24252a; --accent:#8db8e8;
  --law:#6cc28f; --pending:#e0b04d; --dead:#7d7c76; --yea:#6cc28f; --nay:#ee7d72; } }
:root[data-theme="dark"] { --bg:#16171a; --fg:#ecebe6; --muted:#a09e97; --line:#2c2d31; --card:#1d1e22; --soft:#24252a; --accent:#8db8e8;
  --law:#6cc28f; --pending:#e0b04d; --dead:#7d7c76; --yea:#6cc28f; --nay:#ee7d72; }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
main { max-width:1100px; margin:0 auto; padding:28px 16px 64px; }
h1 { margin:0 0 4px; font-size:26px; letter-spacing:-.01em; }
h2 { font-size:18px; margin:28px 0 10px; }
.meta { color:var(--muted); margin-bottom:18px; font-size:14px; }
a { color:var(--accent); }
.tabs { display:flex; gap:4px; border-bottom:1px solid var(--line); margin-bottom:16px; }
.tab { background:none; border:0; border-bottom:2px solid transparent; padding:8px 12px; font:inherit; color:var(--muted); cursor:pointer; }
.tab.on { color:var(--fg); border-bottom-color:var(--accent); font-weight:600; }
.row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:12px; }
.chip { border:1px solid var(--line); background:var(--card); color:var(--fg); border-radius:99px; padding:4px 12px; font:inherit; font-size:13px; cursor:pointer; }
.chip.on { background:var(--fg); color:var(--bg); border-color:var(--fg); }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; margin-bottom:14px; }
.tile { border:1px solid var(--line); background:var(--card); color:var(--fg); border-radius:10px; padding:10px 12px; text-align:left; cursor:pointer; font:inherit; }
.tile b { display:block; font-size:22px; font-variant-numeric:tabular-nums; } .tile span { color:var(--muted); font-size:13px; }
.tile.on { border-color:var(--accent); box-shadow:0 0 0 1px var(--accent) inset; }
input[type=search], select { padding:7px 10px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--fg); font:inherit; font-size:14px; }
input[type=search] { flex:1; min-width:200px; max-width:380px; }
select { max-width:100%; }
.count { color:var(--muted); font-size:13px; margin:4px 0 10px; }
.list { display:flex; flex-direction:column; gap:8px; }
details.p { border:1px solid var(--line); background:var(--card); border-radius:10px; }
details.p > summary { list-style:none; cursor:pointer; padding:12px 14px; display:grid; grid-template-columns:1fr auto; gap:4px 16px; }
details.p > summary::-webkit-details-marker { display:none; }
.ptitle { font-weight:600; }
.psum { color:var(--fg); font-size:14px; grid-column:1; }
.pmeta { color:var(--muted); font-size:13px; grid-column:1; }
.pright { grid-column:2; grid-row:1 / span 3; text-align:right; white-space:nowrap; }
.status { display:inline-block; font-size:12px; padding:2px 9px; border-radius:99px; border:1px solid currentColor; }
.st-law { color:var(--law); } .st-pending { color:var(--pending); } .st-dead { color:var(--dead); }
.stage { display:block; color:var(--muted); font-size:12px; margin-top:4px; }
.body { border-top:1px solid var(--line); padding:12px 14px 14px; display:grid; gap:12px; font-size:14px; }
.kv { display:grid; grid-template-columns:150px 1fr; gap:4px 12px; }
.kv dt { color:var(--muted); } .kv dd { margin:0; }
.floor { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:8px; }
.chamber { background:var(--soft); border-radius:8px; padding:8px 10px; }
.chamber b { display:block; font-size:13px; }
.chamber span { color:var(--muted); font-size:13px; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:500; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
.v-Yea { color:var(--yea); font-weight:600; } .v-Nay { color:var(--nay); font-weight:600; } .v-Absent, .v-Not { color:var(--muted); }
.wrap { overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--card); }
.wrap table { min-width:640px; }
.body table { max-width:460px; }
.num { white-space:nowrap; font-variant-numeric:tabular-nums; }
.cat { color:var(--accent); }
.note { color:var(--muted); font-size:13px; }
.foot { color:var(--muted); font-size:13px; margin-top:24px; max-width:760px; }
@media (max-width:640px) {
  details.p > summary { grid-template-columns:1fr; }
  .pright { grid-column:1; grid-row:auto; text-align:left; }
  .kv { grid-template-columns:1fr; } .kv dt { margin-top:6px; }
}
</style></head>
<body><main>
<h1>__CITY__ home rule petitions</h1>
<div class="meta" id="meta"></div>
<div class="tabs"><button class="tab on" data-tab="petitions">Petitions</button><button class="tab" data-tab="council">City Council</button><button class="tab" data-tab="delegation">Delegation</button><button class="tab" data-tab="updates">Updates</button></div>

<section id="petitions">
  <div class="row" id="sessions"></div>
  <div class="tiles" id="tiles"></div>
  <div class="row">
    <input type="search" id="q" placeholder="Search titles and summaries">
    <select id="cat"><option value="">All categories</option><option value="policy">Hide age waivers and pensions</option></select>
    <select id="who"><option value="">Any transmitting legislator</option></select>
  </div>
  <div class="count" id="count"></div>
  <div class="list" id="list"></div>
</section>

<section id="council" hidden>
  <p class="note" id="cnote"></p>
  <div class="row">
    <input type="search" id="cq" placeholder="Search council dockets">
    <select id="cfilter">
      <option value="">All council dockets</option>
      <option value="split">Split votes (any nay)</option>
      <option value="unfiled">Passed council, not found at the State House</option>
      <option value="notpassed">Not passed by the council</option>
    </select>
  </div>
  <div class="count" id="ccount"></div>
  <div class="wrap"><table><thead><tr><th>Docket</th><th>Petition</th><th>Council vote</th><th>At the State House</th></tr></thead><tbody id="ctable"></tbody></table></div>
</section>

<section id="updates" hidden>
  <h2>What's new</h2>
  <p class="note">Changes the daily update found: new petitions at the City Council and the State House, stage and status changes, and new council votes.</p>
  <div id="changes"></div>
  <h2>Elections and terms</h2>
  <p class="note">When the people who vote on these petitions can change. The tracker checks for new councilors and legislators weekly, and daily from November through January.</p>
  <div class="wrap"><table><thead><tr><th>Date</th><th>Event</th><th>What it means here</th></tr></thead><tbody id="calendar"></tbody></table></div>
</section>

<section id="delegation" hidden>
  <div class="row" id="dsessions"></div>
  <p class="note">Members whose district includes part of Boston. "Transmitted" counts the petitions they filed at the State House. Recorded votes exist only where a petition got a roll call; almost all pass or die on voice votes, which don't record individual members.</p>
  <div class="wrap"><table><thead><tr><th>Member</th><th>District</th><th>Transmitted</th><th>Became law</th><th>Recorded votes</th></tr></thead><tbody id="dtable"></tbody></table></div>
</section>

<p class="foot">State data from the Massachusetts Legislature (malegislature.gov); City Council data from the Council's Legistar records and the City Clerk's minutes (2021 onward), linked to state bills by title and date. A home rule petition here is a bill filed "with the approval of the mayor and city council." Stages are read from each bill's history. When a petition was replaced by a new draft, its status follows the new bill. Summaries marked ✦ were written by Claude from the bill text. Age waivers and individual pensions get a standard summary filled in from the title; anything else unmarked is the Legislature's own filing description.</p>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const STATUS = ['Became law', 'Pending', 'Died at end of session', 'Died'];
const stCls = s => s === 'Became law' ? 'st-law' : s === 'Pending' ? 'st-pending' : 'st-dead';
const state = { court: null, status: null, q: '', who: '', cat: '' };
const CATS = D.categories || [];
const ROUTINE = new Set(CATS.filter(c => c.routine).map(c => c.key));
const catLabel = k => (CATS.find(c => c.key === k) || {}).label || k;

const years = D.sessions.map(s => s.years);
const changes = D.changes || [];
const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
const recent = changes.filter(c => c.date >= weekAgo).length;
$('#meta').innerHTML = `${D.petitions.length} petitions across ${D.sessions.length} sessions (${years[years.length-1]} to ${years[0]}) · updated ${esc(D.generated_at.replace('T',' '))}`
  + (recent ? ` · <a href="#" id="recentlink">${recent} change${recent === 1 ? '' : 's'} this week</a>` : '');

function chips(el, onPick, current) {
  el.innerHTML = [`<button class="chip${current===null?' on':''}" data-c="">All sessions</button>`]
    .concat(D.sessions.map(s => `<button class="chip${current===s.court?' on':''}" data-c="${s.court}">${s.years}${s.closed?'':' (current)'}</button>`)).join('');
  el.querySelectorAll('.chip').forEach(b => b.onclick = () => onPick(b.dataset.c ? +b.dataset.c : null));
}

function filtered(ignoreStatus) {
  const q = state.q.toLowerCase();
  return D.petitions.filter(p =>
    (state.court === null || p.court === state.court) &&
    (ignoreStatus || !state.status || p.status === state.status) &&
    (!state.who || (p.transmitter && p.transmitter.name === state.who)) &&
    (!state.cat || (state.cat === 'policy' ? !ROUTINE.has(p.category) : p.category === state.cat)) &&
    (!q || [p.title, p.short_title, p.summary, p.bill, p.docket].join(' ').toLowerCase().includes(q)));
}

function floorHtml(p) {
  const f = p.floor || {};
  const parts = ['House', 'Senate'].map(b => {
    const r = f[b]; if (!r) return '';
    let line = r.vote_type === 'no floor vote' ? 'No floor vote'
      : r.vote_type === 'voice vote' ? 'Voice vote (no individual votes recorded)'
      : r.roll_calls.map(rc => `Roll call${rc.number ? ' #' + rc.number : ''}: ${rc.yeas}–${rc.nays} (${rc.date})`).join('<br>');
    const steps = [r.engrossed && `engrossed ${r.engrossed}`, r.enacted && `enacted ${r.enacted}`].filter(Boolean).join(', ');
    return `<div class="chamber"><b>${b}</b><span>${line}${steps ? '<br>' + steps : ''}</span></div>`;
  }).join('');
  return parts ? `<div class="floor">${parts}</div>` : '';
}

function rollHtml(p) {
  return (p.roll_calls || []).map(rc => `
    <div><b>Senate roll call #${rc.number}</b> · ${rc.yeas} yea, ${rc.nays} nay, ${rc.absent} absent${rc.pdf ? ` · <a href="${esc(rc.pdf)}" target="_blank" rel="noopener">PDF</a>` : ''}
    <table><thead><tr><th>Boston senator</th><th>District</th><th>Vote</th></tr></thead><tbody>
    ${rc.delegation.map(m => `<tr><td>${esc(m.name)}</td><td>${esc(m.district)}</td><td class="v-${esc(m.vote.split(' ')[0])}">${esc(m.vote)}</td></tr>`).join('')}
    </tbody></table></div>`).join('');
}

const VORDER = ['Nay', 'Yea', 'Present', 'Absent', 'Not present'];
function voteLine(v) {
  if (!v) return 'No vote recorded';
  if (v.kind === 'voice vote') return 'Voice vote (no individual votes recorded)';
  if (v.kind === 'unknown') return 'Passed (vote not found in the minutes)';
  const extra = [v.present && `${v.present} present`, v.absent && `${v.absent} absent`].filter(Boolean).join(', ');
  return `Roll call ${v.yeas}–${v.nays}${extra ? ', ' + extra : ''}`;
}
function councilGrid(v) {
  if (!v || v.kind !== 'roll call') return '';
  const rows = Object.entries(v.votes).sort((a, b) => VORDER.indexOf(a[1]) - VORDER.indexOf(b[1]) || a[0].localeCompare(b[0]));
  const note = v.complete ? '' : `<p class="note">Partial: the minutes name only some councilors and the rest can't be confirmed from the attendance record.</p>`;
  return `<table><thead><tr><th>Councilor</th><th>Vote</th></tr></thead><tbody>
    ${rows.map(([n, x]) => `<tr><td>${esc(n)}</td><td class="v-${esc(x.split(' ')[0])}">${esc(x)}</td></tr>`).join('')}
    </tbody></table>${note}`;
}
function councilHtml(p) {
  const c = p.council;
  if (!c) {
    const covered = D.council_from && p.court >= 192;
    return `<div class="chamber"><b>City Council</b><span>${covered ? 'No matching council docket found.' : 'Council records before 2021 aren\'t available in Legistar.'}</span></div>`;
  }
  const how = c.match.method === 'manual' ? 'linked by hand' : `matched by title, score ${c.match.score}`;
  return `<div><div class="chamber"><b>City Council · <a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.docket)}</a></b>
    <span>${c.passed ? `Passed ${esc(c.passed)}` : 'Not passed'} · ${esc(voteLine(c.vote))}${c.minutes ? ` · <a href="${esc(c.minutes)}" target="_blank" rel="noopener">minutes</a>` : ''}<br><span class="note">${how}</span></span></div>
    ${councilGrid(c.vote)}</div>`;
}

function houseRollNote(p) {
  const h = p.floor && p.floor.House;
  if (!h || !h.roll_calls.length) return '';
  return `<p class="note">House roll-call votes by member aren't published through the Legislature's API; they appear in the House Journal for that date.</p>`;
}

function card(p) {
  const t = p.transmitter;
  const who = t ? `${esc(t.name)}${t.branch ? ` (${t.branch === 'House' ? 'Rep.' : 'Sen.'}${t.district ? ', ' + esc(t.district) : ''})` : ''}` : '—';
  const stageLine = p.status === 'Became law' ? esc(p.chapter || '') :
    p.replaced_by ? `${esc(p.stage_label)} as ${esc(p.replaced_by.bill)}` : esc(p.stage_label);
  const num = p.bill || p.docket || '';
  return `<details class="p">
  <summary>
    <div class="ptitle">${esc(p.short_title || p.title)}</div>
    <div class="psum">${p.summary_source === 'claude' ? '✦ ' : ''}${esc(p.summary)}</div>
    <div class="pmeta"><span class="cat">${esc(catLabel(p.category))}</span> · ${esc(num)} · ${esc(p.years)} · ${who}</div>
    <div class="pright"><span class="status ${stCls(p.status)}">${esc(p.status)}</span><span class="stage">${stageLine}</span></div>
  </summary>
  <div class="body">
    <dl class="kv">
      <dt>Official title</dt><dd>${esc(p.title)}</dd>
      <dt>Bill</dt><dd>${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(num)}</a>` : esc(num)}${p.bill && p.docket ? ` (docket ${esc(p.docket)})` : ''}</dd>
      ${p.replaced_by ? `<dt>Replaced by</dt><dd><a href="${esc(p.replaced_by.url)}" target="_blank" rel="noopener">${esc(p.replaced_by.bill)}</a>. The original bill: ${esc(p.own_stage_label)}</dd>` : ''}
      <dt>Transmitted by</dt><dd>${who}${t && t.in_delegation === false ? ' <span class="note">(not in Boston delegation)</span>' : ''}</dd>
      <dt>Filed</dt><dd>${esc(p.filed_date || '—')}</dd>
      <dt>Committee</dt><dd>${esc(p.committee || '—')}</dd>
      <dt>Latest action</dt><dd>${esc(p.last_action || '—')}${p.last_action_date ? ` <span class="note">(${esc(p.last_action_date)}, ${esc(p.last_action_branch)})</span>` : ''}</dd>
    </dl>
    ${councilHtml(p)}${floorHtml(p)}${rollHtml(p)}${houseRollNote(p)}
  </div>
</details>`;
}

function renderPetitions() {
  chips($('#sessions'), c => { state.court = c; renderPetitions(); }, state.court);
  const base = filtered(true);
  $('#tiles').innerHTML = STATUS.map(s => {
    const n = base.filter(p => p.status === s).length;
    return `<button class="tile${state.status===s?' on':''}" data-s="${s}"><b>${n}</b><span>${s}</span></button>`;
  }).join('');
  $('#tiles').querySelectorAll('.tile').forEach(b => b.onclick = () => { state.status = state.status === b.dataset.s ? null : b.dataset.s; renderPetitions(); });
  const ps = filtered(false);
  $('#count').textContent = `${ps.length} petition${ps.length === 1 ? '' : 's'}`;
  $('#list').innerHTML = ps.map(card).join('');
}

const names = [...new Set(D.petitions.map(p => p.transmitter && p.transmitter.name).filter(Boolean))].sort();
$('#who').innerHTML += names.map(n => `<option>${esc(n)}</option>`).join('');
$('#who').onchange = e => { state.who = e.target.value; renderPetitions(); };
$('#cat').innerHTML += CATS.map(c => `<option value="${esc(c.key)}">${esc(c.label)} (${c.count})</option>`).join('');
$('#cat').onchange = e => { state.cat = e.target.value; renderPetitions(); };
$('#q').oninput = e => { state.q = e.target.value; renderPetitions(); };

let dCourt = D.sessions[0].court;
function renderDelegation() {
  const sel = D.sessions.find(s => s.court === dCourt);
  $('#dsessions').innerHTML = D.sessions.map(s => `<button class="chip${s.court===dCourt?' on':''}" data-c="${s.court}">${s.years}</button>`).join('');
  $('#dsessions').querySelectorAll('.chip').forEach(b => b.onclick = () => { dCourt = +b.dataset.c; renderDelegation(); });
  const ps = D.petitions.filter(p => p.court === dCourt);
  $('#dtable').innerHTML = sel.delegation.map(m => {
    const mine = ps.filter(p => p.transmitter && p.transmitter.code === m.code);
    const laws = mine.filter(p => p.status === 'Became law').length;
    const votes = [];
    ps.forEach(p => (p.roll_calls || []).forEach(rc => rc.delegation.forEach(v => {
      if (v.code === m.code) votes.push(`<span class="v-${esc(v.vote.split(' ')[0])}">${esc(v.vote)}</span> on ${esc(p.bill)}`);
    })));
    return `<tr><td>${esc(m.name)}<div class="note">${m.branch === 'House' ? 'Representative' : 'Senator'} · ${esc(m.party || '')}</div></td><td>${esc(m.district)}</td>
      <td>${mine.length ? `<a href="#" data-who="${esc(m.name)}" data-c="${dCourt}">${mine.length}</a>` : '0'}</td><td>${laws}</td><td>${votes.join('<br>') || '<span class="note">none</span>'}</td></tr>`;
  }).join('');
  $('#dtable').querySelectorAll('a[data-who]').forEach(a => a.onclick = e => {
    e.preventDefault(); state.who = a.dataset.who; state.court = +a.dataset.c; state.status = null;
    $('#who').value = state.who; show('petitions'); renderPetitions();
  });
}

const byKey = Object.fromEntries(D.petitions.map(p => [`${p.court}/${p.bill || p.docket}`, p]));
const cstate = { q: '', f: '' };
function renderCouncil() {
  const all = D.council_petitions || [];
  $('#cnote').textContent = D.council_from
    ? `City Council home rule petitions since ${D.council_from.slice(0, 4)}, from the Council's Legistar records and the City Clerk's minutes. Roll calls name only the smaller side; the rest is filled in from the roster and attendance when the numbers add up exactly.`
    : 'City Council records are only available for Boston.';
  const q = cstate.q.toLowerCase();
  const rows = all.filter(c =>
    (!q || [c.docket, c.title].join(' ').toLowerCase().includes(q)) &&
    (!cstate.f || (cstate.f === 'split' && c.vote && c.vote.nays > 0)
               || (cstate.f === 'unfiled' && c.passed && !c.state_bills.length)
               || (cstate.f === 'notpassed' && !c.passed)));
  $('#ccount').textContent = `${rows.length} docket${rows.length === 1 ? '' : 's'}`;
  $('#ctable').innerHTML = rows.map(c => {
    const v = c.vote;
    const nays = v && v.kind === 'roll call' ? Object.entries(v.votes).filter(([, x]) => x === 'Nay').map(([n]) => n) : [];
    const state = c.state_bills.length ? c.state_bills.map(k => {
      const p = byKey[k]; if (!p) return esc(k);
      return `<a href="#" data-key="${esc(k)}">${esc(p.bill || p.docket)}</a> <span class="status ${stCls(p.status)}">${esc(p.status)}</span>`;
    }).join('<br>') : (c.passed ? '<span class="note">Not found at the State House</span>' : '<span class="note">—</span>');
    return `<tr><td class="num"><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.docket)}</a></td>
      <td>${esc(c.title)}<div class="note">${esc(catLabel(c.category))} · Filed ${esc(c.filed || '—')} · ${esc(c.council_status || '')}</div></td>
      <td>${c.passed ? esc(c.passed) + '<br>' : ''}${esc(c.passed ? voteLine(v) : 'Not passed')}${nays.length ? `<div class="note">Nay: ${nays.map(esc).join(', ')}</div>` : ''}</td>
      <td>${state}</td></tr>`;
  }).join('');
  $('#ctable').querySelectorAll('a[data-key]').forEach(a => a.onclick = e => {
    e.preventDefault(); const p = byKey[a.dataset.key];
    Object.assign(state, { court: p.court, status: null, who: '', q: p.bill || p.docket });
    $('#q').value = state.q; $('#who').value = ''; show('petitions'); renderPetitions();
    const d = document.querySelector('details.p'); if (d) d.open = true;
  });
}
$('#cq').oninput = e => { cstate.q = e.target.value; renderCouncil(); };
$('#cfilter').onchange = e => { cstate.f = e.target.value; renderCouncil(); };

const KIND = { new_petition: 'New at the State House', status: 'Status', stage: 'Progress', council_link: 'Linked',
  removed: 'Removed', new_council: 'New at City Council', council_passed: 'City Council vote', session: 'New session' };
function renderUpdates() {
  if (!changes.length) {
    $('#changes').innerHTML = '<p class="note">No changes recorded yet. Each daily update compares against the previous one, so changes appear from the second run on.</p>';
  } else {
    const byDate = {};
    changes.forEach(c => (byDate[c.date] = byDate[c.date] || []).push(c));
    $('#changes').innerHTML = Object.entries(byDate).map(([d, cs]) => `<h3 class="note">${esc(d)}</h3>
      <div class="wrap"><table><tbody>${cs.map(c => `<tr><td style="width:170px"><span class="note">${esc(KIND[c.kind] || c.kind)}</span></td>
        <td>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a>` : esc(c.title)}<div class="note">${esc(c.text)}</div></td></tr>`).join('')}</tbody></table></div>`).join('');
  }
  const today = new Date().toISOString().slice(0, 10);
  $('#calendar').innerHTML = (D.calendar || []).map(e => `<tr${e.date < today ? ' style="opacity:.6"' : ''}>
    <td class="num">${esc(e.date)}</td><td>${esc(e.title)}</td><td>${esc(e.detail)}</td></tr>`).join('');
}

function show(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.tab === tab));
  ['petitions', 'council', 'delegation', 'updates'].forEach(id => { $('#' + id).hidden = tab !== id; });
  if (tab === 'delegation') renderDelegation();
  if (tab === 'council') renderCouncil();
  if (tab === 'updates') renderUpdates();
}
document.querySelectorAll('.tab').forEach(t => t.onclick = () => show(t.dataset.tab));
const rl = document.getElementById('recentlink');
if (rl) rl.onclick = e => { e.preventDefault(); show('updates'); };
renderPetitions();
</script>
</body></html>
"""
