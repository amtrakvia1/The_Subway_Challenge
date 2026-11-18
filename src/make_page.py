#!/usr/bin/env python3
"""Build the phone run sheet (one self-contained HTML page) from a route JSON made by report.py.
usage: make_page.py out/route_safe.json out/run_sheet.html ["note shown under the title"]"""
import sys, json
route = json.load(open(sys.argv[1]))
note = sys.argv[3] if len(sys.argv) > 3 else ''
for L in route['legs']:
    L.pop('trip_id', None)
page = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Subway Record Run Sheet</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* layout: sticky status bar on top, one column of step cards, current step highlighted */
:root{
  --bg:#eef0f3; --card:#ffffff; --ink:#14181f; --muted:#5b6472; --line:#d5d9e0; --accent:#0b3fa8;
  --good:#12744a; --warn:#a85f00; --crit:#b3261e; --warnbg:#fff1d6; --critbg:#fde3e0; --goodbg:#dcf3e7;
  --display:"Barlow Condensed","Arial Narrow",Arial,sans-serif; --body:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --bg:#0e1217; --card:#171c24; --ink:#e9edf3; --muted:#98a2b1; --line:#2a313c; --accent:#7ea8ff;
  --good:#5fd39a; --warn:#f0b354; --crit:#ff8a80; --warnbg:#3a2c0d; --critbg:#40191a; --goodbg:#12301f; color-scheme:dark; } }
:root[data-theme="dark"]{
  --bg:#0e1217; --card:#171c24; --ink:#e9edf3; --muted:#98a2b1; --line:#2a313c; --accent:#7ea8ff;
  --good:#5fd39a; --warn:#f0b354; --crit:#ff8a80; --warnbg:#3a2c0d; --critbg:#40191a; --goodbg:#12301f; color-scheme:dark; }
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--bg);color:var(--ink);font-family:var(--body);font-size:15px;line-height:1.4;-webkit-text-size-adjust:100%}
.wrap{max-width:720px;margin:0 auto;padding:0 16px 80px}
header.top{padding:18px 0 10px}
h1{font-family:var(--display);font-weight:700;font-size:34px;line-height:1.05;margin:0;letter-spacing:.2px;text-wrap:balance}
.sub{color:var(--muted);margin:6px 0 0;max-width:62ch}
.facts{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:14px 0 4px}
.fact{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.fact b{display:block;font-family:var(--mono);font-weight:500;font-size:17px;font-variant-numeric:tabular-nums}
.fact span{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
@media (max-width:480px){.facts{grid-template-columns:repeat(2,1fr)}}
.bar{position:sticky;top:0;z-index:5;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line)}
.status{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.clock{font-family:var(--mono);font-size:20px;font-variant-numeric:tabular-nums}
.delta{font-family:var(--display);font-weight:600;font-size:18px;padding:2px 10px;border-radius:999px;background:var(--card);border:1px solid var(--line)}
.delta.ahead{background:var(--goodbg);color:var(--good);border-color:transparent}
.delta.behind{background:var(--critbg);color:var(--crit);border-color:transparent}
.grow{flex:1}
button{font:inherit;font-weight:600;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:8px 12px;cursor:pointer}
button.primary{background:var(--accent);color:#fff;border-color:transparent}
:root[data-theme="dark"] button.primary{color:#0e1217}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]) button.primary{color:#0e1217}}
button:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.tools{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
.tools button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
ol.steps{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-direction:column;gap:8px}
li.step{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--line);border-radius:8px;padding:10px 12px}
li.step.cur{border-color:var(--accent);box-shadow:0 0 0 2px color-mix(in srgb,var(--accent) 25%,transparent)}
li.step.done{opacity:.55}
li.step.risk-warn{border-left-color:var(--warn)} li.step.risk-crit{border-left-color:var(--crit)}
.row{display:flex;gap:10px;align-items:flex-start}
.num{font-family:var(--mono);font-size:12px;color:var(--muted);min-width:26px;padding-top:6px}
.bullet{flex:none;width:34px;height:34px;border-radius:50%;display:grid;place-items:center;font-family:var(--display);font-weight:700;font-size:20px;color:#fff}
.bullet.sq{border-radius:7px;background:var(--ink);color:var(--bg);font-size:13px;letter-spacing:.04em}
.main{flex:1;min-width:0}
.what{font-weight:600}
.what small{font-weight:400;color:var(--muted)}
.times{font-family:var(--mono);font-size:13.5px;font-variant-numeric:tabular-nums;color:var(--muted);margin-top:2px}
.times b{color:var(--ink);font-weight:500}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.chip{font-size:12px;padding:2px 8px;border-radius:999px;background:var(--bg);border:1px solid var(--line);white-space:nowrap}
.chip.warn{background:var(--warnbg);color:var(--warn);border-color:transparent}
.chip.crit{background:var(--critbg);color:var(--crit);border-color:transparent}
.chip.good{background:var(--goodbg);color:var(--good);border-color:transparent}
details{margin-top:6px} summary{cursor:pointer;color:var(--accent);font-size:13px}
.stops{font-family:var(--mono);font-size:12.5px;color:var(--muted);margin:6px 0 0;padding:0;list-style:none;columns:2;column-gap:16px}
.stops li{break-inside:avoid}
.pbbtn{margin-top:8px;width:100%;text-align:left;font-weight:500;font-size:13.5px;border-color:var(--crit);color:var(--crit);background:transparent}
.hide{display:none}
.legend{color:var(--muted);font-size:13px;margin:10px 0 0;max-width:65ch}
@media (prefers-reduced-motion:no-preference){li.step{transition:opacity .2s}}
</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <h1>Subway Record Run Sheet</h1>
  <p class="sub" id="sub"></p>
  <div class="facts" id="facts"></div>
</header>
<div class="bar">
  <div class="status">
    <span class="clock" id="clock">--:--:--</span>
    <span class="delta" id="delta">not started</span>
    <span class="grow"></span>
    <button class="primary" id="doneBtn" type="button">Done: step 1</button>
  </div>
  <div class="tools">
    <button type="button" id="riskBtn" aria-pressed="false">Risky connections only</button>
    <button type="button" id="jumpBtn">Jump to current</button>
    <button type="button" id="undoBtn">Undo</button>
    <button type="button" id="resetBtn">Reset</button>
    <button type="button" id="mainBtn" class="hide">Back to main plan</button>
  </div>
</div>
<p class="legend">Tap <b>Done</b> when a step finishes (doors open at the last stop, or you reach the next platform). The pill shows minutes ahead of or behind plan. <b>Margin</b> is spare time before the train leaves. <b>If missed</b> is how much later the whole run finishes if you miss that train and keep the same order. Where a better re-ordered route exists, a red <b>Plan B</b> button swaps the rest of the sheet to it.</p>
<ol class="steps" id="steps"></ol>
</div>
<script>
const ROUTE = __DATA__;
const NOTE = __NOTE__;
const COLORS = {'1':'#d82c26','2':'#d82c26','3':'#d82c26','4':'#00843a','5':'#00843a','6':'#00843a','6X':'#00843a','7':'#a22e9b','7X':'#a22e9b',
  'A':'#0b3fa8','C':'#0b3fa8','E':'#0b3fa8','B':'#e8590c','D':'#e8590c','F':'#e8590c','FX':'#e8590c','M':'#e8590c','G':'#4f9e2f',
  'J':'#8a5a2b','Z':'#8a5a2b','L':'#7d8086','N':'#c79a00','Q':'#c79a00','R':'#c79a00','W':'#c79a00','GS':'#6b6e73','FS':'#6b6e73','H':'#6b6e73'};
const LABEL = {'GS':'S','FS':'S','H':'S','6X':'6','7X':'7','FX':'F'};
const S = ROUTE.summary, PLANB = {}; (ROUTE.planb || []).forEach(b => { PLANB[b.step] = b; });
let legs = ROUTE.legs;
const pad = n => String(n).padStart(2,'0');
const hms = t => { t = ((t % 86400) + 86400) % 86400; return pad(Math.floor(t/3600)) + ':' + pad(Math.floor(t%3600/60)) + ':' + pad(Math.floor(t%60)); };
const hm = t => hms(t).slice(0,5);
const mins = s => (s>=0?'+':'−') + Math.round(Math.abs(s)/60) + ' min';
let state = {done: [], plan: -1};   // done[i] = actual second when step i finished; plan = step whose Plan B is active (-1 = main)
const KEY = 'subway-run-sheet-' + S.start + '-' + S.duration;
try { const v = JSON.parse(localStorage.getItem(KEY)); if (v && Array.isArray(v.done)) state = v; } catch (e) {}
function applyPlan(){ legs = (state.plan >= 0 && PLANB[state.plan]) ? ROUTE.legs.slice(0, state.plan).concat(PLANB[state.plan].legs) : ROUTE.legs; }
applyPlan();
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} };
let riskOnly = false;

function riskOf(L){ if (L.kind !== 'ride' || L.miss_cost == null) return ''; const c = L.miss_cost < 0 ? 1e9 : L.miss_cost;
  const tight = L.margin != null && L.margin <= 120; if (c >= 1200 && tight) return 'crit'; if (c >= 600 && (L.margin == null || L.margin <= 240)) return 'warn'; return ''; }

document.getElementById('sub').textContent = 'Start ' + hm(S.start) + ' at ' + legs[0].from + '. Finish ' + hm(S.end) + ' at ' + legs[legs.length-1].to + '. ' + NOTE;
const facts = [[S.duration_hms,'planned time'], [mins(-S.beats_record_by).replace('+','+ ').replace('−','− '),'vs record 22:14:10'], [S.stations_visited + ' / ' + S.stations_total,'stations'], [S.run_miles_street + ' mi','running, ' + S.runs + ' runs']];
document.getElementById('facts').innerHTML = facts.map(f => '<div class="fact"><b>' + f[0] + '</b><span>' + f[1] + '</span></div>').join('');

const ol = document.getElementById('steps');
function render(){
  const cur = state.done.length;
  ol.innerHTML = '';
  legs.forEach((L, i) => {
    const li = document.createElement('li'); const rk = riskOf(L);
    li.className = 'step' + (i < cur ? ' done' : '') + (i === cur ? ' cur' : '') + (rk ? ' risk-' + rk : '');
    li.id = 'step' + i;
    if (riskOnly && !rk && i !== cur) li.classList.add('hide');
    let bullet, what, chips = '';
    if (L.kind === 'ride') {
      bullet = '<span class="bullet" style="background:' + (COLORS[L.route] || '#555') + '">' + (LABEL[L.route] || L.route) + '</span>';
      what = (L.dir === 'N' ? 'Northbound' : 'Southbound') + ' to ' + L.to + ' <small>from ' + L.from + '</small>';
      chips += '<span class="chip">' + L.nstops + ' stops' + (L.new != null ? ', ' + L.new + ' new' : '') + '</span>';
      if (L.margin != null) chips += '<span class="chip ' + (L.margin <= 60 ? 'crit' : L.margin <= 150 ? 'warn' : 'good') + '">margin ' + Math.floor(L.margin/60) + ':' + pad(L.margin%60) + '</span>';
      if (L.miss_cost != null && L.miss_cost !== 0) chips += '<span class="chip ' + (L.miss_cost < 0 || L.miss_cost >= 1200 ? 'crit' : L.miss_cost >= 600 ? 'warn' : '') + '">if missed ' + (L.miss_cost < 0 ? 'no way through' : mins(L.miss_cost)) + '</span>';
    } else if (L.kind === 'run') {
      bullet = '<span class="bullet sq">RUN</span>';
      what = 'Run ' + L.street_mi + ' mi to ' + L.to + ' <small>from ' + L.from + '</small>';
    } else {
      bullet = '<span class="bullet sq">' + (L.kind === 'cross' ? 'XP' : 'XFR') + '</span>';
      what = (L.kind === 'cross' ? 'Cross to the other platform at ' + L.from : 'Transfer to ' + L.to + ' <small>from ' + L.from + '</small>');
    }
    let delta = '';
    if (i < cur) { const d = state.done[i] - L.t1; delta = '<span class="chip ' + (d > 60 ? 'crit' : d < -60 ? 'good' : '') + '">actual ' + hm(state.done[i]) + ' (' + mins(d) + ')</span>'; }
    let pb = '';
    if (state.plan < 0 && i >= cur && PLANB[i]) { const b = PLANB[i];
      pb = '<button type="button" class="pbbtn" data-step="' + i + '">Missed it: switch to Plan B (' + (b.loss <= 0 ? 'no time lost' : 'finish ' + mins(b.loss)) + (b.keep_loss < 0 ? ', same order has no way through' : ', same order ' + mins(b.keep_loss)) + ')</button>'; }
    let stops = '';
    if (L.kind === 'ride' && L.stops.length > 2) stops = '<details><summary>Stops</summary><ul class="stops">' + L.stops.map(s => '<li>' + hm(s[1]) + ' ' + s[0] + '</li>').join('') + '</ul></details>';
    li.innerHTML = '<div class="row"><span class="num">' + (i+1) + '</span>' + bullet + '<div class="main"><div class="what">' + what + '</div>' +
      '<div class="times"><b>' + hms(L.t0) + '</b> → <b>' + hms(L.t1) + '</b></div><div class="chips">' + chips + delta + '</div>' + stops + '</div></div>';
    ol.appendChild(li);
  });
  ol.querySelectorAll('.pbbtn').forEach(b => b.addEventListener('click', () => { const i = +b.dataset.step; state.plan = i; state.done = state.done.slice(0, i); applyPlan(); save(); render(); jump(); }));
  const mb = document.getElementById('mainBtn'); mb.classList.toggle('hide', state.plan < 0);
  const btn = document.getElementById('doneBtn');
  btn.textContent = cur >= legs.length ? 'Finished' : 'Done: step ' + (cur + 1);
  btn.disabled = cur >= legs.length;
  tick();
}
function nowSec(){ const d = new Date(); let t = d.getHours()*3600 + d.getMinutes()*60 + d.getSeconds();
  // put "now" in the plan's day frame (plan times may run past 24:00)
  const mid = (S.start + S.end) / 2; while (t < mid - 43200) t += 86400; while (t > mid + 43200) t -= 86400; return t; }
function tick(){
  const t = nowSec(); document.getElementById('clock').textContent = hms(t);
  const el = document.getElementById('delta'); const cur = state.done.length;
  if (cur === 0) { el.textContent = 'not started'; el.className = 'delta'; return; }
  const d = state.done[cur-1] - legs[cur-1].t1;
  if (cur >= legs.length) { const total = state.done[cur-1] - (state.done[0] - (legs[0].t1 - legs[0].t0)); el.textContent = 'finished, ' + mins(d) + ' vs plan'; el.className = 'delta ' + (d <= 0 ? 'ahead' : 'behind'); return; }
  el.textContent = Math.abs(d) < 45 ? 'on plan' : (d < 0 ? Math.round(-d/60) + ' min ahead' : Math.round(d/60) + ' min behind');
  el.className = 'delta ' + (d <= 45 ? 'ahead' : 'behind');
}
function jump(){ const el = document.getElementById('step' + Math.min(state.done.length, legs.length-1)); if (el) el.scrollIntoView({block:'center'}); }
document.getElementById('doneBtn').addEventListener('click', () => { if (state.done.length < legs.length) { state.done.push(nowSec()); save(); render(); jump(); } });
document.getElementById('undoBtn').addEventListener('click', () => { state.done.pop(); save(); render(); });
let armed = 0;
document.getElementById('resetBtn').addEventListener('click', e => { if (Date.now() - armed < 4000) { state = {done: [], plan: -1}; applyPlan(); save(); render(); e.target.textContent = 'Reset'; armed = 0; } else { armed = Date.now(); e.target.textContent = 'Tap again to reset'; setTimeout(() => { e.target.textContent = 'Reset'; }, 4000); } });
document.getElementById('riskBtn').addEventListener('click', e => { riskOnly = !riskOnly; e.target.setAttribute('aria-pressed', riskOnly); render(); });
document.getElementById('jumpBtn').addEventListener('click', jump);
document.getElementById('mainBtn').addEventListener('click', () => { state.plan = -1; applyPlan(); save(); render(); });
render(); setInterval(tick, 1000);
</script>
</body>
</html>
'''
page = page.replace('__DATA__', json.dumps(route, separators=(',', ':'))).replace('__NOTE__', json.dumps(note))
open(sys.argv[2], 'w').write(page)
print('wrote', sys.argv[2], len(page) // 1024, 'KB')
