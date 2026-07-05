/**
 * week.js — Week view for planr v1.2.2
 *
 * SELF-CONTAINED on purpose: imports only from shared.js (symbols present
 * in every planr version), so this file can be dropped into any install.
 *
 * Multi-day events have ONE start and ONE end datetime. The API delivers
 * them pre-segmented:
 *   spanning_events — all-day events + the MIDDLE days of timed multi-day
 *                     events → stacked bars in the all-day lane row
 *   timed_by_day    — single-day events + the first/last-day segments of
 *                     timed multi-day events (seg_start_at / seg_end_at,
 *                     cont_before / cont_after) → blocks on the grid,
 *                     labelled "09:00 →" on the first day, "→ 16:00" on
 *                     the last.
 */
import {
  api, todayStr, getURLParam, setURLParam,
  addDays, mondayOf, fmtWeekRange, fmtTime, esc, toast,
  initNav, initCapture, initRootFilter, filterByRoot,
  openTaskModal, openEventModal, openEventView, openTaskView, IMP_COLOR,
} from '/static/js/shared.js?v=6';

const GRID_START  = 6;    // 06:00
const GRID_END    = 22;   // 22:00
const PX_PER_HOUR = 60;
const GRID_H      = (GRID_END - GRID_START) * PX_PER_HOUR;
const DAY_NAMES   = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

let weekStart    = '';
let nowLineTimer = null;

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initCapture(load);
  initRootFilter(load);

  weekStart = mondayOf(getURLParam('date', todayStr()));

  ensureAlldayRow();
  buildGutter();

  document.getElementById('btn-prev').onclick  = () => goTo(addDays(weekStart, -7));
  document.getElementById('btn-next').onclick  = () => goTo(addDays(weekStart, 7));
  document.getElementById('btn-today').onclick = () => goTo(mondayOf(todayStr()));
  document.getElementById('btn-add-event').onclick = () => openEventModal({}, load);
  document.getElementById('btn-add-task').onclick  = () => openTaskModal({}, load);

  document.addEventListener('keydown', e => {
    if (e.target.matches('input, textarea, select') || e.ctrlKey || e.metaKey || e.altKey) return;
    if (!document.getElementById('modal-overlay')?.classList.contains('hidden')) return;
    if (e.key === 'ArrowLeft')  goTo(addDays(weekStart, -7));
    else if (e.key === 'ArrowRight') goTo(addDays(weekStart, 7));
    else if (e.key === 't') goTo(mondayOf(todayStr()));
    else if (e.key === 'd') location.href = `/day?date=${weekStart}`;
    else if (e.key === 'm') location.href = `/month?date=${weekStart}`;
  });

  load();
});

function goTo(d) {
  weekStart = d;
  setURLParam('date', d);
  load();
}

/** Create the all-day lane row if the template predates it (cache safety). */
function ensureAlldayRow() {
  if (document.getElementById('week-allday-lanes')) return;
  const row = document.createElement('div');
  row.className = 'week-allday-row';
  row.innerHTML = `<div class="week-allday-gutter"></div>
    <div class="week-allday-lanes" id="week-allday-lanes"></div>`;
  const body = document.getElementById('week-body');
  body.parentNode.insertBefore(row, body);
  // .week-outer is grid-template-rows: auto 1fr — make room for the new row
  body.parentNode.style.gridTemplateRows = 'auto auto 1fr';
}

function buildGutter() {
  const gutter = document.getElementById('week-time-col');
  gutter.style.height = GRID_H + 'px';
  for (let h = GRID_START; h < GRID_END; h++) {
    const top = (h - GRID_START) * PX_PER_HOUR;
    const lbl = document.createElement('span');
    lbl.className = 'tg-label';
    lbl.style.top = top + 'px';
    lbl.textContent = `${String(h).padStart(2,'0')}:00`;
    gutter.appendChild(lbl);
    const line = document.createElement('div');
    line.className = 'tg-hour';
    line.style.top = top + 'px';
    gutter.appendChild(line);
  }
}

// ── Load ─────────────────────────────────────────────────────────────────────

