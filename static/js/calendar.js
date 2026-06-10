/**
 * calendar.js — unified calendar page for planr v1.2.0
 *
 * One page, three views (day / week / month) selected via tabs.
 * URL state: /calendar?view=week&date=YYYY-MM-DD
 *
 * Multi-day events (Google Calendar behaviour):
 *   day   → pills in the all-day strip, labelled "day n/m"
 *   week  → spanning bars in a dedicated all-day lane row
 *   month → chips with continuation styling on every day covered
 */
import {
  api, todayStr, getURLParam,
  addDays, mondayOf, fmtDateLong, fmtWeekRange, fmtMonth, fmtTime, isToday,
  esc, initNav, initCapture,
  openTaskModal, openEventModal, renderTaskItem, IMP_COLOR,
} from '/static/js/shared.js';

// ── Time-grid constants (day + week) ─────────────────────────────────────────
const GRID_START  = 6;    // 06:00
const GRID_END    = 22;   // 22:00
const PX_PER_HOUR = 60;
const GRID_H      = (GRID_END - GRID_START) * PX_PER_HOUR;
const DAY_NAMES   = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
const VIEWS       = ['day', 'week', 'month'];

let view         = 'day';
let anchorDate   = '';     // YYYY-MM-DD, meaning depends on view
let effortFilter = '';
let nowLineTimer = null;

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initCapture(load);

  const v = getURLParam('view', 'day');
  view       = VIEWS.includes(v) ? v : 'day';
  anchorDate = getURLParam('date', todayStr());

  buildDayGrid();
  buildWeekGutter();

  document.getElementById('view-tabs').addEventListener('click', e => {
    const tab = e.target.closest('.view-tab');
    if (tab) switchView(tab.dataset.view);
  });
  document.getElementById('btn-prev').onclick  = () => navigate(-1);
  document.getElementById('btn-next').onclick  = () => navigate(1);
  document.getElementById('btn-today').onclick = () => goTo(todayStr());
  document.getElementById('btn-add-event').onclick = () => openEventModal({}, load);
  document.getElementById('btn-add-task').onclick  = () => openTaskModal({}, load);

  document.getElementById('effort-chips').addEventListener('click', e => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    effortFilter = chip.dataset.effort;
    document.querySelectorAll('#effort-chips .chip').forEach(c =>
      c.classList.toggle('on', c === chip));
    loadDayTasks();
  });

  // Keyboard navigation (skipped while typing)
  document.addEventListener('keydown', e => {
    if (e.target.matches('input, textarea, select') || e.ctrlKey || e.metaKey) return;
    if (!document.getElementById('modal-overlay').classList.contains('hidden')) return;
    if (e.key === 'ArrowLeft')  navigate(-1);
    else if (e.key === 'ArrowRight') navigate(1);
    else if (e.key === 't') goTo(todayStr());
    else if (e.key === 'd') switchView('day');
    else if (e.key === 'w') switchView('week');
    else if (e.key === 'm') switchView('month');
  });

  window.addEventListener('popstate', () => {
    view       = getURLParam('view', 'day');
    anchorDate = getURLParam('date', todayStr());
    load();
  });

  load();
});

// ── State / navigation ───────────────────────────────────────────────────────

function switchView(v, date) {
  if (!VIEWS.includes(v)) return;
  view = v;
  if (date) anchorDate = date;
  syncURL();
  load();
}

function syncURL() {
  const p = new URLSearchParams(location.search);
  p.set('view', view); p.set('date', anchorDate);
  history.pushState({}, '', '?' + p);
}

function navigate(delta) {
  if (view === 'day') {
    anchorDate = addDays(anchorDate, delta);
  } else if (view === 'week') {
    anchorDate = addDays(anchorDate, delta * 7);
  } else {
    const d = new Date(anchorDate + 'T12:00:00');
    d.setDate(1);
    d.setMonth(d.getMonth() + delta);
    anchorDate = d.toLocaleDateString('en-CA');
  }
  goTo(anchorDate);
}

function goTo(dateStr) {
  anchorDate = dateStr;
  syncURL();
  load();
}

// ── Load / dispatch ──────────────────────────────────────────────────────────

async function load() {
  // Tabs + per-view chrome
  document.querySelectorAll('.view-tab').forEach(t =>
    t.classList.toggle('on', t.dataset.view === view));
  document.querySelectorAll('.cal-view').forEach(el =>
    el.classList.toggle('hidden', el.id !== `view-${view}`));
  document.getElementById('btn-today').textContent =
    { day: 'Today', week: 'This week', month: 'This month' }[view];

  stopNowLine();
  if (view === 'day')        await loadDay();
  else if (view === 'week')  await loadWeek();
  else                       await loadMonth();
}

