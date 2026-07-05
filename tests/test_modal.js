// Full-modal integration tests under jsdom: the REAL openEventModal /
// openEventView / openTaskView with a stubbed API — not isolated widget
// fragments. This is the harness that would have caught the 1.6.0
// stale-CSS-adjacent regressions.
//   NODE_PATH=... node tests/test_modal.js
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '..');
const dom = new JSDOM(`<!doctype html><body>
  <div id="toasts"></div>
  <div id="modal-overlay" class="modal-overlay hidden">
    <div class="modal">
      <div class="modal-hd"><span id="modal-title"></span>
        <button id="modal-x">✕</button></div>
      <div class="modal-bd" id="modal-bd"></div>
    </div>
  </div></body>`, { url: 'http://localhost/day' });
const { window } = dom;
const { document } = window;

// ── API stub: capture writes, serve minimal reads ─────────────────────────────
const captured = { puts: [], posts: [], deletes: [] };
window.fetch = async (rawUrl, opts = {}) => {
  const url = String((rawUrl && rawUrl.url) || rawUrl);
  const method = (opts.method || (rawUrl && rawUrl.method) || 'GET').toUpperCase();
  const body = opts.body ? JSON.parse(opts.body) : null;
  let data = {};
  if (method === 'GET' && url.includes('/contexts')) {
    data = [{ id: 1, full_path: 'inbox', color: '#888' }];
  } else if (method === 'PUT') {
    captured.puts.push({ url, body }); data = { uuid: 'u1', ...body };
  } else if (method === 'POST') {
    captured.posts.push({ url, body }); data = { uuid: 'new1', ...body };
  } else if (method === 'DELETE') {
    captured.deletes.push({ url }); data = { deleted: 'u1' };
  } else if (method === 'GET') {
    data = [];
  }
  return { ok: true, status: 200, json: async () => data,
           text: async () => JSON.stringify(data) };
};
window.requestAnimationFrame = fn => setTimeout(fn, 0);
window.confirm = () => true;
const lsStub = { getItem: () => null, setItem: () => {}, removeItem: () => {} };

// ── Evaluate shared.js in the jsdom window ────────────────────────────────────
let src = fs.readFileSync(path.join(ROOT, 'static/js/shared.js'), 'utf8')
  .replace(/^export default /gm, '')
  .replace(/^export /gm, '');
const sandbox = new Function(
  'window', 'document', 'location', 'localStorage', 'fetch',
  'requestAnimationFrame', 'confirm', 'Event', 'Node',
  src + `;
  return { openEventModal, openEventView, openTaskView, openTransferModal, openModal, closeModal };
`);
const S = sandbox(window, document, window.location, lsStub,
  window.fetch, window.requestAnimationFrame, window.confirm,
  window.Event, window.Node);

const $ = id => document.getElementById(id);
const tick = (n = 3) => new Promise(r => {
  let i = 0; const step = () => (++i >= n ? r() : setTimeout(step, 0));
  setTimeout(step, 0);
});
// The scope chooser is a fixed-position overlay appended to <body>,
// identified by containing a Cancel button (wiki-autocomplete and other
// fixed elements don't have one).
const overlay = () => [...document.body.children].find(
  el => el.style && el.style.position === 'fixed' && el !== $('modal-overlay')
        && [...el.querySelectorAll('button')].some(b => b.textContent === 'Cancel'));
const overlayButton = label => [...overlay().querySelectorAll('button')]
  .find(b => b.textContent === label);

let n = 0;
function check(name, cond) {
  if (!cond) { console.error(`FAIL: ${name}`); process.exit(1); }
  n++; console.log(`  ok  ${name}`);
}

const weeklyOcc = {
  uuid: 'u1', title: 'PT', description: '', context_id: 1, all_day: 0,
  start_at: '2026-07-14T15:00:00', end_at: '2026-07-14T16:00:00',
  recurrence: 'FREQ=WEEKLY', is_occurrence: 1,
  master_start_at: '2026-07-07T15:00:00',
};