async function load() {
  document.getElementById('week-label').textContent = fmtWeekRange(weekStart);

  let data = { days: [], spanning_events: [], timed_by_day: {}, tasks_by_day: {} };
  try {
    data = await api.get('/calendar/week', { start_date: weekStart });
  } catch (err) {
    toast(`Week data failed: ${err.message}`, 'err');
  }
  if (!data.days?.length)
    data.days = Array.from({length: 7}, (_, i) => addDays(weekStart, i));

  const header = document.getElementById('week-header');
  const body   = document.getElementById('week-body');
  const today  = todayStr();

  header.querySelectorAll('.week-dh-wrap').forEach(el => el.remove());
  body.querySelectorAll('.week-day-col').forEach(el => el.remove());
  stopNowLine();

  renderSpanning(filterByRoot(data.spanning_events || []));

  let todayCol = null;
  for (let i = 0; i < 7; i++) {
    const dateStr = data.days[i];
    const isT = dateStr === today;

    const hd = document.createElement('div');
    hd.className = `week-header-col week-dh-wrap${isT ? ' today' : ''}`;
    hd.innerHTML = `<div class="week-dh${isT ? ' today' : ''}">
      <div class="dn">${DAY_NAMES[i]}</div>
      <div class="dd">${dateStr.slice(8)}</div>
    </div>`;
    hd.addEventListener('click', () => location.href = `/day?date=${dateStr}`);
    header.appendChild(hd);

    const col = document.createElement('div');
    col.className = 'week-day-col';
    col.style.height = GRID_H + 'px';
    col.dataset.date = dateStr;
    for (let h = GRID_START; h < GRID_END; h++) {
      const line = document.createElement('div');
      line.className = 'tg-hour';
      line.style.top = ((h - GRID_START) * PX_PER_HOUR) + 'px';
      col.appendChild(line);
    }

    for (const { ev, col: c, cols, sm, em } of layoutTimed(filterByRoot(data.timed_by_day?.[dateStr] || []))) {
      const block = makeTimedBlock(ev, c, cols, sm, em, 2, false);
      if (block) col.appendChild(block);
    }

    const dayTasks = filterByRoot(data.tasks_by_day?.[dateStr] || []);
    if (dayTasks.length) {
      const tray = document.createElement('div');
      tray.className = 'week-task-tray';
      for (const t of dayTasks.slice(0, 3)) {
        const chip = document.createElement('div');
        chip.className = 'week-task-chip';
        chip.style.borderLeftColor = IMP_COLOR[t.importance] || IMP_COLOR.normal;
        chip.textContent = t.title;
        chip.title = `${t.title} — due ${t.due_at.slice(0,10)}`;
        chip.onclick = e => { e.stopPropagation(); openTaskView(t, load); };
        tray.appendChild(chip);
      }
      if (dayTasks.length > 3) {
        const more = document.createElement('div');
        more.className = 'week-task-more';
        more.textContent = `+${dayTasks.length - 3} tasks`;
        more.onclick = () => location.href = `/day?date=${dateStr}`;
        tray.appendChild(more);
      }
      col.appendChild(tray);
    }

    if (isT) todayCol = col;
    body.appendChild(col);
  }

  if (todayCol) startNowLine(todayCol);
}

/** Stack spanning bars into lanes (greedy interval scheduling). */
function renderSpanning(events) {
  const lanesEl = document.getElementById('week-allday-lanes');
  lanesEl.innerHTML = '';
  const laneEnds = [];
  const placed = [];

  for (const ev of [...events].sort((a, b) =>
      a.col_start - b.col_start || b.col_span - a.col_span)) {
    let lane = 0;
    while (laneEnds[lane] !== undefined && laneEnds[lane] > ev.col_start) lane++;
    laneEnds[lane] = ev.col_start + ev.col_span;
    placed.push({ ev, lane });
  }

  lanesEl.style.height = (placed.length ? laneEnds.length * 22 + 4 : 8) + 'px';

  for (const { ev, lane } of placed) {
    const c  = ev.context_color || '#4B5563';
    const rc = ev.root_color || c;
    const bar = document.createElement('div');
    bar.className = 'week-span-bar'
      + (ev.continues_before ? ' cont-l' : '')
      + (ev.continues_after  ? ' cont-r' : '');
    bar.style.cssText = `
      left: ${ev.col_start / 7 * 100}%;
      width: calc(${ev.col_span / 7 * 100}% - ${ev.continues_after ? 0 : 6}px);
      top: ${lane * 22 + 2}px;
      background: ${c}33; border-color: ${c}; border-left-color: ${rc}; color: ${c};
    `;
    bar.innerHTML = `${ev.continues_before ? '◂ ' : ''}${ev.recurrence ? '↻ ' : ''}${esc(ev.title)}${ev.continues_after ? ' ▸' : ''}`;
    bar.title = ev.all_day
      ? `${ev.title} (${ev.start_date} → ${ev.end_date})`
      : `${ev.title}\n${ev.start_date} ${fmtTime(ev.start_at)} → ${ev.end_date} ${fmtTime(ev.end_at)}`;
    bar.onclick = () => openEventView(ev, load);
    lanesEl.appendChild(bar);
  }
}