// ═════════════════════════════════════════════════════════════════════════════
// DAY VIEW
// ═════════════════════════════════════════════════════════════════════════════

function buildDayGrid() {
  const grid = document.getElementById('day-grid');
  grid.style.height = GRID_H + 'px';
  for (let h = GRID_START; h <= GRID_END; h++) {
    const top = (h - GRID_START) * PX_PER_HOUR;
    const row = document.createElement('div');
    row.className = 'tg-hour';
    row.style.top = top + 'px';
    grid.appendChild(row);
    if (h < GRID_END) {
      const lbl = document.createElement('span');
      lbl.className = 'tg-label';
      lbl.style.top = top + 'px';
      lbl.textContent = `${String(h).padStart(2,'0')}:00`;
      grid.appendChild(lbl);
    }
  }
}

async function loadDay() {
  document.getElementById('cal-label').textContent = fmtDateLong(anchorDate);
  await Promise.all([loadDayEvents(), loadDayTasks()]);
  if (isToday(anchorDate)) startNowLine('day-grid');
}

async function loadDayEvents() {
  const data = await api.get('/calendar/day', { date_str: anchorDate });

  // All-day strip: true all-day + multi-day events
  const strip = document.getElementById('day-allday');
  strip.innerHTML = '';
  for (const ev of data.all_day_events) {
    const pill = document.createElement('div');
    pill.className = 'allday-pill';
    pill.style.background = ev.context_color || '#4B5563';
    const span = ev.total_days > 1
      ? ` <span class="pill-span">d${ev.day_index}/${ev.total_days}</span>` : '';
    pill.innerHTML = esc(ev.title) + span;
    pill.title = ev.total_days > 1
      ? `${ev.title} (${ev.start_date} → ${ev.end_date})` : ev.title;
    pill.onclick = () => openEventModal(ev, load, load);
    strip.appendChild(pill);
  }

  // Timed events
  const grid = document.getElementById('day-grid');
  grid.querySelectorAll('.ev-block').forEach(el => el.remove());
  for (const { ev, col, cols, sm, em } of layoutTimed(data.timed_events)) {
    grid.appendChild(makeTimedBlock(ev, col, cols, sm, em, 56, true));
  }
}

async function loadDayTasks() {
  const tasks = await api.get(`/tasks/day/${anchorDate}`, { effort: effortFilter });
  const list = document.getElementById('day-tasks');
  list.innerHTML = '';
  if (!tasks.length) {
    list.innerHTML = '<div class="empty"><span class="empty-icon">✓</span>Nothing due today</div>';
    return;
  }
  for (const t of tasks) list.appendChild(renderTaskItem(t, onTaskCheck, onTaskOpen));
}

async function onTaskCheck(t, el) {
  const ns = t.status === 'done' ? 'active' : 'done';
  await api.put(`/tasks/${t.uuid}`, { status: ns });
  t.status = ns;
  el.classList.toggle('done', ns === 'done');
  el.querySelector('.t-check').textContent = ns === 'done' ? '✓' : '';
}
function onTaskOpen(t) { openTaskModal(t, load, load); }

// ═════════════════════════════════════════════════════════════════════════════
// WEEK VIEW
// ═════════════════════════════════════════════════════════════════════════════

