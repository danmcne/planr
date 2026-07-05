// TRUE end-to-end: the real openEventView/openEventModal in jsdom, with
// fetch forwarded to a LIVE planr server — the full pipeline the isolated
// suites can't see. Started by tests/run_e2e.sh with BASE set.
//   BASE=http://127.0.0.1:PORT NODE_PATH=... node tests/test_e2e.js
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const BASE = process.env.BASE;
if (!BASE) { console.error('BASE env var required'); process.exit(2); }
const ROOT = path.resolve(__dirname, '..');

const dom = new JSDOM(`<!doctype html><body>
  <div id="toasts"></div>
  <div id="modal-overlay" class="hidden"><div>
    <span id="modal-title"></span><button id="modal-x">✕</button>
    <div id="modal-bd"></div></div></div></body>`,
  { url: 'http://localhost/day' });
const { window } = dom;
const { document } = window;

// Forward the app's fetch to the live server (the app may hand over either
// bare paths or URLs already resolved against jsdom's localhost origin).
window.fetch = (u, opts) => {
  const raw = String((u && u.url) || u);
  const url = raw.startsWith('http')
    ? raw.replace(/^https?:\/\/localhost(:\d+)?/, BASE)
    : BASE + raw;
  return globalThis.fetch(url, opts);
};
window.requestAnimationFrame = fn => setTimeout(fn, 0);
window.confirm = () => true;

let src = fs.readFileSync(path.join(ROOT, 'static/js/shared.js'), 'utf8')
  .replace(/^export default /gm, '').replace(/^export /gm, '');
const S = new Function(
  'window', 'document', 'location', 'localStorage', 'fetch',
  'requestAnimationFrame', 'confirm', 'Event', 'Node',
  src + '; return { openEventView, openEventModal, closeModal };')(
  window, document, window.location,
  { getItem: () => null, setItem: () => {} },
  window.fetch, window.requestAnimationFrame, window.confirm,
  window.Event, window.Node);

const $ = id => document.getElementById(id);
const tick = (n = 4) => new Promise(r => {
  let i = 0; const step = () => (++i >= n ? r() : setImmediate(step));
  setImmediate(step);
});
const settle = async (ms = 150) => new Promise(r => setTimeout(r, ms));
const overlay = () => [...document.body.children].find(
  el => el.style && el.style.position === 'fixed'
        && [...el.querySelectorAll('button')].some(b => b.textContent === 'Cancel'));
const overlayButton = label => [...overlay().querySelectorAll('button')]
  .find(b => b.textContent === label);

async function api(method, p, body) {
  const r = await globalThis.fetch(BASE + '/api' + p, {
    method, headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined });
  return r.json();
}
const dayRows = async ds =>
  (await api('GET', `/api/calendar/day?date_str=${ds}`.replace('/api/api', '/api')))
    .timed_events;

let n = 0;
function check(name, cond) {
  if (!cond) { console.error(`FAIL: ${name}`); process.exit(1); }
  n++; console.log(`  ok  ${name}`);
}

// Drive the full UI edit flow on a calendar row: view card → Edit →
// choose scope → retitle → Save → wait for the round trip.
async function uiEdit(row, scopeLabel, newTitle, times) {
  S.openEventView(row, () => {});
  $('v-edit').click();
  await tick();
  if (scopeLabel) {
    if (!overlay()) { console.error(`no scope chooser for "${scopeLabel}"`); process.exit(1); }
    overlayButton(scopeLabel).click();
  }
  await settle();                       // editor fetches contexts
  $('f-title').value = newTitle;
  if (times) { $('f-st').value = times[0]; $('f-et').value = times[1]; }
  $('f-save').click();
  await settle();                       // PUT round trip
  S.closeModal();
}