// ── Timed-event layout (shared logic, inlined for standalone deploy) ─────────

function isoToMins(iso) {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

function layoutTimed(events) {
  const items = events
    .filter(e => (e.seg_start_at || e.start_at))
    .map(e => {
      const sm = isoToMins(e.seg_start_at || e.start_at);
      const endIso = e.seg_end_at || e.end_at;
      let em = endIso ? isoToMins(endIso) : sm + 60;
      if (endIso?.slice(11, 16) === '23:59') em = 24 * 60;
      if (em <= sm) em = sm + 30;
      return { ev: e, sm, em, col: 0, cols: 1 };
    })
    .sort((a, b) => a.sm - b.sm || b.em - a.em);

  const out = [];
  let cluster = [], colEnds = [], clusterEnd = -1;
  const flush = () => {
    const n = Math.max(1, colEnds.length);
    cluster.forEach(it => { it.cols = n; });
    out.push(...cluster);
    cluster = []; colEnds = []; clusterEnd = -1;
  };
  for (const it of items) {
    if (cluster.length && it.sm >= clusterEnd) flush();
    let c = 0;
    while (colEnds[c] !== undefined && colEnds[c] > it.sm) c++;
    colEnds[c] = it.em;
    it.col = c;
    cluster.push(it);
    clusterEnd = Math.max(clusterEnd, it.em);
  }
  flush();
  return out;
}

function makeTimedBlock(ev, col, cols, sm, em, gutterPx, showRange) {
  const rawTop = (sm / 60 - GRID_START) * PX_PER_HOUR;
  const top    = Math.max(0, rawTop);
  let h = Math.max(20, (em - sm) / 60 * PX_PER_HOUR - (top - rawTop));
  h = Math.min(h, GRID_H - top);
  if (h <= 0) return null;

  const c  = ev.context_color || '#4B5563';
  const rc = ev.root_color || c;
  const el = document.createElement('div');
  el.className = 'ev-block'
    + (ev.cont_before ? ' cont-before' : '')
    + (ev.cont_after  ? ' cont-after'  : '');
  el.style.cssText = `
    top:${top}px; height:${h}px;
    background:${c}22; border-left-color:${rc}; color:${c};
    left:calc(${gutterPx}px + (100% - ${gutterPx + 4}px) * ${col} / ${cols});
    width:calc((100% - ${gutterPx + 4}px) / ${cols} - 2px);
  `;
  let time;
  if (ev.cont_after)       time = `${fmtTime(ev.seg_start_at || ev.start_at)} →`;
  else if (ev.cont_before) time = `→ ${fmtTime(ev.seg_end_at || ev.end_at)}`;
  else time = fmtTime(ev.start_at)
    + (showRange && ev.end_at ? ' – ' + fmtTime(ev.end_at) : '');
  el.innerHTML = `
    <div class="ev-title">${ev.recurrence ? '↻ ' : ''}${esc(ev.title)}</div>
    <div class="ev-time">${time}</div>
  `;
  el.title = ev.total_days > 1
    ? `${ev.title}\n${ev.start_date} ${fmtTime(ev.start_at)} → ${ev.end_date} ${fmtTime(ev.end_at)}`
    : ev.title;
  el.onclick = () => openEventView(ev, load);
  return el;
}

// ── Now line ──────────────────────────────────────────────────────────────────

function startNowLine(container) {
  const draw = () => {
    document.querySelectorAll('.tg-now').forEach(el => el.remove());
    const now  = new Date();
    const mins = now.getHours() * 60 + now.getMinutes();
    if (mins < GRID_START * 60 || mins > GRID_END * 60) return;
    const line = document.createElement('div');
    line.className = 'tg-now';
    line.style.top = ((mins / 60 - GRID_START) * PX_PER_HOUR) + 'px';
    container.appendChild(line);
  };
  draw();
  clearInterval(nowLineTimer);
  nowLineTimer = setInterval(draw, 60_000);
}
function stopNowLine() {
  clearInterval(nowLineTimer);
  document.querySelectorAll('.tg-now').forEach(el => el.remove());
}