function buildWeekGutter() {
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

async function loadWeek() {
  const weekStart = mondayOf(anchorDate);
  document.getElementById('cal-label').textContent = fmtWeekRange(weekStart);

  const data   = await api.get('/calendar/week', { start_date: weekStart });
  const header = document.getElementById('week-header');
  const body   = document.getElementById('week-body');
  const today  = todayStr();
  body._todayCol = null;

  header.querySelectorAll('.week-dh-wrap').forEach(el => el.remove());
  body.querySelectorAll('.week-day-col').forEach(el => el.remove());

  // Spanning (all-day + multi-day) events → lane bars
  renderWeekSpanning(data.spanning_events);

  for (let i = 0; i < 7; i++) {
    const dateStr = data.days[i];
    const isT = dateStr === today;

    // Header cell
    const hd = document.createElement('div');
    hd.className = `week-header-col week-dh-wrap${isT ? ' today' : ''}`;
    hd.innerHTML = `<div class="week-dh${isT ? ' today' : ''}">
      <div class="dn">${DAY_NAMES[i]}</div>
      <div class="dd">${dateStr.slice(8)}</div>
    </div>`;
    hd.addEventListener('click', () => switchView('day', dateStr));
    header.appendChild(hd);

    // Day column
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

    // Timed single-day events (overlap-aware)
    for (const { ev, col: c, cols, sm, em } of layoutTimed(data.timed_by_day[dateStr] || [])) {
      col.appendChild(makeTimedBlock(ev, c, cols, sm, em, 2, false));
    }

    // Task deadlines: small chips pinned at the bottom of the column
    const dayTasks = data.tasks_by_day[dateStr] || [];
    if (dayTasks.length) {
      const tray = document.createElement('div');
      tray.className = 'week-task-tray';
      for (const t of dayTasks.slice(0, 3)) {
        const chip = document.createElement('div');
        chip.className = 'week-task-chip';
        chip.style.borderLeftColor = IMP_COLOR[t.importance] || IMP_COLOR.normal;
        chip.textContent = t.title;
        chip.title = `${t.title} — due ${t.due_at.slice(0,10)}`;
        chip.onclick = e => { e.stopPropagation(); openTaskModal(t, load, load); };
        tray.appendChild(chip);
      }
      if (dayTasks.length > 3) {
        const more = document.createElement('div');
        more.className = 'week-task-more';
        more.textContent = `+${dayTasks.length - 3} tasks`;
        more.onclick = () => switchView('day', dateStr);
        tray.appendChild(more);
      }
      col.appendChild(tray);
    }

    if (isT) body._todayCol = col;
    body.appendChild(col);
  }

  if (body._todayCol) startNowLine(null, body._todayCol);
}

/** Lay spanning events into stacked lanes (greedy interval scheduling). */
function renderWeekSpanning(events) {
  const lanesEl = document.getElementById('week-allday-lanes');
  lanesEl.innerHTML = '';
  const laneEnds = [];   // last occupied column (exclusive) per lane
  const placed = [];

  for (const ev of [...events].sort((a, b) =>
      a.col_start - b.col_start || b.col_span - a.col_span)) {
    let lane = 0;
    while (laneEnds[lane] !== undefined && laneEnds[lane] > ev.col_start) lane++;
    laneEnds[lane] = ev.col_start + ev.col_span;
    placed.push({ ev, lane });
  }

  const laneCount = Math.max(1, laneEnds.length);
  lanesEl.style.height = (placed.length ? laneCount * 22 + 4 : 8) + 'px';

  for (const { ev, lane } of placed) {
    const c   = ev.context_color || '#4B5563';
    const bar = document.createElement('div');
    bar.className = 'week-span-bar'
      + (ev.continues_before ? ' cont-l' : '')
      + (ev.continues_after  ? ' cont-r' : '');
    bar.style.cssText = `
      left: ${ev.col_start / 7 * 100}%;
      width: calc(${ev.col_span / 7 * 100}% - ${ev.continues_after ? 0 : 6}px);
      top: ${lane * 22 + 2}px;
      background: ${c}33; border-color: ${c}; color: ${c};
    `;
    const time = (!ev.all_day && ev.total_days > 1) ? `${fmtTime(ev.start_at)} ` : '';
    bar.innerHTML = `${ev.continues_before ? '◂ ' : ''}${time}${esc(ev.title)}${ev.continues_after ? ' ▸' : ''}`;
    bar.title = `${ev.title} (${ev.start_date} → ${ev.end_date})`;
    bar.onclick = () => openEventModal(ev, load, load);
    lanesEl.appendChild(bar);
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// MONTH VIEW
// ═════════════════════════════════════════════════════════════════════════════

async function loadMonth() {
  const ref   = new Date(anchorDate + 'T12:00:00');
  const year  = ref.getFullYear();
  const month = ref.getMonth() + 1;

  document.getElementById('cal-label').textContent = fmtMonth(year, month);
  const data = await api.get('/calendar/month', { year, month });

  const body = document.getElementById('month-body');
  body.innerHTML = '';

  const first       = new Date(year, month - 1, 1);
  const offset      = (first.getDay() + 6) % 7;          // Monday-first
  const daysInMonth = new Date(year, month, 0).getDate();
  const numRows     = Math.ceil((offset + daysInMonth) / 7);
  body.style.gridTemplateRows = `repeat(${numRows}, 1fr)`;

  const gridStart = new Date(year, month - 1, 1 - offset);
  const today     = todayStr();

  for (let i = 0; i < numRows * 7; i++) {
    const d  = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    const ds = d.toLocaleDateString('en-CA');
    body.appendChild(makeMonthCell(ds, d.getDate(),
      d.getMonth() !== month - 1, data, today));
  }
}

function makeMonthCell(ds, dayNum, isOther, data, today) {
  const cell = document.createElement('div');
  cell.className = `month-cell${ds === today ? ' today' : ''}${isOther ? ' other' : ''}`;

  let html = `<div class="mc-date">${dayNum}</div>`;

  const events = data.events_by_day[ds] || [];
  for (const ev of events.slice(0, 3)) {
    const c = ev.context_color || '#4B5563';
    const cls = 'mc-ev'
      + (ev.spanning && !ev.is_start ? ' cont-l' : '')
      + (ev.spanning && !ev.is_end   ? ' cont-r' : '');
    const label = ev.spanning
      ? (ev.is_start ? esc(ev.title) : '&nbsp;')
      : `<span class="mc-time">${fmtTime(ev.start_at)}</span> ${esc(ev.title)}`;
    html += `<div class="${cls}" style="background:${c};" title="${esc(ev.title)}">${label}</div>`;
  }
  if (events.length > 3)
    html += `<div class="mc-more">+${events.length - 3} more</div>`;

  const tasks = data.tasks_by_day[ds] || [];
  if (tasks.length) {
    html += '<div class="mc-tasks">';
    for (const t of tasks.slice(0, 6))
      html += `<div class="mc-dot" style="background:${IMP_COLOR[t.importance] || IMP_COLOR.normal};" title="${esc(t.title)}"></div>`;
    if (tasks.length > 6)
      html += `<span class="mc-more">+${tasks.length - 6}</span>`;
    html += '</div>';
  }

  cell.innerHTML = html;
  if (!isOther) cell.addEventListener('click', () => switchView('day', ds));
  return cell;
}

// ═════════════════════════════════════════════════════════════════════════════
// Shared: timed-event layout, blocks, now line
// ═════════════════════════════════════════════════════════════════════════════

function isoToMins(iso) {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

/**
 * Overlap-aware column layout. Events are grouped into clusters of
 * transitively overlapping intervals; within a cluster each event gets a
 * column and all share the cluster's column count.
 */
function layoutTimed(events) {
  const items = events
    .filter(e => e.start_at)
    .map(e => {
      const sm = isoToMins(e.start_at);
      let em = e.end_at ? isoToMins(e.end_at) : sm + 60;
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

/** Create a positioned timed-event block. gutterPx = left offset reserved for time labels. */
function makeTimedBlock(ev, col, cols, sm, em, gutterPx, showRange) {
  const rawTop = (sm / 60 - GRID_START) * PX_PER_HOUR;
  const top    = Math.max(0, rawTop);
  let h = Math.max(20, (em - sm) / 60 * PX_PER_HOUR - (top - rawTop));
  h = Math.min(h, GRID_H - top);            // clip to grid window
  if (h <= 0) return document.createDocumentFragment();
  const c = ev.context_color || '#4B5563';

  const el = document.createElement('div');
  el.className = 'ev-block';
  el.style.cssText = `
    top:${top}px; height:${h}px;
    background:${c}22; border-left-color:${c}; color:${c};
    left:calc(${gutterPx}px + (100% - ${gutterPx + 4}px) * ${col} / ${cols});
    width:calc((100% - ${gutterPx + 4}px) / ${cols} - 2px);
  `;
  el.innerHTML = `
    <div class="ev-title">${esc(ev.title)}</div>
    <div class="ev-time">${fmtTime(ev.start_at)}${showRange && ev.end_at ? ' – ' + fmtTime(ev.end_at) : ''}</div>
  `;
  el.onclick = () => openEventModal(ev, load, load);
  return el;
}

function startNowLine(gridId, colEl) {
  const draw = () => {
    document.querySelectorAll('.tg-now').forEach(el => el.remove());
    const now  = new Date();
    const mins = now.getHours() * 60 + now.getMinutes();
    if (mins < GRID_START * 60 || mins > GRID_END * 60) return;
    const line = document.createElement('div');
    line.className = 'tg-now';
    line.style.top = ((mins / 60 - GRID_START) * PX_PER_HOUR) + 'px';
    (colEl || document.getElementById(gridId)).appendChild(line);
  };
  draw();
  clearInterval(nowLineTimer);
  nowLineTimer = setInterval(draw, 60_000);
}
function stopNowLine() {
  clearInterval(nowLineTimer);
  document.querySelectorAll('.tg-now').forEach(el => el.remove());
}