(async () => {
  const day = async ds => {
    const r = await globalThis.fetch(`${BASE}/api/calendar/day?date_str=${ds}`);
    return (await r.json()).timed_events;
  };

  // The user's exact sequence, driven entirely through the UI layer.
  const post = await globalThis.fetch(`${BASE}/api/events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'PT', start_at: '2026-07-07T15:00:00',
      end_at: '2026-07-07T16:00:00', recurrence: 'FREQ=WEEKLY' }) });
  const master = await post.json();

  // 1. one-off edit of the Jul 14 occurrence
  let rows = await day('2026-07-14');
  await uiEdit(rows[0], 'Only this occurrence', 'Special');
  rows = await day('2026-07-14');
  check('UI one-off edit produced the override',
        rows.length === 1 && rows[0].title === 'Special'
        && rows[0].uuid !== master.uuid);
  const overrideUuid = rows[0].uuid;

  // 2. this-and-future at Jul 28
  rows = await day('2026-07-28');
  await uiEdit(rows[0], 'This and all future occurrences', 'Later');
  rows = await day('2026-07-28');
  check('UI future split renamed from the split point',
        rows.length === 1 && rows[0].title === 'Later');
  check('…without touching earlier occurrences',
        (await day('2026-07-21'))[0].title === 'PT');
  const segUuid = rows[0].uuid;
  check('split created a distinct segment row',
        segUuid !== master.uuid && segUuid !== overrideUuid);

  // 3. edit ALL from a SEGMENT occurrence (Aug 4)
  rows = await day('2026-08-04');
  check('Aug 4 row belongs to the segment', rows[0].uuid === segUuid);
  await uiEdit(rows[0], 'All occurrences', 'Renamed');

  // 4. the reported assertion — RESET semantics: edit-all removes all
  // other edits. The override row is gone; its slot rejoins the grid.
  const ovRes = await globalThis.fetch(`${BASE}/api/events/${overrideUuid}`);
  check('edit-all from the segment REMOVED the one-off override', !ovRes.ok);
  const jul14 = await day('2026-07-14');
  check('…its slot rejoined the grid with the new values',
        jul14.length === 1 && jul14[0].title === 'Renamed'
        && jul14[0].uuid !== overrideUuid);
  check('…and the master occurrences', (await day('2026-07-21'))[0].title === 'Renamed');
  const aug4 = await day('2026-08-04');
  check('…and the former segment territory (segment collapsed away)',
        aug4[0].title === 'Renamed' && aug4[0].uuid !== segUuid);
  check('split boundary intact (one event on Jul 28)',
        (await day('2026-07-28')).length === 1);

  // ── the reported scenario, time-based: one-off TIME edit, then a
  // time-changing edit-all must reach and UNIFY the override ──────────
  const p2 = await globalThis.fetch(`${BASE}/api/events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'Gym', start_at: '2026-09-01T15:00:00',
      end_at: '2026-09-01T16:00:00', recurrence: 'FREQ=WEEKLY' }) });
  await p2.json();

  // (the first series recurs into September too — select by title)
  const gym = rows2 => rows2.filter(e => e.title.startsWith('Gym'));

  let r2 = gym(await day('2026-09-08'));
  await uiEdit(r2[0], 'Only this occurrence', 'Gym (moved)', ['16:00', '17:00']);
  r2 = gym(await day('2026-09-08'));
  check('time-based one-off edit landed at 16:00',
        r2.length === 1 && r2[0].seg_start_at === '2026-09-08T16:00:00');
  const ov2 = r2[0].uuid;

  r2 = gym(await day('2026-09-15'));
  await uiEdit(r2[0], 'All occurrences', 'Gym early', ['09:00', '10:00']);
  check('edit-all unified the series time',
        gym(await day('2026-09-15'))[0].seg_start_at === '2026-09-15T09:00:00'
        && gym(await day('2026-09-01'))[0].seg_start_at === '2026-09-01T09:00:00');
  r2 = gym(await day('2026-09-08'));
  check('…and the one-off was reset onto the grid at the new time',
        r2.length === 1 && r2[0].uuid !== ov2
        && r2[0].seg_start_at === '2026-09-08T09:00:00'
        && r2[0].title === 'Gym early');
  const ov2Res = await globalThis.fetch(`${BASE}/api/events/${ov2}`);
  check('…the override row itself is gone', !ov2Res.ok);

  console.log(`\nAll ${n} UI↔server end-to-end tests passed.`);
  process.exit(0);
})().catch(e => { console.error('E2E ERROR:', e); process.exit(1); });
