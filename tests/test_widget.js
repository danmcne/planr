// DOM-level test of the event recurrence widget (shared.js) under jsdom.
//   node tests/test_widget.js        (from the planr root; needs jsdom)
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '..');
const dom = new JSDOM('<!doctype html><body></body>', { url: 'http://localhost/' });
const { window } = dom;
const { document } = window;

// shared.js is an ES module with no imports — strip `export` and evaluate
// it in the jsdom window so the module-private widget functions are reachable.
let src = fs.readFileSync(path.join(ROOT, 'static/js/shared.js'), 'utf8')
  .replace(/^export default /gm, '')
  .replace(/^export /gm, '');
const sandbox = new Function('window', 'document', 'location', 'localStorage',
  src + `;
  return { _recurHTML, _initRecur, _getRecur, _parseRecur, _onOptions, _clampHint, humanizeRecur };
`);
const W = sandbox(window, document,
  window.location, { getItem: () => null, setItem: () => {} });

let n = 0;
function check(name, cond) {
  if (!cond) { console.error(`FAIL: ${name}`); process.exit(1); }
  n++; console.log(`  ok  ${name}`);
}

// Build a minimal event-modal fragment: start-date input + widget host.
function mount(recurrence, startDate) {
  document.body.innerHTML =
    `<input id="f-sd" value="${startDate}">` +
    `<div id="host">${W._recurHTML('f-recur', recurrence, false)}</div>`;
  W._initRecur('f-recur', false, 'f-sd');
}
const $ = id => document.getElementById(id);
function setUnit(u) {
  $('f-recur-unit').value = u;
  $('f-recur-unit').dispatchEvent(new window.Event('change'));
}
function setOn(v) {
  $('f-recur-on').value = v;
  $('f-recur-on').dispatchEvent(new window.Event('change'));
}
const onValues = () => [...$('f-recur-on').options].map(o => o.value);

// ── the reported gap: create "3rd Thursday" rules ────────────────────────────
// 2026-07-16 is the third Thursday of July.
mount('', '2026-07-16');
setUnit('month');
check('On select appears for Monthly',
      $('f-recur-on-wrap').style.display !== 'none');
check('options offer day-of-month and 3rd Thursday',
      onValues().includes('md') && onValues().includes('nth'));
setOn('nth');
check('monthly 3rd Thursday emits BYDAY=3TH',
      W._getRecur('f-recur', false, 'f-sd') === 'FREQ=MONTHLY;BYDAY=3TH');

setUnit('year');
setOn('nth');
check('yearly 3rd Thursday pins the month',
      W._getRecur('f-recur', false, 'f-sd') === 'FREQ=YEARLY;BYMONTH=7;BYDAY=3TH');

// interval carries through
$('f-recur-n').value = '2';
check('interval included when > 1',
      W._getRecur('f-recur', false, 'f-sd') === 'FREQ=YEARLY;INTERVAL=2;BYMONTH=7;BYDAY=3TH');

// ── no 5th weekday on offer ──────────────────────────────────────────────────
// 2026-09-29 is the fifth Tuesday of September (last week → 'last' offered).
mount('', '2026-09-29');
setUnit('month');
check('5th weekday not offered', !onValues().includes('nth'));
check('"last Tuesday" offered instead', onValues().includes('last'));
setOn('last');
check('last Tuesday emits BYDAY=-1TU',
      W._getRecur('f-recur', false, 'f-sd') === 'FREQ=MONTHLY;BYDAY=-1TU');

// 4th weekday is still offered (2026-07-28 = 4th Tuesday, also last week)
mount('', '2026-07-28');
setUnit('month');
check('4th weekday still offered alongside last',
      onValues().includes('nth') && onValues().includes('last'));

// ── day 29–31 clamps, with a warning ─────────────────────────────────────────
mount('', '2026-07-31');
setUnit('month');
check('day-31 monthly emits clamp rule',
      W._getRecur('f-recur', false, 'f-sd')
      === 'FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1');
check('clamp warning is visible',
      $('f-recur-hint').style.display !== 'none'
      && $('f-recur-hint').textContent.includes('last day'));

mount('', '2026-07-30');
setUnit('month');
check('day-30 monthly emits clamp rule',
      W._getRecur('f-recur', false, 'f-sd')
      === 'FREQ=MONTHLY;BYMONTHDAY=28,29,30;BYSETPOS=-1');

// Feb 29 yearly
mount('', '2028-02-29');
setUnit('year');
check('Feb-29 yearly emits leap clamp',
      W._getRecur('f-recur', false, 'f-sd')
      === 'FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=28,29;BYSETPOS=-1');
check('leap-year warning shown',
      $('f-recur-hint').textContent.includes('leap'));

// day ≤ 28 stays plain, no warning
mount('', '2026-07-14');
setUnit('month');
check('day-14 monthly stays plain FREQ=MONTHLY',
      W._getRecur('f-recur', false, 'f-sd') === 'FREQ=MONTHLY');
check('no warning for safe days', $('f-recur-hint').style.display === 'none');