(async () => {
  // ── A. weekday toggles inside the REAL modal ─────────────────────────
  await S.openEventModal({}, () => {});
  $('f-sd').value = '2026-07-07';                       // a Tuesday
  $('f-recur-unit').value = 'week';
  $('f-recur-unit').dispatchEvent(new window.Event('change'));
  check('modal: weekday toggles visible for Weekly',
        $('f-recur-wd-wrap').style.display !== 'none');
  check('modal: start weekday auto-selected',
        $('f-recur-wd-TU').classList.contains('on'));
  $('f-recur-wd-TH').click();
  check('modal: clicking a day toggles its .on class',
        $('f-recur-wd-TH').classList.contains('on'));
  $('f-recur-wd-TH').click();
  check('modal: clicking again untoggles',
        !$('f-recur-wd-TH').classList.contains('on'));
  S.closeModal();

  // ── B. save-time fallback chooser (recurring, no preset) ─────────────
  await S.openEventModal(weeklyOcc, () => {});
  check('fallback: no premature overlay', !overlay());
  $('f-save').click();
  await tick();
  check('fallback: chooser overlay appears on Save', !!overlay());
  check('fallback: offers the three scopes',
        !!overlayButton('Only this occurrence')
        && !!overlayButton('This and all future occurrences')
        && !!overlayButton('All occurrences'));
  overlayButton('Only this occurrence').click();
  await tick(6);
  check('fallback: PUT carries scope + original occurrence_at',
        captured.puts.length === 1
        && captured.puts[0].body.scope === 'occurrence'
        && captured.puts[0].body.occurrence_at === '2026-07-14T15:00:00');
  check('fallback: chooser overlay removed after choice', !overlay());

  // ── C. preset flow (scope decided up front) ──────────────────────────
  captured.puts.length = 0;
  await S.openEventModal(weeklyOcc, () => {}, () => {}, 'future');
  check('preset: title announces the scope',
        $('modal-title').textContent.includes('this and all future'));
  check('preset: recurrence section visible for future',
        $('f-recur-sect').style.display !== 'none');
  $('f-save').click();
  await tick(6);
  check('preset: saves without asking again',
        !overlay() && captured.puts.length === 1
        && captured.puts[0].body.scope === 'future'
        && captured.puts[0].body.occurrence_at === '2026-07-14T15:00:00');

  captured.puts.length = 0;
  await S.openEventModal(weeklyOcc, () => {}, () => {}, 'occurrence');
  check('preset occurrence: recurrence section hidden',
        $('f-recur-sect').style.display === 'none');
  check('preset occurrence: note explains the series is unchanged',
        $('modal-bd').textContent.includes('series and its rule are unchanged'));
  $('f-save').click();
  await tick(6);
  check('preset occurrence: PUT scope=occurrence',
        captured.puts[0].body.scope === 'occurrence');

  // preset delete skips the chooser, uses confirm
  captured.deletes.length = 0;
  await S.openEventModal(weeklyOcc, () => {}, () => {}, 'all');
  $('f-del').click();
  await tick(6);
  check('preset delete: DELETE with scope=all, no chooser',
        !overlay() && captured.deletes.length === 1
        && captured.deletes[0].url.includes('scope=all')
        && captured.deletes[0].url.includes(
             encodeURIComponent('2026-07-14T15:00:00')));

  // ── D. view card asks the scope when Edit is clicked ─────────────────
  captured.puts.length = 0;
  S.openEventView(weeklyOcc, () => {});
  check('view: card shows humanized rule',
        $('modal-bd').textContent.includes('Repeats weekly on Tuesday'));
  $('v-edit').click();
  await tick();
  check('view→edit: scope chooser appears BEFORE the editor', !!overlay());
  overlayButton('This and all future occurrences').click();
  await tick(6);
  check('view→edit: editor opens with the chosen scope in the title',
        $('modal-title').textContent === 'Edit event — this and all future occurrences');
  $('f-save').click();
  await tick(6);
  check('view→edit: save carries the chosen scope without re-asking',
        !overlay() && captured.puts[0].body.scope === 'future');

  // cancelling the scope question keeps the view card
  S.openEventView(weeklyOcc, () => {});
  $('v-edit').click();
  await tick();
  [...overlay().querySelectorAll('button')]
    .find(b => b.textContent === 'Cancel').click();
  await tick();
  check('view→edit: cancelling the scope question keeps the view card',
        !!$('v-edit') && !overlay());
  S.closeModal();

  // non-recurring event goes straight to the editor
  S.openEventView({ uuid: 'u2', title: 'Once', all_day: 0,
                    start_at: '2026-07-21T11:00:00',
                    end_at: '2026-07-21T12:00:00' }, () => {});
  $('v-edit').click();
  await tick(6);
  check('view→edit: plain event opens editor with no scope question',
        !overlay() && $('modal-title').textContent === 'Edit event');
  S.closeModal();

  // ── E. task view card ─────────────────────────────────────────────────
  S.openTaskView({ uuid: 't1', title: 'Send invoice', status: 'active',
                   importance: 'high', effort: 'low',
                   due_at: '2026-07-10T00:00:00',
                   recurrence: 'week:1:moveable',
                   context_path: 'work', description: 'Q3 items' }, () => {});
  const bd = $('modal-bd').textContent;
  check('task view: shows status, due, context, description',
        bd.includes('active') && bd.includes('2026-07-10')
        && bd.includes('work') && bd.includes('Q3 items'));
  check('task view: humanizes moveable recurrence',
        bd.includes('Repeats weekly') && bd.includes('moveable'));
  $('v-edit').click();
  await tick(6);
  check('task view: Edit opens the task editor',
        $('modal-title').textContent.toLowerCase().includes('task'));
  S.closeModal();

  // ── F. transfer dialog ────────────────────────────────────────────────
  await S.openTransferModal();
  check('transfer: entry offers Export and Import',
        !!$('tx-export') && !!$('tx-import'));
  $('tx-export').click();
  await tick(6);
  check('transfer: export form has What + Context + Download',
        !!$('tx-what') && !!$('tx-ctx') && !!$('tx-go')
        && $('modal-title').textContent === 'Export');
  $('tx-what').value = 'journal';
  $('tx-what').dispatchEvent(new window.Event('change'));
  check('transfer: context selector hidden for journal export',
        $('tx-ctx-wrap').style.display === 'none');
  $('tx-back').click();
  await tick(6);
  check('transfer: Back returns to the chooser', !!$('tx-export'));
  $('tx-import').click();
  await tick(6);
  check('transfer: import form has file input and calendar options',
        !!$('tx-file') && !!$('tx-cats') && !!$('tx-ctx'));
  $('tx-what').value = 'notes';
  $('tx-what').dispatchEvent(new window.Event('change'));
  check('transfer: calendar options hidden for notes import',
        $('tx-cal-opts').style.display === 'none');
  S.closeModal();

  console.log(`\nAll ${n} full-modal tests passed.`);
})().catch(e => { console.error('HARNESS ERROR:', e); process.exit(1); });