// ── labels re-derive when the start date changes ─────────────────────────────
mount('', '2026-07-16');            // Thursday
setUnit('month'); setOn('nth');
$('f-sd').value = '2026-07-14';     // now a Tuesday
$('f-sd').dispatchEvent(new window.Event('change'));
check('weekday re-derived from new start date',
      W._getRecur('f-recur', false, 'f-sd') === 'FREQ=MONTHLY;BYDAY=2TU');

// ── prefill: stored rules select the right mode ──────────────────────────────
mount('FREQ=MONTHLY;BYDAY=3TH', '2026-07-16');
check('prefill selects nth mode', $('f-recur-on').value === 'nth');
mount('FREQ=MONTHLY;BYDAY=-1TU', '2026-09-29');
check('prefill selects last mode', $('f-recur-on').value === 'last');
mount('FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1', '2026-07-31');
check('clamp rule prefills as day-of-month with warning',
      $('f-recur-on').value === 'md'
      && $('f-recur-hint').style.display !== 'none');
mount('week:1', '2026-07-07');
check('legacy value prefills Weekly', $('f-recur-unit').value === 'week');

// tasks path untouched
document.body.innerHTML = `<div>${W._recurHTML('f-recur', 'week:2:moveable', true)}</div>`;
W._initRecur('f-recur', true);
check('task widget still emits legacy format',
      W._getRecur('f-recur', true) === 'week:2:moveable');

// ── multi-weekday weekly (1.6.0) ─────────────────────────────────────────────
mount('', '2026-07-07');            // a Tuesday
setUnit('week');
check('weekday toggles appear for Weekly',
      $('f-recur-wd-wrap').style.display !== 'none');
check('start weekday pre-selected',
      $('f-recur-wd-TU').classList.contains('on')
      && !$('f-recur-wd-TH').classList.contains('on'));
check('only start weekday → canonical plain FREQ=WEEKLY',
      W._getRecur('f-recur', false, 'f-sd') === 'FREQ=WEEKLY');
$('f-recur-wd-TH').click();
check('Tue+Thu emits BYDAY=TU,TH',
      W._getRecur('f-recur', false, 'f-sd') === 'FREQ=WEEKLY;BYDAY=TU,TH');
$('f-recur-wd-MO').click(); $('f-recur-wd-TU').click(); // MO on, TU off
$('f-recur-wd-WE').click(); $('f-recur-wd-TH').click(); // WE on, TH off
$('f-recur-wd-FR').click();
check('MWF emits BYDAY=MO,WE,FR (Monday-first order)',
      W._getRecur('f-recur', false, 'f-sd') === 'FREQ=WEEKLY;BYDAY=MO,WE,FR');
check('toggles hidden again for Monthly',
      (setUnit('month'), $('f-recur-wd-wrap').style.display === 'none'));

// stored BYDAY prefills the toggles
mount('FREQ=WEEKLY;BYDAY=TU,TH', '2026-07-07');
check('BYDAY prefills Tue and Thu toggles',
      $('f-recur-wd-TU').classList.contains('on')
      && $('f-recur-wd-TH').classList.contains('on')
      && !$('f-recur-wd-MO').classList.contains('on'));
check('prefilled multi-day round-trips',
      W._getRecur('f-recur', false, 'f-sd') === 'FREQ=WEEKLY;BYDAY=TU,TH');

// ── humanizeRecur ────────────────────────────────────────────────────────────
const H = W.humanizeRecur;
check('humanize: plain weekly names the weekday',
      H('FREQ=WEEKLY', '2026-07-07T15:00:00') === 'Repeats weekly on Tuesday');
check('humanize: multi-day weekly lists days',
      H('FREQ=WEEKLY;BYDAY=MO,WE,FR', '2026-07-06T07:00:00')
      === 'Repeats weekly on Monday, Wednesday and Friday');
check('humanize: monthly nth weekday',
      H('FREQ=MONTHLY;BYDAY=3TH', '2026-07-16T09:00:00')
      === 'Repeats monthly on the third Thursday');
check('humanize: yearly last weekday with month',
      H('FREQ=YEARLY;BYMONTH=7;BYDAY=-1FR', '2026-07-31T09:00:00')
      === 'Repeats yearly on the last Friday of July');
check('humanize: clamp rule explains itself',
      H('FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1', '2026-07-31T19:00:00')
      === 'Repeats monthly on day 31 (or the last day of shorter months)');
check('humanize: plain monthly on day 31 also explains the clamp',
      H('FREQ=MONTHLY', '2026-07-31T19:00:00')
      === 'Repeats monthly on day 31 (or the last day of shorter months)');
check('humanize: interval and UNTIL',
      H('FREQ=WEEKLY;INTERVAL=2;UNTIL=20261231T145959', '2026-07-07T15:00:00')
      === 'Repeats every 2 weeks on Tuesday until 2026-12-31');
check('humanize: legacy value', H('week:1', '2026-07-07T15:00:00')
      === 'Repeats weekly on Tuesday');
check('humanize: empty rule → empty string', H('', '2026-07-07T15:00:00') === '');

console.log(`\nAll ${n} widget DOM tests passed.`);
